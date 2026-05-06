"""
db.py — Ed Console Feature Store + Snapshot Database
=====================================================
SQLite database that logs every refresh snapshot for:
  - Predictive model training (outcomes filled in next bar)
  - Rules engine historical lookup
  - Cross-instrument confluence history
  - Model prediction accuracy tracking

Tables:
  snapshots        — one row per refresh per ticker per timeframe
  outcomes         — filled in on next bar (what actually happened)
  predictions      — what the model predicted (measured against outcomes)
  confluence_log   — cross-instrument state per refresh
  level_crosses    — every time price crosses a key level
  model_accuracy   — rolling accuracy metrics per model version

Design principles:
  - Never delete data — append only
  - All monetary values in float (points, not dollars)
  - Timestamps always UTC, displayed in ET
  - NULL is valid — missing data is recorded as NULL not 0
  - Schema is fixed from day 1 — no migrations needed
"""

from __future__ import annotations

import os
import sqlite3
import json
import time as _wall_time
import bisect
import hashlib
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

from db_authority import (
    assert_ed_console_db_env_resolves_safely,
    canonical_console_db_path,
    classify_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional, TypeVar

# ── Canonical timeframe (central config) ───────────────────────────────────
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME
from snapshot_access import require_snapshot_timeframe
from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    OUTCOME_BAR_SPECS,
    OUTCOME_MOVEMENT_V1_SPECS,
    AUTHORITATIVE_1M_SOURCE,
    forward_bar_start_utc,
    bar_complete_by_utc,
)
from movement_target_threshold import (
    directional_and_move_labels_v2,
    invalid_for_dir_target,
    load_movement_thresholds_by_horizon_v1,
    threshold_move_pts_for_slug,
)

# ── Centralized math (single source of truth) ────────────────────────────────
# Direction classification, distance bucketing, and all thresholds live in
# math_exposure.py. db.py MUST NOT define its own versions.
from math_exposure import (
    classify_direction as _classify_direction_central,
    dist_bucket as _dist_bucket,
    bucket_lo as _bucket_lo,
    bucket_hi as _bucket_hi,
    MIN_SAMPLES_STATISTICAL,
)

# Issue 19 / 21 — tier column tuples + audit helpers (single source: similarity_audit)
from similarity_audit import (
    SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS,
    SIMILARITY_TIER_STOP_OUTCOME_COLUMNS,
    query_context_for_similarity,
    structured_constraints_for_tier,
    relaxed_constraints_vs_previous_tier,
    withheld_horizons_report,
    tier_stop_weak_horizons,
    weakest_tracked_horizons,
    widening_summary_from_tiers,
)

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

T = TypeVar("T")

# Tier 1 only: insert_snapshot + upsert_1m_bars (short transactions on the live console DB).
# Heavy work (fill_outcomes, logging_universe, training materialize) must NOT share this lock
# or the UI/SSE path waits tens of seconds behind background writers.
# Exception: upsert_1m_bars runs a bounded incremental governed-outcome refresh for snapshots
# whose BAR_ANCHOR_V1 labels depend on mutated bar rows (same connection, immediately after write).
_TIER1_SNAPSHOT_WRITE_LOCK = threading.Lock()

# One-time EdDB schema bootstrap (single-threaded init; avoids overlapping CREATE/migrate).
_SCHEMA_INIT_LOCK = threading.Lock()

SQLITE_BUSY_MAX_RETRIES = max(1, int(os.environ.get("ED_SQLITE_BUSY_RETRIES", "8")))
SQLITE_BUSY_BASE_SLEEP_SEC = float(os.environ.get("ED_SQLITE_BUSY_BASE_SLEEP_SEC", "0.02"))
SQLITE_BUSY_MAX_SLEEP_SEC = float(os.environ.get("ED_SQLITE_BUSY_MAX_SLEEP_SEC", "0.4"))
SQLITE_LOCK_WAIT_WARN_MS = float(os.environ.get("ED_SQLITE_LOCK_WAIT_WARN_MS", "100"))
SQLITE_WRITE_SLOW_MS = float(os.environ.get("ED_SQLITE_WRITE_SLOW_MS", "500"))


def configure_sqlite_connection(
    conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000
) -> None:
    """
    Production pragmas for any sqlite3 connection touching the console DB.
    Safe to call on every new connection (WAL is idempotent once enabled on the file).
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    except sqlite3.Error:
        pass
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        pass


def similarity_labeled_counts(rows: list) -> dict[str, int]:
    """Labeled direction counts per horizon (same rule as prediction_engine._count_labeled)."""
    out: dict[str, int] = {}
    for col in SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS:
        out[col] = sum(1 for r in rows if r.get(col) in ("up", "down", "flat"))
    return out


def similarity_tier_stop_viable(labeled_by_col: dict[str, int]) -> bool:
    """True iff tiers 1–4 may stop: 1c / 5c / 15c each have enough labeled rows."""
    if not labeled_by_col:
        return False
    return all(
        labeled_by_col.get(col, 0) >= MIN_SAMPLES_STATISTICAL
        for col in SIMILARITY_TIER_STOP_OUTCOME_COLUMNS
    )


def similarity_empirically_viable(labeled_by_col: dict[str, int]) -> bool:
    """True iff every tracked empirical column has enough labeled rows (full histogram set)."""
    if not labeled_by_col:
        return False
    return all(n >= MIN_SAMPLES_STATISTICAL for n in labeled_by_col.values())

# ── Database location (single canonical file per deployment) ────────────────
# Default: data/ed_console.db (see db_authority.canonical_console_db_path).
# ED_CONSOLE_DB: optional override; non-canonical targets require
# ED_CONSOLE_ALLOW_NONCANONICAL_DB=1 (see db_authority).
DB_DIR = Path(__file__).parent / "data"


def _resolve_console_db_path() -> Path:
    env = os.environ.get("ED_CONSOLE_DB", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        assert_ed_console_db_env_resolves_safely(p)
        return p
    return canonical_console_db_path()


DB_PATH = _resolve_console_db_path()

# ── ET timezone ───────────────────────────────────────────────────────────────
ET = timezone(timedelta(hours=-5))   # EST; DST handled by using fixed offset + awareness

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_et() -> datetime:
    return datetime.now(ET)

def utc_ts() -> float:
    return _wall_time.time()


# ════════════════════════════════════════════════════════════════════════════════
# DATACLASSES — typed snapshot structure
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class SnapshotRow:
    """
    One row per refresh per ticker per timeframe.
    Captures everything we know at this moment.
    Outcome fields are NULL until the next bar closes.
    """
    # ── Required fields (no defaults) — must come first ────────────────────────
    ticker:             str
    timeframe:          str             # '1m', '5m', '15m', '1h'
    ts_utc:             float           # unix timestamp UTC
    ts_et:              str             # '2026-02-23 10:47:32 ET' display string
    et_hour:            int             # 0-23 ET hour
    et_minute:          int             # 0-59 ET minute
    market_session:     str             # 'premarket', 'rth', 'afterhours', 'closed'
    spot:               float

    # ── Identity (optional) ────────────────────────────────────────────────────
    expiry:             Optional[str] = None  # '2026-02-23'
    dte:                Optional[int] = None  # days to expiry (ET authority)
    hours_to_expiry:    Optional[float] = None  # hours until 4pm ET on expiry date
    candle_open:        Optional[float] = None
    candle_high:        Optional[float] = None
    candle_low:         Optional[float] = None
    candle_close:       Optional[float] = None
    candle_volume:      Optional[float] = None
    candle_direction:   Optional[str] = None  # 'up', 'down', 'flat'
    candle_body_pts:    Optional[float] = None  # abs(close - open)
    candle_range_pts:   Optional[float] = None  # high - low
    spread:             Optional[float] = None   # bid-ask spread (pts)

    # ── VWAP ─────────────────────────────────────────────────────────────────
    vwap:               Optional[float] = None
    vwap_side:          Optional[str] = None  # 'above', 'below'
    vwap_dist_pts:      Optional[float] = None  # abs(spot - vwap)

    # ── Price action levels ───────────────────────────────────────────────────
    pdh:                Optional[float] = None
    pdl:                Optional[float] = None
    pdc:                Optional[float] = None
    orb_high:           Optional[float] = None
    orb_low:            Optional[float] = None

    # ── Zone (structural: derive_zone / gamma bias) — NOT regime_primary ───────
    zone:               Optional[str] = None  # pin_bull, pin_bear, pin_neutral, pin_chaos, breakout, breakdown
    zone_since_bars:    Optional[int] = None  # alias for zone_since_bars_1m; populated with 1m value
    zone_since_bars_1m: Optional[int] = None  # execution-layer recency (1m bars)
    zone_since_bars_5m: Optional[int] = None  # structure-layer recency (5m bars)
    prev_zone:          Optional[str] = None  # zone on previous snapshot

    # ── Level distances (signed: positive = above spot, negative = below) ─────
    dist_call_gamma_wall:   Optional[float] = None
    dist_put_gamma_wall:    Optional[float] = None
    dist_call_delta_wall:   Optional[float] = None
    dist_put_delta_wall:    Optional[float] = None
    dist_gamma_inflection:  Optional[float] = None
    dist_delta_inflection:  Optional[float] = None
    dist_call_oi_wall:      Optional[float] = None
    dist_put_oi_wall:       Optional[float] = None
    dist_call_vanna_wall:   Optional[float] = None
    dist_put_vanna_wall:    Optional[float] = None

    # ── Level absolute values ─────────────────────────────────────────────────
    call_gamma_wall:    Optional[float] = None
    put_gamma_wall:     Optional[float] = None
    call_delta_wall:    Optional[float] = None
    put_delta_wall:     Optional[float] = None
    gamma_inflection:   Optional[float] = None
    delta_inflection:   Optional[float] = None
    call_oi_wall:       Optional[float] = None
    put_oi_wall:        Optional[float] = None
    call_vanna_wall:    Optional[float] = None
    put_vanna_wall:     Optional[float] = None
    pin_width_pts:      Optional[float] = None  # call_gamma_wall - put_gamma_wall

    # ── Nearest levels ────────────────────────────────────────────────────────
    nearest_above_name: Optional[str] = None
    nearest_above_val:  Optional[float] = None
    nearest_above_dist: Optional[float] = None
    nearest_below_name: Optional[str] = None
    nearest_below_val:  Optional[float] = None
    nearest_below_dist: Optional[float] = None

    # ── Greeks snapshot ───────────────────────────────────────────────────────
    net_gamma:          Optional[float] = None
    net_delta:          Optional[float] = None
    net_vanna:          Optional[float] = None
    charm_net:          Optional[float] = None
    charm_direction:    Optional[str] = None  # 'buying', 'selling', 'neutral'
    charm_drift_toward: Optional[float] = None
    iv_level:           Optional[float] = None  # avg IV across chain
    iv_direction:       Optional[str] = None  # 'expanding', 'contracting', 'flat'
    charm_magnitude:    Optional[float] = None  # abs charm net, normalized
    session_bucket:     Optional[str] = None  # 'open', 'morning', 'midday', 'afternoon', 'close'
    vix_bucket:         Optional[str] = None  # 'low', 'normal', 'elevated', 'high', 'extreme'
    put_call_oi_ratio:  Optional[float] = None
    oi_center:          Optional[float] = None
    gamma_pin:          Optional[float] = None  # strike with highest gamma

    # ── Cross-instrument (SPY when not primary, else NULL) ────────────────────
    spy_spot:           Optional[float] = None
    spy_chg_pct:        Optional[float] = None
    spy_zone:           Optional[str] = None
    spy_vwap_side:      Optional[str] = None
    spy_net_delta:      Optional[float] = None

    qqq_spot:           Optional[float] = None
    qqq_chg_pct:        Optional[float] = None
    qqq_zone:           Optional[str] = None
    qqq_vwap_side:      Optional[str] = None
    qqq_net_delta:      Optional[float] = None
    qqq_vs_spy:         Optional[str] = None  # 'leading', 'lagging', 'inline'
    qqq_vs_spy_delta:   Optional[float] = None  # qqq_chg_pct - spy_chg_pct

    iwm_spot:           Optional[float] = None
    iwm_chg_pct:        Optional[float] = None
    iwm_zone:           Optional[str] = None
    iwm_vwap_side:      Optional[str] = None
    iwm_net_delta:      Optional[float] = None
    iwm_vs_spy:         Optional[str] = None  # 'leading', 'lagging', 'inline'
    iwm_risk_signal:    Optional[str] = None  # 'risk_on', 'risk_off', 'neutral'

    # ── SPY constituents (price % change) ─────────────────────────────────────
    nvda_chg_pct:       Optional[float] = None
    aapl_chg_pct:       Optional[float] = None
    msft_chg_pct:       Optional[float] = None
    amzn_chg_pct:       Optional[float] = None
    googl_chg_pct:      Optional[float] = None
    avgo_chg_pct:       Optional[float] = None
    meta_chg_pct:       Optional[float] = None
    tsla_chg_pct:       Optional[float] = None
    spy_weighted_push:  Optional[float] = None  # weighted % contribution from top 9
    qqq_weighted_push:  Optional[float] = None  # Nasdaq-100 top names (qqq_confluence.weighted_push)

    # ── IWM sector proxies (price % change) ───────────────────────────────────
    kre_chg_pct:        Optional[float] = None  # Financials
    xbi_chg_pct:        Optional[float] = None  # Healthcare/Biotech
    psci_chg_pct:       Optional[float] = None  # Industrials
    xrt_chg_pct:        Optional[float] = None  # Consumer Discretionary
    iwm_weighted_push:  Optional[float] = None  # holdings + sector blend (market_context.iwm_blended_participation_push)

    # ── VIX ───────────────────────────────────────────────────────────────────
    vix_level:          Optional[float] = None
    vix_direction:      Optional[str] = None  # 'rising', 'falling', 'flat'
    vix_vs_prev:        Optional[float] = None  # change vs previous snapshot

    # ── Rules engine output ───────────────────────────────────────────────────
    rules_signal:       Optional[str] = None  # 'long', 'short', 'wait'
    rules_conviction:   Optional[str] = None  # 'high', 'medium', 'low'
    rules_entry:        Optional[float] = None
    rules_stop:         Optional[float] = None
    rules_target:       Optional[float] = None
    call_target2:       Optional[float] = None  # second target from Call card
    rules_summary:      Optional[str] = None  # plain English 2-3 sentences

    # ── Model prediction (filled when model has enough data) ──────────────────
    # 1c = next completed 1m bar (empirical similar-set histogram; same contract as other pred_Nc_*)
    pred_1c_up_prob:    Optional[float] = None
    pred_1c_down_prob:  Optional[float] = None
    pred_1c_flat_prob:  Optional[float] = None
    pred_3c_up_prob:    Optional[float] = None
    pred_3c_down_prob:  Optional[float] = None
    pred_3c_flat_prob:  Optional[float] = None
    pred_5c_up_prob:    Optional[float] = None
    pred_5c_down_prob:  Optional[float] = None
    pred_5c_flat_prob:  Optional[float] = None
    pred_8c_up_prob:    Optional[float] = None
    pred_8c_down_prob:  Optional[float] = None
    pred_8c_flat_prob:  Optional[float] = None
    pred_13c_up_prob:   Optional[float] = None
    pred_13c_down_prob: Optional[float] = None
    pred_13c_flat_prob: Optional[float] = None
    pred_15c_up_prob:   Optional[float] = None  # 15×1m forward — product 15m clock
    pred_15c_down_prob: Optional[float] = None
    pred_15c_flat_prob: Optional[float] = None
    pred_60c_up_prob:   Optional[float] = None  # 60×1m forward — product 60m clock
    pred_60c_down_prob: Optional[float] = None
    pred_60c_flat_prob: Optional[float] = None
    pred_model_version: Optional[str] = None  # 'statistical_v1', 'xgb_v1', etc.
    pred_model_source:  Optional[str] = None  # 'ml', 'rules', 'statistical'
    pred_override_source: Optional[str] = None  # override source if user overrode
    pred_confidence:    Optional[str] = None  # 'low', 'medium', 'high'
    pred_samples_used:  Optional[int] = None  # how many historical snapshots used
    prediction_direction:   Optional[str]   = None  # PredictiveCard.dominant_dir
    prediction_dominant_prob: Optional[float] = None  # PredictiveCard.dominant_prob

    # ── Combined signal ───────────────────────────────────────────────────────
    combined_signal:    Optional[str]   = None  # 'long', 'short', 'wait'
    combined_conviction:Optional[str]   = None  # 'high', 'medium', 'low'
    rules_pred_agree:   Optional[bool]  = None  # do rules and model agree?
    reward_risk:        Optional[float] = None  # R:R to T1 from Call card
    reward_risk2:       Optional[float] = None  # R:R to T2 from Call card

    # ── Regime classification (regime_engine.py env — orthogonal to zone) ─────
    regime_primary:         Optional[str]   = None  # pinning, acceleration, … (not pin_bull/pin_neutral)
    regime_confidence:      Optional[str]   = None  # 'low', 'medium', 'high'
    regime_score:           Optional[float] = None  # 0.0–1.0

    # ── Bayesian fusion (from bayesian_fusion.py) ─────────────────────────────
    fusion_dominant:        Optional[str]   = None  # dominant outcome family
    fusion_dominant_prob:   Optional[float] = None  # probability of dominant
    fusion_dominant_direction: Optional[str] = None  # 'up', 'down', 'flat'
    fusion_prob_down:       Optional[float] = None
    fusion_prob_flat:       Optional[float] = None
    fusion_prob_up:         Optional[float] = None
    fusion_confidence:      Optional[str]   = None  # 'low', 'medium', 'high'
    fusion_breakout:        Optional[float] = None  # posterior P(breakout)
    fusion_pinning:         Optional[float] = None  # posterior P(pinning)
    fusion_continuation:    Optional[float] = None  # posterior P(continuation)
    fusion_reversal:        Optional[float] = None  # posterior P(reversal)
    fusion_vol_expansion:   Optional[float] = None  # posterior P(vol expansion)
    fusion_mean_reversion:  Optional[float] = None  # posterior P(mean reversion)
    fusion_model_agreement: Optional[float] = None  # 0.0–1.0
    fusion_n_models_active: Optional[int]   = None  # how many models ran

    # ── Monte Carlo (from monte_carlo.py) ─────────────────────────────────────
    mc_efe:                 Optional[float] = None  # expected favorable excursion (pts)
    mc_eae:                 Optional[float] = None  # expected adverse excursion (pts)
    mc_containment:         Optional[float] = None  # P(stays within EM)
    mc_expansion:           Optional[float] = None  # P(breaks EM boundary)
    mc_upper_50:            Optional[float] = None  # 87.5th percentile terminal
    mc_lower_50:            Optional[float] = None  # 12.5th percentile terminal
    mc_paths:               Optional[int]   = None  # MC path count
    mc_horizon:             Optional[int]   = None  # MC horizon (bars)
    mc_vol_source:          Optional[str]   = None  # 'garch' or 'blend'
    mc_sigma_value:         Optional[float] = None  # scaled/blended sigma

    # ── Individual model outputs ──────────────────────────────────────────────
    xgb_available:          Optional[bool]  = None
    xgb_dominant:           Optional[str]   = None  # 'up', 'down', 'flat'
    xgb_confidence:         Optional[float] = None
    xgb_approved:           Optional[int]   = None  # boolean 0/1
    lstm_available:         Optional[bool]  = None
    lstm_dominant:          Optional[str]   = None
    lstm_confidence:        Optional[float] = None
    lstm_approved:          Optional[int]   = None  # boolean 0/1
    transformer_available:  Optional[bool]  = None
    transformer_dominant:   Optional[str]   = None  # 'up', 'down', 'flat'
    transformer_confidence: Optional[float] = None
    transformer_approved:   Optional[int]   = None  # boolean 0/1

    # ── Volatility signals ────────────────────────────────────────────────────
    iv_skew:                Optional[float] = None  # IV_put - IV_call at ATM
    realized_vol:           Optional[float] = None  # annualized realized vol %
    atr:                    Optional[float] = None  # average true range (pts)
    iv_rank:                Optional[float] = None  # 0-100 rank vs history
    iv_percentile:          Optional[float] = None  # 0-100 percentile vs history

    # ── Section 8 — Predictive Positioning Signals ────────────────────────────
    dpi_raw:                Optional[float] = None  # dealer pressure index raw
    dpi_normalized:         Optional[float] = None  # 0-100 normalized
    dpi_direction:          Optional[str]   = None  # 'buying', 'selling', 'neutral'
    hedging_flow_score:     Optional[float] = None  # 0-100 composite
    hedging_flow_direction: Optional[str]   = None  # 'buying', 'selling', 'neutral'
    gamma_gradient:         Optional[float] = None  # d(GEX)/d(Price)
    breakout_score:         Optional[float] = None  # 0-100
    pin_score:              Optional[float] = None  # 0-100
    vol_expansion_score:    Optional[float] = None  # 0-100
    sweep_score:            Optional[float] = None  # 0-100

    # ── Session levels + liquidity sweeps ─────────────────────────────────────
    session_high:           Optional[float] = None
    session_low:            Optional[float] = None
    last_sweep_type:        Optional[str]   = None  # 'sweep_high', 'sweep_low'
    last_sweep_level:       Optional[float] = None
    last_sweep_held:        Optional[bool]  = None  # True = failed sweep
    n_sweeps_today:         Optional[int]   = None

    # ── Trade Validation Gate ─────────────────────────────────────────────────
    validation_passed:      Optional[bool]  = None
    structure_valid:        Optional[bool]  = None
    probability_valid:      Optional[bool]  = None
    risk_valid:             Optional[bool]  = None
    validation_summary:     Optional[str]   = None

    # ── Formal Position Sizing ────────────────────────────────────────────────
    r_units:                Optional[float] = None  # 0.00 to 1.25
    execution_mode:         Optional[str]   = None  # NO_TRADE, PROBE, REDUCED, STANDARD, MAX

    # ── Volatility Envelope ───────────────────────────────────────────────────
    vol_env_upper:          Optional[float] = None
    vol_env_lower:          Optional[float] = None

    # ── Level Density ─────────────────────────────────────────────────────────
    level_density_count:    Optional[int]   = None
    level_density_label:    Optional[str]   = None  # 'clear', 'light', 'moderate', 'congested'

    # ── Sector Strength ───────────────────────────────────────────────────────
    sector_leader:          Optional[str]   = None
    sector_laggard:         Optional[str]   = None
    sector_breadth:         Optional[float] = None  # 0-1
    sector_risk_signal:     Optional[str]   = None  # 'risk_on', 'risk_off', 'mixed'

    # ── Index Strength (SPY/QQQ/IWM) ─────────────────────────────────────────
    index_leader:           Optional[str]   = None
    index_laggard:          Optional[str]   = None
    index_breadth:          Optional[float] = None
    index_risk_signal:      Optional[str]   = None

    # ── SPY Holdings Strength (top 8) ─────────────────────────────────────────
    spy_holdings_leader:    Optional[str]   = None
    spy_holdings_laggard:   Optional[str]   = None
    spy_holdings_breadth:   Optional[float] = None
    spy_holdings_risk:      Optional[str]   = None

    # ── IWM Deep Confluence ───────────────────────────────────────────────────
    iwm_risk_regime:        Optional[str]   = None  # 'risk_on', 'risk_off', 'neutral'
    iwm_risk_score:         Optional[float] = None  # 0-100 composite
    spy_iwm_divergence:     Optional[float] = None  # IWM - SPY spread
    spy_iwm_fragile:        Optional[bool]  = None  # SPY up + IWM down
    iwm_early_warning:      Optional[bool]  = None  # risk-off forming
    rotation_signal:        Optional[str]   = None  # 'growth_favored', 'value_favored', 'neutral'

    # ── Bond Yields ───────────────────────────────────────────────────────────
    tnx_yield:              Optional[float] = None  # 10Y Treasury yield
    tnx_chg:                Optional[float] = None  # yield change today
    bond_signal:            Optional[str]   = None  # 'flight_to_safety', 'risk_on', 'rate_stress', 'neutral'

    # ── Order Flow Signals ────────────────────────────────────────────────────
    vol_oi_ratio:           Optional[float] = None  # volume/OI near ATM
    flow_imbalance:         Optional[float] = None  # -1 to +1 bid/ask imbalance
    smart_money_score:      Optional[float] = None  # 0-100 composite
    smart_money_direction:  Optional[str]   = None  # 'bullish', 'bearish', 'neutral'
    iv_model_spread:        Optional[float] = None  # market IV - theoretical IV

    # ── ML-facing dealer pressure (maps from DPI / hedging flow; see server + backfill) ──
    pressure_label:       Optional[str]   = None  # buying, selling, neutral (from dpi/hedge)
    pressure_trend:       Optional[str]   = None  # rising, falling, flat (dpi_normalized vs prior)

    # ── Archived option chain (bid/ask per contract at snapshot time — realized contract PnL eval) ──
    option_chain_json:      Optional[str] = None  # JSON list of contract dicts for snapshot.expiry

    # ── Full replay bundle: walls/totals, regime, OE proof, hold policy (JSON) ──
    replay_context_json:    Optional[str] = None

    # ── Institutional behavior + news context (additive layer; optional APIs) ──
    absorption_score:          Optional[float] = None
    continuation_score:        Optional[float] = None
    liquidity_behavior_label:  Optional[str] = None
    sentiment_composite:       Optional[float] = None
    sentiment_buzz:            Optional[float] = None
    sentiment_finnhub:         Optional[float] = None
    sentiment_av:              Optional[float] = None
    breaking_news_flag:        Optional[int] = None   # 0/1
    breaking_news_headline:    Optional[str] = None
    pre_market_sentiment:      Optional[float] = None

    # ── Outcomes (NULL until fill_outcomes — Issue 4 anchor + Issue 3 forward bar close) ─
    outcome_1c:         Optional[str]   = None  # 'up', 'down', 'flat'
    outcome_3c:         Optional[str]   = None
    outcome_5c:         Optional[str]   = None
    outcome_1c_pts:     Optional[float] = None  # actual point move
    outcome_3c_pts:     Optional[float] = None
    outcome_5c_pts:     Optional[float] = None
    outcome_8c:         Optional[str]   = None
    outcome_8c_pts:     Optional[float] = None
    outcome_13c:        Optional[str]   = None
    outcome_13c_pts:    Optional[float] = None
    outcome_15c:        Optional[str]   = None  # 15×1m bars — true 15m label
    outcome_15c_pts:    Optional[float] = None
    outcome_60c:        Optional[str]   = None  # 60×1m bars — true 60m label
    outcome_60c_pts:    Optional[float] = None
    # Movement-target v1 labels (filled by fill_outcomes / refresh; NULL on fresh inserts)
    outcome_dir_1c:     Optional[str]   = None
    outcome_move_1c:    Optional[str]   = None
    outcome_move_thr_pts_1c: Optional[float] = None
    outcome_dir_3c:     Optional[str]   = None
    outcome_move_3c:    Optional[str]   = None
    outcome_move_thr_pts_3c: Optional[float] = None
    outcome_dir_5c:     Optional[str]   = None
    outcome_move_5c:    Optional[str]   = None
    outcome_move_thr_pts_5c: Optional[float] = None
    outcome_dir_8c:     Optional[str]   = None
    outcome_move_8c:    Optional[str]   = None
    outcome_move_thr_pts_8c: Optional[float] = None
    outcome_dir_13c:    Optional[str]   = None
    outcome_move_13c:   Optional[str]   = None
    outcome_move_thr_pts_13c: Optional[float] = None
    outcome_dir_15c:    Optional[str]   = None
    outcome_move_15c:   Optional[str]   = None
    outcome_move_thr_pts_15c: Optional[float] = None
    outcome_dir_60c:    Optional[str]   = None
    outcome_move_60c:   Optional[str]   = None
    outcome_move_thr_pts_60c: Optional[float] = None
    valid_dir_1c:       Optional[int]   = None
    threshold_move_1c:  Optional[float] = None
    valid_dir_3c:       Optional[int]   = None
    threshold_move_3c:  Optional[float] = None
    valid_dir_5c:       Optional[int]   = None
    threshold_move_5c:  Optional[float] = None
    valid_dir_8c:       Optional[int]   = None
    threshold_move_8c:  Optional[float] = None
    valid_dir_13c:      Optional[int]   = None
    threshold_move_13c: Optional[float] = None
    valid_dir_15c:      Optional[int]   = None
    threshold_move_15c: Optional[float] = None
    valid_dir_60c:      Optional[int]   = None
    threshold_move_60c: Optional[float] = None
    # XGB movement-head probabilities (product ML horizons — legacy / features / comparison only; not policy authority)
    pred_dir_up_prob_1c: Optional[float] = None
    pred_dir_down_prob_1c: Optional[float] = None
    pred_move_prob_1c: Optional[float] = None
    pred_no_move_prob_1c: Optional[float] = None
    pred_dir_up_prob_5c: Optional[float] = None
    pred_dir_down_prob_5c: Optional[float] = None
    pred_move_prob_5c: Optional[float] = None
    pred_no_move_prob_5c: Optional[float] = None
    pred_dir_up_prob_15c: Optional[float] = None
    pred_dir_down_prob_15c: Optional[float] = None
    pred_move_prob_15c: Optional[float] = None
    pred_no_move_prob_15c: Optional[float] = None
    pred_dir_up_prob_60c: Optional[float] = None
    pred_dir_down_prob_60c: Optional[float] = None
    pred_move_prob_60c: Optional[float] = None
    pred_no_move_prob_60c: Optional[float] = None
    pred_1c_dir_up_prob:   Optional[float] = None
    pred_1c_dir_down_prob: Optional[float] = None
    pred_1c_move_prob:     Optional[float] = None
    pred_1c_no_move_prob:  Optional[float] = None
    pred_5c_dir_up_prob:   Optional[float] = None
    pred_5c_dir_down_prob: Optional[float] = None
    pred_5c_move_prob:     Optional[float] = None
    pred_5c_no_move_prob:  Optional[float] = None
    pred_15c_dir_up_prob:   Optional[float] = None
    pred_15c_dir_down_prob: Optional[float] = None
    pred_15c_move_prob:     Optional[float] = None
    pred_15c_no_move_prob:  Optional[float] = None
    pred_60c_dir_up_prob:   Optional[float] = None
    pred_60c_dir_down_prob: Optional[float] = None
    pred_60c_move_prob:     Optional[float] = None
    pred_60c_no_move_prob:  Optional[float] = None
    # Fusion policy substrate (signals: per-horizon stack → MC → fuse); Phase 8/9 authority
    fused_move_prob_1c: Optional[float] = None
    fused_dir_up_prob_1c: Optional[float] = None
    fused_confidence_1c: Optional[float] = None
    fused_contributing_models_1c: Optional[str] = None
    fused_stack_status_1c: Optional[str] = None
    fused_move_prob_3c: Optional[float] = None
    fused_dir_up_prob_3c: Optional[float] = None
    fused_confidence_3c: Optional[float] = None
    fused_contributing_models_3c: Optional[str] = None
    fused_stack_status_3c: Optional[str] = None
    fused_move_prob_5c: Optional[float] = None
    fused_dir_up_prob_5c: Optional[float] = None
    fused_confidence_5c: Optional[float] = None
    fused_contributing_models_5c: Optional[str] = None
    fused_stack_status_5c: Optional[str] = None
    fused_move_prob_8c: Optional[float] = None
    fused_dir_up_prob_8c: Optional[float] = None
    fused_confidence_8c: Optional[float] = None
    fused_contributing_models_8c: Optional[str] = None
    fused_stack_status_8c: Optional[str] = None
    fused_move_prob_13c: Optional[float] = None
    fused_dir_up_prob_13c: Optional[float] = None
    fused_confidence_13c: Optional[float] = None
    fused_contributing_models_13c: Optional[str] = None
    fused_stack_status_13c: Optional[str] = None
    fused_move_prob_15c: Optional[float] = None
    fused_dir_up_prob_15c: Optional[float] = None
    fused_confidence_15c: Optional[float] = None
    fused_contributing_models_15c: Optional[str] = None
    fused_stack_status_15c: Optional[str] = None
    fused_move_prob_60c: Optional[float] = None
    fused_dir_up_prob_60c: Optional[float] = None
    fused_confidence_60c: Optional[float] = None
    fused_contributing_models_60c: Optional[str] = None
    fused_stack_status_60c: Optional[str] = None
    # Replay/backfill aggregate (optional): FULL | PARTIAL | DEGRADED — does not gate rows
    fusion_replay_stack_grade_v1: Optional[str] = None
    outcome_filled:     bool            = False  # all OUTCOME_BAR_SPECS horizons populated (backfill); not used for ML eligibility
    # 3 = bar-close anchor + bar-forward close (Issue 4+3); 2 = invalidated spot-anchor contract
    horizon_outcome_schema_version: int = HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1

    # ── Internal ──────────────────────────────────────────────────────────────
    snapshot_id:        Optional[int]   = None  # set by DB after insert


@dataclass
class LevelCrossEvent:
    """
    Logged every time price crosses a key level.
    Used for breach log + pattern detection.
    """
    ticker:         str
    ts_utc:         float
    ts_et:          str
    level_name:     str         # 'Call Gamma Wall', 'VWAP', etc.
    level_value:    float
    direction:      str         # 'up', 'down'
    spot_at_cross:  float
    zone_before:    Optional[str]
    zone_after:     Optional[str]
    timeframe:      str


@dataclass
class ConfluenceLog:
    """
    Cross-instrument confluence state per refresh.
    Stored separately so we can analyze confluence patterns.
    """
    ts_utc:             float
    ts_et:              str
    primary_ticker:     str

    # Overall confluence signal
    confluence_signal:  str         # 'bullish', 'bearish', 'neutral', 'mixed'
    confluence_score:   float       # -1.0 to +1.0
    instruments_agree:  int         # count of instruments pointing same way
    instruments_total:  int

    # Per instrument state (JSON strings)
    spy_state:          str         # JSON: {zone, vwap_side, net_delta, chg_pct}
    qqq_state:          str
    iwm_state:          str
    vix_state:          str

    # Constituent state (JSON)
    spy_constituents:   str         # JSON list of {ticker, chg_pct, direction}
    iwm_sectors:        str         # JSON list of {ticker, chg_pct, direction}

    # Weighted signals
    spy_push:           Optional[float]
    iwm_push:           Optional[float]
    qqq_vs_spy_delta:   Optional[float]


# ════════════════════════════════════════════════════════════════════════════════
# DATABASE MANAGER
# ════════════════════════════════════════════════════════════════════════════════

class EdDB:
    """
    Main database interface for Ed Console.
    Reads use a fresh connection per call (WAL allows concurrent readers).
    Tier-1 writes (insert_snapshot, upsert_1m_bars) use _tier1_snapshot_write with bounded
    busy retries. All other writes use ordinary connections + SQLite busy_timeout/WAL.
    """

    def __init__(self, db_path: Path = DB_PATH, *, allow_noncanonical: bool | None = None):
        self.db_path = Path(db_path).resolve()
        if not is_canonical_db_path(self.db_path) and not eddb_allow_noncanonical_path(
            allow_noncanonical
        ):
            raise ValueError(
                f"EdDB: non-canonical database path {self.db_path!r} "
                f"(classification={classify_db_path(self.db_path)}). "
                "Pass allow_noncanonical=True, or set ED_CONSOLE_ALLOW_NONCANONICAL_DB=1 "
                "for harness/test/alternate DBs."
            )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _SCHEMA_INIT_LOCK:
            self._bootstrap_sql_guard_suppress = True
            try:
                self._init_schema()
                self._migrate_schema()
                self._ensure_logging_universe_table()
                self._ensure_logging_universe_aux_tables()
                self._ensure_normalized_table()
            finally:
                self._bootstrap_sql_guard_suppress = False
        log.info(f"EdDB initialized at {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        configure_sqlite_connection(conn)
        if not getattr(self, "_bootstrap_sql_guard_suppress", False):
            from db_safety import maybe_install_sql_guard_on_connection

            maybe_install_sql_guard_on_connection(conn, self.db_path)
        return conn

    def _tier1_snapshot_write(self, op: str, ticker: Optional[str], fn: Callable[[], T]) -> T:
        """
        Serialize only hot-path snapshot + 1m bar upserts with bounded sqlite busy/locked retries.
        Retries release the tier-1 lock between attempts.
        """
        db_s = str(self.db_path)
        thread_name = threading.current_thread().name
        total_wait_lock_ms = 0.0
        total_retry_sleep_ms = 0.0
        last_exc: Optional[BaseException] = None
        for attempt in range(1, SQLITE_BUSY_MAX_RETRIES + 1):
            sleep_s = 0.0
            lock_wait_t0 = _wall_time.perf_counter()
            _TIER1_SNAPSHOT_WRITE_LOCK.acquire()
            lock_wait_ms = (_wall_time.perf_counter() - lock_wait_t0) * 1000.0
            total_wait_lock_ms += lock_wait_ms
            if lock_wait_ms >= SQLITE_LOCK_WAIT_WARN_MS:
                log.warning(
                    "sqlite_tier1_lock_wait op=%s ticker=%s db_path=%s wait_ms=%.1f "
                    "attempt=%s/%s thread=%s",
                    op,
                    ticker,
                    db_s,
                    lock_wait_ms,
                    attempt,
                    SQLITE_BUSY_MAX_RETRIES,
                    thread_name,
                )
            exec_t0 = _wall_time.perf_counter()
            try:
                out = fn()
                exec_ms = (_wall_time.perf_counter() - exec_t0) * 1000.0
                if (
                    exec_ms >= SQLITE_WRITE_SLOW_MS
                    or attempt > 1
                    or total_wait_lock_ms >= SQLITE_LOCK_WAIT_WARN_MS
                ):
                    log.info(
                        "sqlite_tier1_ok op=%s ticker=%s db_path=%s attempts=%s exec_ms=%.1f "
                        "lock_wait_ms_total=%.1f retry_sleep_ms_total=%.1f thread=%s",
                        op,
                        ticker,
                        db_s,
                        attempt,
                        exec_ms,
                        total_wait_lock_ms,
                        total_retry_sleep_ms,
                        thread_name,
                    )
                return out
            except sqlite3.OperationalError as e:
                last_exc = e
                em = str(e).lower()
                retryable = "locked" in em or "busy" in em
                if not retryable or attempt >= SQLITE_BUSY_MAX_RETRIES:
                    log.error(
                        "sqlite_tier1_fail op=%s ticker=%s db_path=%s attempts=%s thread=%s err=%s",
                        op,
                        ticker,
                        db_s,
                        attempt,
                        thread_name,
                        e,
                    )
                    raise
                sleep_s = min(
                    SQLITE_BUSY_MAX_SLEEP_SEC,
                    SQLITE_BUSY_BASE_SLEEP_SEC * (2 ** (attempt - 1)),
                )
                log.warning(
                    "sqlite_tier1_busy_retry op=%s ticker=%s db_path=%s attempt=%s/%s sleep_s=%.3f "
                    "thread=%s err=%s",
                    op,
                    ticker,
                    db_s,
                    attempt,
                    SQLITE_BUSY_MAX_RETRIES,
                    sleep_s,
                    thread_name,
                    e,
                )
            finally:
                _TIER1_SNAPSHOT_WRITE_LOCK.release()
            if sleep_s > 0:
                total_retry_sleep_ms += sleep_s * 1000.0
                _wall_time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc

    def get_schema_flag(self, flag_key: str) -> Optional[str]:
        """Return flag_value for an ed_schema_flags row, or None if absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                (flag_key,),
            ).fetchone()
            return str(row[0]) if row and row[0] is not None else None

    def set_schema_flag(
        self,
        flag_key: str,
        flag_value: str,
        set_ts_utc: Optional[float] = None,
    ) -> None:
        """Upsert an auditable schema flag (ed_schema_flags)."""
        ts = float(_wall_time.time() if set_ts_utc is None else set_ts_utc)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(flag_key) DO UPDATE SET
                    flag_value = excluded.flag_value,
                    set_ts_utc = excluded.set_ts_utc
                """,
                (flag_key, flag_value, ts),
            )

    def _init_schema(self):
        """Create all tables if they don't exist. Safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""

            -- ── Snapshots ─────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Identity
                ticker              TEXT    NOT NULL,
                timeframe           TEXT    NOT NULL,
                expiry              TEXT,
                dte                 INTEGER,
                hours_to_expiry     REAL,

                -- Timestamp
                ts_utc              REAL    NOT NULL,
                ts_et               TEXT    NOT NULL,
                et_hour             INTEGER,
                et_minute           INTEGER,
                market_session      TEXT,

                -- Price action
                spot                REAL    NOT NULL,
                candle_open         REAL,
                candle_high         REAL,
                candle_low          REAL,
                candle_close        REAL,
                candle_volume       REAL,
                candle_direction    TEXT,
                candle_body_pts     REAL,
                candle_range_pts    REAL,
                spread              REAL,

                -- VWAP
                vwap                REAL,
                vwap_side           TEXT,
                vwap_dist_pts       REAL,

                -- Price action levels
                pdh                 REAL,
                pdl                 REAL,
                pdc                 REAL,
                orb_high            REAL,
                orb_low             REAL,

                -- Zone
                zone                TEXT,
                zone_since_bars     INTEGER,
                prev_zone           TEXT,

                -- Level distances
                dist_call_gamma_wall    REAL,
                dist_put_gamma_wall     REAL,
                dist_call_delta_wall    REAL,
                dist_put_delta_wall     REAL,
                dist_gamma_inflection   REAL,
                dist_delta_inflection   REAL,
                dist_call_oi_wall       REAL,
                dist_put_oi_wall        REAL,
                dist_call_vanna_wall    REAL,
                dist_put_vanna_wall     REAL,

                -- Level absolute values
                call_gamma_wall     REAL,
                put_gamma_wall      REAL,
                call_delta_wall     REAL,
                put_delta_wall      REAL,
                gamma_inflection    REAL,
                delta_inflection    REAL,
                call_oi_wall        REAL,
                put_oi_wall         REAL,
                call_vanna_wall     REAL,
                put_vanna_wall      REAL,
                pin_width_pts       REAL,

                -- Nearest levels
                nearest_above_name  TEXT,
                nearest_above_val   REAL,
                nearest_above_dist  REAL,
                nearest_below_name  TEXT,
                nearest_below_val   REAL,
                nearest_below_dist  REAL,

                -- Greeks
                net_gamma           REAL,
                net_delta           REAL,
                net_vanna           REAL,
                charm_net           REAL,
                charm_direction     TEXT,
                charm_drift_toward  REAL,
                iv_level            REAL,
                iv_direction        TEXT,
                charm_magnitude     REAL,
                session_bucket      TEXT,
                vix_bucket          TEXT,
                put_call_oi_ratio   REAL,
                oi_center           REAL,
                gamma_pin           REAL,

                -- Cross-instrument SPY
                spy_spot            REAL,
                spy_chg_pct         REAL,
                spy_zone            TEXT,
                spy_vwap_side       TEXT,
                spy_net_delta       REAL,

                -- Cross-instrument QQQ
                qqq_spot            REAL,
                qqq_chg_pct         REAL,
                qqq_zone            TEXT,
                qqq_vwap_side       TEXT,
                qqq_net_delta       REAL,
                qqq_vs_spy          TEXT,
                qqq_vs_spy_delta    REAL,

                -- Cross-instrument IWM
                iwm_spot            REAL,
                iwm_chg_pct         REAL,
                iwm_zone            TEXT,
                iwm_vwap_side       TEXT,
                iwm_net_delta       REAL,
                iwm_vs_spy          TEXT,
                iwm_risk_signal     TEXT,

                -- SPY constituents
                nvda_chg_pct        REAL,
                aapl_chg_pct        REAL,
                msft_chg_pct        REAL,
                amzn_chg_pct        REAL,
                googl_chg_pct       REAL,
                avgo_chg_pct        REAL,
                meta_chg_pct        REAL,
                tsla_chg_pct        REAL,
                spy_weighted_push   REAL,
                qqq_weighted_push   REAL,

                -- IWM sector proxies
                kre_chg_pct         REAL,
                xbi_chg_pct         REAL,
                psci_chg_pct        REAL,
                xrt_chg_pct         REAL,
                iwm_weighted_push   REAL,

                -- VIX
                vix_level           REAL,
                vix_direction       TEXT,
                vix_vs_prev         REAL,

                -- Rules engine output
                rules_signal        TEXT,
                rules_conviction    TEXT,
                rules_entry         REAL,
                rules_stop          REAL,
                rules_target        REAL,
                call_target2        REAL,
                rules_summary       TEXT,

                -- Model predictions
                pred_1c_up_prob     REAL,
                pred_1c_down_prob   REAL,
                pred_1c_flat_prob   REAL,
                pred_3c_up_prob     REAL,
                pred_3c_down_prob   REAL,
                pred_3c_flat_prob   REAL,
                pred_5c_up_prob     REAL,
                pred_5c_down_prob   REAL,
                pred_5c_flat_prob   REAL,
                pred_8c_up_prob     REAL,
                pred_8c_down_prob   REAL,
                pred_8c_flat_prob   REAL,
                pred_13c_up_prob    REAL,
                pred_13c_down_prob  REAL,
                pred_13c_flat_prob  REAL,
                pred_15c_up_prob    REAL,
                pred_15c_down_prob  REAL,
                pred_15c_flat_prob  REAL,
                pred_60c_up_prob    REAL,
                pred_60c_down_prob  REAL,
                pred_60c_flat_prob  REAL,
                pred_model_version  TEXT,
                pred_confidence     TEXT,
                pred_samples_used   INTEGER,
                prediction_direction    TEXT,
                prediction_dominant_prob REAL,

                -- Combined signal
                combined_signal     TEXT,
                combined_conviction TEXT,
                rules_pred_agree    INTEGER,    -- 0/1 boolean

                -- Regime classification
                regime_primary          TEXT,
                regime_confidence       TEXT,
                regime_score            REAL,

                -- Bayesian fusion
                fusion_dominant         TEXT,
                fusion_dominant_prob    REAL,
                fusion_confidence       TEXT,
                fusion_breakout         REAL,
                fusion_pinning          REAL,
                fusion_continuation     REAL,
                fusion_reversal         REAL,
                fusion_vol_expansion    REAL,
                fusion_mean_reversion   REAL,
                fusion_model_agreement  REAL,
                fusion_n_models_active  INTEGER,

                -- Monte Carlo
                mc_efe                  REAL,
                mc_eae                  REAL,
                mc_containment          REAL,
                mc_expansion            REAL,
                mc_upper_50             REAL,
                mc_lower_50             REAL,
                mc_paths                 INTEGER,
                mc_horizon               INTEGER,
                mc_vol_source            TEXT,
                mc_sigma_value           REAL,

                -- Individual model outputs
                xgb_available           INTEGER,
                xgb_dominant            TEXT,
                xgb_confidence          REAL,
                lstm_available          INTEGER,
                lstm_dominant           TEXT,
                lstm_confidence         REAL,
                transformer_available   INTEGER,
                transformer_dominant    TEXT,
                transformer_confidence  REAL,

                -- Volatility signals
                iv_skew                 REAL,
                realized_vol            REAL,
                atr                     REAL,
                iv_rank                 REAL,
                iv_percentile           REAL,

                -- Section 8 predictive signals
                dpi_raw                 REAL,
                dpi_normalized          REAL,
                dpi_direction           TEXT,
                hedging_flow_score      REAL,
                hedging_flow_direction  TEXT,
                gamma_gradient          REAL,
                breakout_score          REAL,
                pin_score               REAL,
                vol_expansion_score     REAL,
                sweep_score             REAL,

                -- Session levels + sweeps
                session_high            REAL,
                session_low             REAL,
                last_sweep_type         TEXT,
                last_sweep_level        REAL,
                last_sweep_held         INTEGER,
                n_sweeps_today          INTEGER,

                -- Trade Validation Gate
                validation_passed       INTEGER,
                structure_valid         INTEGER,
                probability_valid       INTEGER,
                risk_valid              INTEGER,
                validation_summary      TEXT,

                -- Position Sizing
                r_units                 REAL,
                execution_mode          TEXT,

                -- Volatility Envelope
                vol_env_upper           REAL,
                vol_env_lower           REAL,

                -- Level Density
                level_density_count     INTEGER,
                level_density_label     TEXT,

                -- Sector Strength
                sector_leader           TEXT,
                sector_laggard          TEXT,
                sector_breadth          REAL,
                sector_risk_signal      TEXT,

                -- Index Strength
                index_leader            TEXT,
                index_laggard           TEXT,
                index_breadth           REAL,
                index_risk_signal       TEXT,

                -- SPY Holdings Strength
                spy_holdings_leader     TEXT,
                spy_holdings_laggard    TEXT,
                spy_holdings_breadth    REAL,
                spy_holdings_risk       TEXT,

                -- IWM Deep Confluence
                iwm_risk_regime         TEXT,
                iwm_risk_score          REAL,
                spy_iwm_divergence      REAL,
                spy_iwm_fragile         INTEGER,
                iwm_early_warning       INTEGER,
                rotation_signal         TEXT,

                -- Bond Yields
                tnx_yield               REAL,
                tnx_chg                 REAL,
                bond_signal             TEXT,

                -- Order Flow Signals
                vol_oi_ratio            REAL,
                flow_imbalance          REAL,
                smart_money_score       REAL,
                smart_money_direction   TEXT,
                iv_model_spread         REAL,

                -- Outcomes (NULL until filled)
                outcome_1c          TEXT,
                outcome_3c          TEXT,
                outcome_5c          TEXT,
                outcome_1c_pts      REAL,
                outcome_3c_pts      REAL,
                outcome_5c_pts      REAL,
                outcome_8c          TEXT,
                outcome_8c_pts      REAL,
                outcome_13c         TEXT,
                outcome_13c_pts     REAL,
                outcome_15c         TEXT,
                outcome_15c_pts     REAL,
                outcome_60c         TEXT,
                outcome_60c_pts     REAL,
                horizon_outcome_schema_version INTEGER NOT NULL DEFAULT 3,
                outcome_filled      INTEGER DEFAULT 0,

                -- Metadata
                created_at          TEXT DEFAULT (datetime('now'))
            );

            -- Canonical 1m OHLC closes (Schwab history + live accumulator) for bar-based horizon labels
            CREATE TABLE IF NOT EXISTS price_bars_1m (
                ticker              TEXT    NOT NULL,
                bar_start_ts_utc    REAL    NOT NULL,
                bar_end_ts_utc      REAL    NOT NULL,
                open                REAL,
                high                REAL,
                low                 REAL,
                close               REAL    NOT NULL,
                volume              REAL,
                source              TEXT    NOT NULL DEFAULT 'schwab_1m_accumulator_sqlite',
                PRIMARY KEY (ticker, bar_start_ts_utc)
            );
            CREATE INDEX IF NOT EXISTS idx_bars_1m_ticker_start
                ON price_bars_1m(ticker, bar_start_ts_utc);

            CREATE TABLE IF NOT EXISTS ed_schema_flags (
                flag_key    TEXT PRIMARY KEY,
                flag_value  TEXT NOT NULL,
                set_ts_utc  REAL
            );

            -- Indexes for fast lookup
            CREATE INDEX IF NOT EXISTS idx_snap_ticker_tf_ts
                ON snapshots(ticker, timeframe, ts_utc);
            CREATE INDEX IF NOT EXISTS idx_snap_outcome_unfilled
                ON snapshots(ticker, timeframe, outcome_filled)
                WHERE outcome_filled = 0;
            CREATE INDEX IF NOT EXISTS idx_snap_ts
                ON snapshots(ts_utc);

            -- ── Level cross events ────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS level_crosses (
                cross_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT    NOT NULL,
                ts_utc          REAL    NOT NULL,
                ts_et           TEXT    NOT NULL,
                level_name      TEXT    NOT NULL,
                level_value     REAL    NOT NULL,
                direction       TEXT    NOT NULL,
                spot_at_cross   REAL    NOT NULL,
                zone_before     TEXT,
                zone_after      TEXT,
                timeframe       TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cross_ticker_ts
                ON level_crosses(ticker, ts_utc);

            -- ── Confluence log ────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS confluence_log (
                conf_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc              REAL    NOT NULL,
                ts_et               TEXT    NOT NULL,
                primary_ticker      TEXT    NOT NULL,
                confluence_signal   TEXT,
                confluence_score    REAL,
                instruments_agree   INTEGER,
                instruments_total   INTEGER,
                spy_state           TEXT,
                qqq_state           TEXT,
                iwm_state           TEXT,
                vix_state           TEXT,
                spy_constituents    TEXT,
                iwm_sectors         TEXT,
                spy_push            REAL,
                iwm_push            REAL,
                qqq_vs_spy_delta    REAL,
                created_at          TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_conf_ts
                ON confluence_log(ts_utc);

            -- ── Model accuracy tracking ───────────────────────────────────────
            CREATE TABLE IF NOT EXISTS model_accuracy (
                acc_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc              REAL    NOT NULL,
                ticker              TEXT    NOT NULL,
                timeframe           TEXT    NOT NULL,
                model_version       TEXT    NOT NULL,
                horizon             TEXT    NOT NULL,   -- '1c', '3c', '5c'
                total_predictions   INTEGER,
                correct_direction   INTEGER,
                accuracy_pct        REAL,
                avg_confidence      REAL,
                computed_at         TEXT DEFAULT (datetime('now'))
            );

            -- ── Session log ───────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS session_log (
                session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT,
                started_at      TEXT DEFAULT (datetime('now')),
                ended_at        TEXT,
                snapshots_taken INTEGER DEFAULT 0,
                crosses_logged  INTEGER DEFAULT 0
            );

            -- ── Breaking / notable news events (optional persistence) ────────
            CREATE TABLE IF NOT EXISTS news_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                source          TEXT    NOT NULL,
                ticker          TEXT,
                headline        TEXT    NOT NULL,
                sentiment_score REAL,
                impact_level    TEXT,
                url             TEXT,
                raw_json        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_news_ticker_ts ON news_events(ticker, timestamp);
            CREATE INDEX IF NOT EXISTS idx_news_impact_ts ON news_events(impact_level, timestamp);

            """)
        log.info("Schema initialized")

    def _ensure_logging_universe_table(self):
        """Issue 22 — durable background-logging enrollment (additive schema)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe (
                    ticker                     TEXT PRIMARY KEY COLLATE NOCASE,
                    category                   TEXT NOT NULL,
                    enrollment_source          TEXT,
                    enrolled_ts_utc            REAL NOT NULL,
                    last_seen_ts_utc           REAL NOT NULL,
                    last_background_log_ts_utc REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logging_universe_cat "
                "ON logging_universe (category, enrolled_ts_utc)"
            )

    def _ensure_logging_universe_aux_tables(self):
        """Eviction audit + idempotent migration bookkeeping (Issue 22 hardening)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe_eviction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evicted_ticker TEXT NOT NULL,
                    evicted_ts_utc REAL NOT NULL,
                    reason TEXT NOT NULL,
                    cap_limit INTEGER,
                    incoming_ticker TEXT,
                    incoming_enrollment_source TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe_migration_log (
                    name TEXT PRIMARY KEY,
                    completed_ts_utc REAL NOT NULL,
                    source_sha256 TEXT,
                    detail_json TEXT
                )
                """
            )

    def logging_universe_sync_panel_auto(self, panel_candidates: list[str], now_ts: float) -> dict[str, Any]:
        """
        Upsert ``panel_auto`` rows — symbols the app quotes every market-context refresh and must
        therefore receive the same persistent snapshot / 1m pipeline as enrolled user tickers.

        Does not alter existing ``core`` / ``user_persisted`` / ``pinned`` rows. Drops ``panel_auto``
        rows no longer in the desired panel list (e.g. holdings table refresh).
        """
        from production_universe import filter_valid_tickers, is_valid_production_ticker, normalize_production_ticker

        want_list = [normalize_production_ticker(x) for x in filter_valid_tickers(panel_candidates)]
        want_list = [t for t in want_list if t and is_valid_production_ticker(t)]
        want = frozenset(want_list)

        def _do() -> dict[str, Any]:
            upserted = 0
            with self._connect() as conn:
                if not want:
                    conn.execute("DELETE FROM logging_universe WHERE category = 'panel_auto'")
                    return {"upserted": 0, "desired": 0, "symbols": []}

                qmarks = ",".join("?" * len(want))
                conn.execute(
                    f"""
                    DELETE FROM logging_universe
                    WHERE category = 'panel_auto'
                      AND UPPER(ticker) NOT IN ({qmarks})
                    """,
                    tuple(sorted(want)),
                )

                for sym in want_list:
                    row = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (sym,),
                    ).fetchone()
                    cat = str(row[0]) if row else None
                    if cat is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                                (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'panel_auto', 'market_context_panel_v1', ?, ?)
                            """,
                            (sym, now_ts, now_ts),
                        )
                        upserted += 1
                    elif cat == "panel_auto":
                        conn.execute(
                            """
                            UPDATE logging_universe SET
                                last_seen_ts_utc = ?,
                                enrollment_source = 'market_context_panel_v1'
                            WHERE ticker = ? COLLATE NOCASE AND category = 'panel_auto'
                            """,
                            (now_ts, sym),
                        )
                        upserted += 1
                    elif cat in ("core", "user_persisted", "pinned"):
                        continue

            return {"upserted": upserted, "desired": len(want), "symbols": want_list}

        return _do()

    def logging_universe_sync_core(self, core_tickers: list[str], now_ts: float) -> None:
        """Upsert core symbols — always category core (authoritative list from server)."""

        def _do() -> None:
            with self._connect() as conn:
                for raw in core_tickers:
                    t = (raw or "").upper().strip()
                    if not t:
                        continue
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, 'core', 'core_bootstrap', ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            category='core',
                            enrollment_source='core_bootstrap',
                            last_seen_ts_utc=excluded.last_seen_ts_utc
                        """,
                        (t, now_ts, now_ts),
                    )

        _do()

    def logging_universe_upsert_user_persisted(
        self, ticker: str, enrollment_source: str, now_ts: float
    ) -> None:
        """Enroll a non-core symbol for persistent background logging."""
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        t = normalize_production_ticker(ticker)
        if not t:
            return
        if not is_valid_production_ticker(t):
            raise ValueError(
                f"logging_universe_upsert_user_persisted: refusing invalid ticker {ticker!r} "
                f"(normalized {t!r})"
            )

        def _do() -> None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (t, "user_persisted", enrollment_source, now_ts, now_ts),
                    )
                elif cur[0] == "core":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                elif cur[0] == "pinned":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE logging_universe SET
                            last_seen_ts_utc = ?,
                            enrollment_source = ?
                        WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                        """,
                        (now_ts, enrollment_source, t),
                    )

        _do()

    def logging_universe_upsert_pinned(
        self, ticker: str, enrollment_source: str, now_ts: float
    ) -> None:
        """Protect symbol from FIFO eviction (not a core ticker)."""
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        t = normalize_production_ticker(ticker)
        if not t:
            return
        if not is_valid_production_ticker(t):
            raise ValueError(
                f"logging_universe_upsert_pinned: refusing invalid ticker {ticker!r} "
                f"(normalized {t!r})"
            )

        def _do() -> None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, 'pinned', ?, ?, ?)
                        """,
                        (t, enrollment_source, now_ts, now_ts),
                    )
                elif cur[0] == "core":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE logging_universe SET
                            category = 'pinned',
                            enrollment_source = ?,
                            last_seen_ts_utc = ?
                        WHERE ticker = ? COLLATE NOCASE
                        """,
                        (enrollment_source, now_ts, t),
                    )

        _do()

    def logging_universe_unpin_to_user_persisted(self, ticker: str, now_ts: float) -> bool:
        """Downgrade pinned → user_persisted (evictable). Core unchanged."""
        t = (ticker or "").upper().strip()

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if not cur or cur[0] != "pinned":
                    return False
                conn.execute(
                    """
                    UPDATE logging_universe SET
                        category = 'user_persisted',
                        enrollment_source = 'unpinned_from_pin',
                        last_seen_ts_utc = ?
                    WHERE ticker = ? COLLATE NOCASE
                    """,
                    (now_ts, t),
                )
                return True

        return _do()

    def logging_universe_remove_user_persisted(self, ticker: str) -> bool:
        t = (ticker or "").upper().strip()

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM logging_universe
                    WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                    """,
                    (t,),
                )
                return cur.rowcount > 0

        return _do()

    def logging_universe_remove_non_core(self, ticker: str) -> bool:
        """Remove pinned or user_persisted row; never core."""
        t = (ticker or "").upper().strip()

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM logging_universe
                    WHERE ticker = ? COLLATE NOCASE AND category IN ('user_persisted', 'pinned')
                    """,
                    (t,),
                )
                return cur.rowcount > 0

        return _do()

    def logging_universe_prune_invalid_enrollments(self) -> list[str]:
        """
        Remove invalid user_persisted/pinned rows (migration fragments, corrupted keys).

        Core rows are never touched.
        """
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        removed: list[str] = []

        def _do() -> None:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT ticker, category
                    FROM logging_universe
                    WHERE category IN ('user_persisted', 'pinned', 'panel_auto')
                    """
                ).fetchall()
                for r in rows:
                    raw = str(r[0] or "")
                    cat = str(r[1] or "")
                    t = normalize_production_ticker(raw)
                    if is_valid_production_ticker(t):
                        continue
                    cur = conn.execute(
                        "DELETE FROM logging_universe WHERE ticker = ? COLLATE NOCASE AND category = ?",
                        (raw, cat),
                    )
                    if cur.rowcount and int(cur.rowcount) > 0:
                        removed.append(raw)

        _do()
        return removed

    def logging_universe_record_eviction(
        self,
        *,
        evicted_ticker: str,
        evicted_ts_utc: float,
        reason: str,
        cap_limit: Optional[int] = None,
        incoming_ticker: Optional[str] = None,
        incoming_enrollment_source: Optional[str] = None,
    ) -> None:
        ev = evicted_ticker.upper().strip()

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO logging_universe_eviction_log
                        (evicted_ticker, evicted_ts_utc, reason, cap_limit,
                         incoming_ticker, incoming_enrollment_source)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        ev,
                        evicted_ts_utc,
                        reason,
                        cap_limit,
                        incoming_ticker,
                        incoming_enrollment_source,
                    ),
                )

        _do()

    def logging_universe_recent_evictions(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM logging_universe_eviction_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def logging_universe_eviction_candidates_fifo(self) -> list[str]:
        """user_persisted only, oldest enrolled first — next eviction order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category = 'user_persisted'
                ORDER BY enrolled_ts_utc ASC, ticker COLLATE NOCASE
                """
            ).fetchall()
            return [str(r[0]).upper() for r in rows]

    def logging_universe_protected_tickers(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category IN ('core', 'pinned', 'panel_auto')
                ORDER BY ticker COLLATE NOCASE
                """
            ).fetchall()
            return [str(r[0]).upper() for r in rows]

    def logging_universe_pinned_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM logging_universe WHERE category = 'pinned'"
            ).fetchone()
            return int(row[0] or 0)

    def logging_universe_snapshot_ticker_orphans(self) -> list[str]:
        """Distinct snapshot tickers (canonical timeframe) with no logging_universe row.

        Non-empty indicates Issue-22 drift (e.g. raw SQL import) — normal server paths enroll
        before insert_snapshot via server._register_tracked_ticker. Used by /api/logger/status
        and tools/_ticker_coverage_audit_v1.py.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT s.ticker FROM snapshots s
                WHERE s.timeframe = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM logging_universe lu
                    WHERE lu.ticker = s.ticker COLLATE NOCASE
                  )
                ORDER BY s.ticker COLLATE NOCASE
                """,
                (CANONICAL_TIMEFRAME,),
            ).fetchall()
            return [str(r[0]) for r in rows]

    def logging_universe_authoritative_tickers(self) -> list[str]:
        """Sole enrollment authority (Issue 22): core + pinned + panel_auto + user_persisted.

        Background logger, ml_scheduler, and bulk train entry points use this same set.
        ``panel_auto`` is maintained by ``logging_universe_sync_panel_auto`` (market_context panel).
        Rows observed in snapshots are not authority — enroll via server/UI/API or sync_core.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category IN ('core', 'pinned', 'panel_auto', 'user_persisted')
                ORDER BY CASE category
                    WHEN 'core' THEN 0
                    WHEN 'pinned' THEN 1
                    WHEN 'panel_auto' THEN 2
                    WHEN 'user_persisted' THEN 3
                    ELSE 4 END,
                    ticker COLLATE NOCASE
                """
            ).fetchall()
            return [str(r[0]).upper() for r in rows]

    def logging_universe_scheduler_tickers(self) -> list[str]:
        """Alias for scheduler paths — identical to logging_universe_authoritative_tickers."""
        return self.logging_universe_authoritative_tickers()

    def logging_universe_migration_completed(self, name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM logging_universe_migration_log WHERE name = ?",
                (name,),
            ).fetchone()
            return row is not None

    def logging_universe_migration_mark(
        self, name: str, ts: float, source_sha256: str, detail: dict
    ) -> None:
        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (name, ts, source_sha256, json.dumps(detail)),
                )

        _do()

    def logging_universe_import_legacy_json_tickers(
        self,
        tickers: list[str],
        enrollment_source: str,
        now_ts: float,
        core_tickers: list[str],
    ) -> int:
        """Upsert deduped non-core symbols; returns rows touched. Caller runs inside transaction."""
        core_u = {(c or "").upper().strip() for c in core_tickers}
        tickers_copy = list(tickers)
        enr = enrollment_source
        nt = now_ts

        def _do() -> int:
            n = 0
            seen: set[str] = set()
            with self._connect() as conn:
                for raw in tickers_copy:
                    t = str(raw).upper().strip()
                    if not t or t.startswith("$") or t in core_u or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, enr, nt, nt),
                        )
                        n += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET
                              last_seen_ts_utc = ?,
                              enrollment_source = COALESCE(enrollment_source, ?)
                            WHERE ticker = ? COLLATE NOCASE
                            """,
                            (nt, enr, t),
                        )
                        n += 1
            return n

        return _do()

    def logging_universe_migrate_legacy_json_file(
        self,
        *,
        primary_path: Path,
        archive_path: Path,
        core_tickers: list[str],
    ) -> dict:
        """
        Idempotent one-time import of legacy [.logger_tickers.json] list into logging_universe.
        Uses a single transaction; archives primary only after successful commit.
        """
        mname = "legacy_logger_tickers_json_v1"
        if self.logging_universe_migration_completed(mname):
            return {"status": "already_completed", "migration": mname}
        src = primary_path if primary_path.is_file() else None
        archived_only = False
        if src is None and archive_path.is_file():
            src = archive_path
            archived_only = True
        if src is None:
            self.logging_universe_migration_mark(
                mname, _wall_time.time(), "", {"detail": "no_source_file"}
            )
            return {"status": "skipped_no_source", "migration": mname}
        raw_bytes = src.read_bytes()
        h = hashlib.sha256(raw_bytes).hexdigest()
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            return {"status": "error_json", "migration": mname, "error": str(e)}
        if not isinstance(payload, list):
            return {"status": "error_not_list", "migration": mname}
        tickers = [str(x) for x in payload]
        core_u = {(c or "").upper().strip() for c in core_tickers}
        expected = sorted(
            {
                str(t).upper().strip()
                for t in tickers
                if t
                and not str(t).startswith("$")
                and str(t).upper().strip() not in core_u
            }
        )
        now = _wall_time.time()

        def _body() -> dict:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            configure_sqlite_connection(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                seen: set[str] = set()
                imported = 0
                for raw in tickers:
                    t = str(raw).upper().strip()
                    if not t or t.startswith("$") or t in core_u or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, "migrated_logger_tickers_json", now, now),
                        )
                        imported += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET last_seen_ts_utc = ?
                            WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                            """,
                            (now, t),
                        )
                n_db = conn.execute(
                    """
                    SELECT COUNT(*) FROM logging_universe
                    WHERE category = 'user_persisted'
                      AND enrollment_source = 'migrated_logger_tickers_json'
                    """
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (
                        mname,
                        now,
                        h,
                        json.dumps(
                            {
                                "source_path": str(src.resolve()),
                                "archived_only": archived_only,
                                "expected_non_core_symbols": expected,
                                "upsert_touched": imported,
                                "rows_migrated_enrollment": int(n_db),
                            }
                        ),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return {
                "status": "imported",
                "migration": mname,
                "sha256": h,
                "upsert_touched": imported,
                "archived_only": archived_only,
            }

        out = _body()
        if not archived_only and primary_path.is_file():
            try:
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(primary_path), str(archive_path))
            except OSError as e:
                log.warning("legacy logger json archive replace failed: %s", e)
        return out

    def logging_universe_migrate_scheduler_companion_json(
        self,
        *,
        primary_path: Path,
        archive_path: Path,
    ) -> dict:
        """One-time: data/user_scheduler_tickers.json → logging_universe (Issue 22 SSOT)."""
        mname = "scheduler_user_tickers_json_v1"
        if self.logging_universe_migration_completed(mname):
            return {"status": "already_completed", "migration": mname}
        src = primary_path if primary_path.is_file() else None
        archived_only = False
        if src is None and archive_path.is_file():
            src = archive_path
            archived_only = True
        if src is None:
            self.logging_universe_migration_mark(
                mname, _wall_time.time(), "", {"detail": "no_source_file"}
            )
            return {"status": "skipped_no_source", "migration": mname}
        raw = src.read_bytes()
        h = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8"))
            raw_list = data.get("tickers") if isinstance(data, dict) else data
            if not isinstance(raw_list, list):
                raise ValueError("not_a_list")
        except Exception as e:
            return {"status": "error_json", "migration": mname, "error": str(e)}
        now = _wall_time.time()

        def _body() -> dict:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            configure_sqlite_connection(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                n = 0
                seen: set[str] = set()
                for item in raw_list:
                    t = str(item).upper().strip()
                    if not t or t.startswith("$") or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, "migrated_scheduler_user_tickers_json", now, now),
                        )
                        n += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET last_seen_ts_utc = ?
                            WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                            """,
                            (now, t),
                        )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (
                        mname,
                        now,
                        h,
                        json.dumps(
                            {
                                "source": str(src.resolve()),
                                "archived_only": archived_only,
                                "rows_touched": n,
                            }
                        ),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return {"status": "imported", "migration": mname, "rows_touched": n}

        out = _body()
        if not archived_only and primary_path.is_file():
            try:
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(primary_path), str(archive_path))
            except OSError as e:
                log.warning("scheduler json archive replace failed: %s", e)
        return out

    def logging_universe_touch_seen(self, ticker: str, now_ts: float) -> None:
        t = (ticker or "").upper().strip()
        nt = now_ts

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                    (nt, t),
                )

        _do()

    def logging_universe_touch_background_log(self, ticker: str, ts_utc: float) -> None:
        t = (ticker or "").upper().strip()
        tu = ts_utc

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE logging_universe SET last_background_log_ts_utc = ?
                    WHERE ticker = ? COLLATE NOCASE
                    """,
                    (tu, t),
                )

        _do()

    def logging_universe_user_persisted_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM logging_universe WHERE category = 'user_persisted'"
            ).fetchone()
            return int(row[0] or 0)

    def logging_universe_oldest_user_persisted_ticker(self) -> Optional[str]:
        """Must match eviction FIFO head — single deterministic eviction victim."""
        fifo = self.logging_universe_eviction_candidates_fifo()
        return fifo[0] if fifo else None

    def logging_universe_list_rows(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, category, enrollment_source,
                       enrolled_ts_utc, last_seen_ts_utc, last_background_log_ts_utc
                FROM logging_universe
                ORDER BY CASE category
                    WHEN 'core' THEN 0
                    WHEN 'pinned' THEN 1
                    WHEN 'panel_auto' THEN 2
                    WHEN 'user_persisted' THEN 3
                    ELSE 4 END,
                    ticker COLLATE NOCASE
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def logging_universe_list_rows_audit(self) -> list[dict]:
        """Rows + deterministic eviction_status + fifo position for user_persisted."""
        fifo = self.logging_universe_eviction_candidates_fifo()
        fifo_pos = {t: i + 1 for i, t in enumerate(fifo)}
        prot = set(self.logging_universe_protected_tickers())
        out: list[dict] = []
        for row in self.logging_universe_list_rows():
            d = dict(row)
            cat = d.get("category") or ""
            if cat in ("core", "pinned", "panel_auto"):
                d["eviction_status"] = "protected"
                d["eviction_fifo_position"] = None
            elif cat == "user_persisted":
                d["eviction_status"] = "eligible"
                d["eviction_fifo_position"] = fifo_pos.get(d["ticker"].upper().strip())
            else:
                d["eviction_status"] = "unknown"
                d["eviction_fifo_position"] = None
            d["is_protected"] = d["ticker"].upper().strip() in prot
            out.append(d)
        return out

    def _migrate_schema(self):
        """Add columns that may be missing from older databases.
        Safe to call repeatedly — silently skips columns that already exist."""
        from db_safety import (
            assert_critical_row_counts_no_drop,
            backup_console_database,
            critical_table_row_counts,
            preflight_exclusive_sqlite_write,
            skip_automatic_backup,
        )

        _counts_before: dict[str, int] = {}

        NEW_COLUMNS = [
            # (column_name, column_type)
            ("charm_magnitude",     "REAL"),
            ("session_bucket",      "TEXT"),
            ("vix_bucket",          "TEXT"),
            ("pred_8c_up_prob",     "REAL"),
            ("pred_8c_down_prob",   "REAL"),
            ("pred_8c_flat_prob",   "REAL"),
            ("pred_13c_up_prob",    "REAL"),
            ("pred_13c_down_prob",  "REAL"),
            ("pred_13c_flat_prob",  "REAL"),
            ("pred_15c_up_prob",    "REAL"),
            ("pred_15c_down_prob",  "REAL"),
            ("pred_15c_flat_prob",  "REAL"),
            ("outcome_8c",          "TEXT"),
            ("outcome_8c_pts",      "REAL"),
            ("outcome_13c",         "TEXT"),
            ("outcome_13c_pts",     "REAL"),
            ("outcome_15c",         "TEXT"),
            ("outcome_15c_pts",     "REAL"),
            ("outcome_60c",         "TEXT"),
            ("outcome_60c_pts",     "REAL"),
            ("pred_60c_up_prob",    "REAL"),
            ("pred_60c_down_prob",  "REAL"),
            ("pred_60c_flat_prob",  "REAL"),
            ("horizon_outcome_schema_version", "INTEGER"),
            ("call_target2",            "REAL"),
            # ── Model stack (added Session 5) ─────────────────────────
            ("regime_primary",          "TEXT"),
            ("regime_confidence",       "TEXT"),
            ("regime_score",            "REAL"),
            ("fusion_dominant",         "TEXT"),
            ("fusion_dominant_prob",    "REAL"),
            ("fusion_dominant_direction", "TEXT"),
            ("fusion_prob_down",        "REAL"),
            ("fusion_prob_flat",        "REAL"),
            ("fusion_prob_up",          "REAL"),
            ("fusion_confidence",       "TEXT"),
            ("fusion_breakout",         "REAL"),
            ("fusion_pinning",          "REAL"),
            ("fusion_continuation",     "REAL"),
            ("fusion_reversal",         "REAL"),
            ("fusion_vol_expansion",    "REAL"),
            ("fusion_mean_reversion",   "REAL"),
            ("fusion_model_agreement",  "REAL"),
            ("fusion_n_models_active",  "INTEGER"),
            ("mc_efe",                  "REAL"),
            ("mc_eae",                  "REAL"),
            ("mc_containment",          "REAL"),
            ("mc_expansion",            "REAL"),
            ("mc_upper_50",             "REAL"),
            ("mc_lower_50",             "REAL"),
            ("xgb_available",           "INTEGER"),
            ("xgb_dominant",            "TEXT"),
            ("xgb_confidence",          "REAL"),
            ("xgb_approved",            "INTEGER"),
            ("lstm_available",          "INTEGER"),
            ("lstm_dominant",           "TEXT"),
            ("lstm_confidence",         "REAL"),
            ("lstm_approved",           "INTEGER"),
            ("transformer_available",   "INTEGER"),
            ("transformer_dominant",    "TEXT"),
            ("transformer_confidence",  "REAL"),
            ("transformer_approved",    "INTEGER"),
            # ── Volatility signals ─────────────────────────────────
            ("iv_skew",                 "REAL"),
            ("realized_vol",            "REAL"),
            ("atr",                     "REAL"),
            ("iv_rank",                 "REAL"),
            ("iv_percentile",           "REAL"),
            # ── Section 8 predictive signals ───────────────────────
            ("dpi_raw",                 "REAL"),
            ("dpi_normalized",          "REAL"),
            ("dpi_direction",           "TEXT"),
            ("hedging_flow_score",      "REAL"),
            ("hedging_flow_direction",  "TEXT"),
            ("gamma_gradient",          "REAL"),
            ("breakout_score",          "REAL"),
            ("pin_score",               "REAL"),
            ("vol_expansion_score",     "REAL"),
            ("sweep_score",             "REAL"),
            # ── Session levels + sweeps ────────────────────────────
            ("session_high",            "REAL"),
            ("session_low",             "REAL"),
            ("last_sweep_type",         "TEXT"),
            ("last_sweep_level",        "REAL"),
            ("last_sweep_held",         "INTEGER"),
            ("n_sweeps_today",          "INTEGER"),
            # ── Trade Validation Gate ──────────────────────────────
            ("validation_passed",       "INTEGER"),
            ("structure_valid",         "INTEGER"),
            ("probability_valid",       "INTEGER"),
            ("risk_valid",              "INTEGER"),
            ("validation_summary",      "TEXT"),
            # ── Position Sizing ────────────────────────────────────
            ("r_units",                 "REAL"),
            ("execution_mode",          "TEXT"),
            # ── Volatility Envelope ────────────────────────────────
            ("vol_env_upper",           "REAL"),
            ("vol_env_lower",           "REAL"),
            # ── Level Density ──────────────────────────────────────
            ("level_density_count",     "INTEGER"),
            ("level_density_label",     "TEXT"),
            # ── Sector Strength ────────────────────────────────────
            ("sector_leader",           "TEXT"),
            ("sector_laggard",          "TEXT"),
            ("sector_breadth",          "REAL"),
            ("sector_risk_signal",      "TEXT"),
            # ── Index Strength ─────────────────────────────────────
            ("index_leader",            "TEXT"),
            ("index_laggard",           "TEXT"),
            ("index_breadth",           "REAL"),
            ("index_risk_signal",       "TEXT"),
            # ── SPY Holdings Strength ──────────────────────────────
            ("spy_holdings_leader",     "TEXT"),
            ("spy_holdings_laggard",    "TEXT"),
            ("spy_holdings_breadth",    "REAL"),
            ("spy_holdings_risk",       "TEXT"),
            # ── IWM Deep Confluence ────────────────────────────────
            ("iwm_risk_regime",         "TEXT"),
            ("iwm_risk_score",          "REAL"),
            ("spy_iwm_divergence",      "REAL"),
            ("spy_iwm_fragile",         "INTEGER"),
            ("iwm_early_warning",       "INTEGER"),
            ("rotation_signal",         "TEXT"),
            # ── Bond Yields ────────────────────────────────────────
            ("tnx_yield",               "REAL"),
            ("tnx_chg",                 "REAL"),
            ("bond_signal",             "TEXT"),
            # ── Order Flow Signals ─────────────────────────────────
            ("vol_oi_ratio",            "REAL"),
            ("flow_imbalance",          "REAL"),
            ("smart_money_score",       "REAL"),
            ("smart_money_direction",   "TEXT"),
            ("iv_model_spread",         "REAL"),
            ("spread",                  "REAL"),
            # ── DTE / hours to expiry (ET authority) ───────────────────────────
            ("hours_to_expiry",         "REAL"),
            # ── Prediction direction + MC metadata (persistence fix) ───────────
            ("prediction_direction",    "TEXT"),
            ("prediction_dominant_prob", "REAL"),
            ("mc_paths",                "INTEGER"),
            ("mc_horizon",              "INTEGER"),
            ("mc_vol_source",           "TEXT"),
            ("mc_sigma_value",          "REAL"),
            # ── Zone recency (no mixed-clock) ──────────────────────────────────
            ("zone_since_bars_1m",      "INTEGER"),   # execution-layer (1m bars)
            ("zone_since_bars_5m",      "INTEGER"),   # structure-layer (5m bars)
            # ── Option chain archive (realized contract-level eval) ───────────
            ("option_chain_json",       "TEXT"),
            ("replay_context_json",     "TEXT"),
            # ── Institutional behavior + news context ──────────────────────────
            ("absorption_score",         "REAL"),
            ("continuation_score",       "REAL"),
            ("liquidity_behavior_label", "TEXT"),
            ("sentiment_composite",      "REAL"),
            ("sentiment_buzz",           "REAL"),
            ("sentiment_finnhub",        "REAL"),
            ("sentiment_av",             "REAL"),
            ("breaking_news_flag",       "INTEGER"),
            ("breaking_news_headline",   "TEXT"),
            ("pre_market_sentiment",     "REAL"),
            ("qqq_weighted_push",        "REAL"),
        ]

        _snapshot_migration_pending = False
        if is_canonical_db_path(self.db_path) and not skip_automatic_backup():
            try:
                with self._connect() as _cxp:
                    have_cols = {str(r[1]) for r in _cxp.execute("PRAGMA table_info(snapshots)")}
            except sqlite3.OperationalError:
                have_cols = set()
            _snapshot_migration_pending = any(cn not in have_cols for cn, _ in NEW_COLUMNS)

        if (
            is_canonical_db_path(self.db_path)
            and not skip_automatic_backup()
            and _snapshot_migration_pending
        ):
            ok_w, err_w = preflight_exclusive_sqlite_write(self.db_path)
            if not ok_w:
                raise RuntimeError(f"EdDB._migrate_schema: DB lock preflight failed: {err_w}")
            with self._connect() as _c0:
                _counts_before = critical_table_row_counts(_c0)
            _bpath, _mpath, _ = backup_console_database(
                self.db_path,
                operation_name="EdDB._migrate_schema",
            )
            log.info("db_safety: pre-migration backup %s manifest %s", _bpath, _mpath)

        added = 0
        with self._connect() as conn:
            for col_name, col_type in NEW_COLUMNS:
                try:
                    conn.execute(
                        f"ALTER TABLE snapshots ADD COLUMN {col_name} {col_type}"
                    )
                    added += 1
                    log.info(f"DB migration: added column {col_name}")
                except sqlite3.OperationalError:
                    pass  # column already exists
        if added:
            log.info(f"Schema migration: added {added} new columns to snapshots")

        for tbl in ("snapshots_1m_normalized",):
            try:
                with self._connect() as conn:
                    conn.execute(
                        "ALTER TABLE snapshots_1m_normalized ADD COLUMN qqq_weighted_push REAL"
                    )
                log.info("DB migration: added qqq_weighted_push to snapshots_1m_normalized")
            except sqlite3.OperationalError:
                pass

        for col_name, col_type in (
            ("pred_15c_up_prob", "REAL"),
            ("pred_15c_down_prob", "REAL"),
            ("pred_15c_flat_prob", "REAL"),
            ("outcome_15c", "TEXT"),
            ("outcome_15c_pts", "REAL"),
            ("outcome_60c", "TEXT"),
            ("outcome_60c_pts", "REAL"),
            ("pred_60c_up_prob", "REAL"),
            ("pred_60c_down_prob", "REAL"),
            ("pred_60c_flat_prob", "REAL"),
        ):
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE snapshots_1m_normalized ADD COLUMN {col_name} {col_type}"
                    )
                log.info("DB migration: added %s to snapshots_1m_normalized", col_name)
            except sqlite3.OperationalError:
                pass

        # Issue 16: keep snapshots_1m_normalized aligned with snapshots for materialize INSERT.
        # Missing this column caused INSERT to fail silently (transaction rollback) and left
        # training table with NULL outcome_15c / outcome_60c while snapshots were populated.
        try:
            with self._connect() as conn:
                conn.execute(
                    "ALTER TABLE snapshots_1m_normalized ADD COLUMN "
                    "horizon_outcome_schema_version INTEGER NOT NULL DEFAULT "
                    f"{int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}"
                )
                log.info(
                    "DB migration: added horizon_outcome_schema_version to snapshots_1m_normalized"
                )
        except sqlite3.OperationalError:
            pass

        for tbl in ("snapshots_1m_normalized",):
            for col_name, col_type in (
                ("option_chain_json", "TEXT"),
                ("replay_context_json", "TEXT"),
            ):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        for col_name, col_type in (
            ("pressure_label", "TEXT"),
            ("pressure_trend", "TEXT"),
        ):
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        _ctx_cols = (
            ("absorption_score", "REAL"),
            ("continuation_score", "REAL"),
            ("liquidity_behavior_label", "TEXT"),
            ("sentiment_composite", "REAL"),
            ("sentiment_buzz", "REAL"),
            ("sentiment_finnhub", "REAL"),
            ("sentiment_av", "REAL"),
            ("breaking_news_flag", "INTEGER"),
            ("breaking_news_headline", "TEXT"),
            ("pre_market_sentiment", "REAL"),
        )
        for col_name, col_type in _ctx_cols:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        # Movement-target v1/v2: dir, move, valid_dir, threshold_move (+ legacy outcome_move_thr_pts)
        for _dcol, _mcol, _vdcol, _tmcol, _legtcol, _, _slug in OUTCOME_MOVEMENT_V1_SPECS:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (_dcol, "TEXT"),
                    (_mcol, "TEXT"),
                    (_vdcol, "INTEGER"),
                    (_tmcol, "REAL"),
                    (_legtcol, "REAL"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        try:
            from ml_horizon import ML_HORIZON_SLUGS

            _ml_hz = ML_HORIZON_SLUGS
        except Exception:
            _ml_hz = ("1c", "5c", "15c", "60c")
        for _hz in _ml_hz:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (f"pred_{_hz}_dir_up_prob", "REAL"),
                    (f"pred_{_hz}_dir_down_prob", "REAL"),
                    (f"pred_{_hz}_move_prob", "REAL"),
                    (f"pred_{_hz}_no_move_prob", "REAL"),
                    (f"pred_dir_up_prob_{_hz}", "REAL"),
                    (f"pred_dir_down_prob_{_hz}", "REAL"),
                    (f"pred_move_prob_{_hz}", "REAL"),
                    (f"pred_no_move_prob_{_hz}", "REAL"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        # Fusion policy columns (per governed horizon; policy/calibration authority)
        for _hz in _ml_hz:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (f"fused_move_prob_{_hz}", "REAL"),
                    (f"fused_dir_up_prob_{_hz}", "REAL"),
                    (f"fused_confidence_{_hz}", "REAL"),
                    (f"fused_contributing_models_{_hz}", "TEXT"),
                    (f"fused_stack_status_{_hz}", "TEXT"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        for tbl in ("snapshots", "snapshots_1m_normalized"):
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE {tbl} ADD COLUMN fusion_replay_stack_grade_v1 TEXT"
                    )
                log.info("DB migration: added fusion_replay_stack_grade_v1 to %s", tbl)
            except sqlite3.OperationalError:
                pass

        self._migrate_horizon_bar_contract_v1()
        self._migrate_outcome_anchor_bar_canonical()

        if _counts_before and is_canonical_db_path(self.db_path) and not skip_automatic_backup():
            with self._connect() as _c1:
                _after = critical_table_row_counts(_c1)
            assert_critical_row_counts_no_drop(_counts_before, _after)

    def _migrate_horizon_bar_contract_v1(self) -> None:
        """
        Issue 3: one-time auditable invalidation of poll-window outcomes + schema flag.
        All active outcome_* labels use bar-based universal contract (schema version 2).
        """
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_bars_1m (
                    ticker              TEXT    NOT NULL,
                    bar_start_ts_utc    REAL    NOT NULL,
                    bar_end_ts_utc      REAL    NOT NULL,
                    open                REAL,
                    high                REAL,
                    low                 REAL,
                    close               REAL    NOT NULL,
                    volume              REAL,
                    source              TEXT    NOT NULL DEFAULT 'schwab_1m_accumulator_sqlite',
                    PRIMARY KEY (ticker, bar_start_ts_utc)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ed_schema_flags (
                    flag_key    TEXT PRIMARY KEY,
                    flag_value  TEXT NOT NULL,
                    set_ts_utc  REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bars_1m_ticker_start ON price_bars_1m(ticker, bar_start_ts_utc)"
            )
            row = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                ("horizon_bar_v1_legacy_poll_invalidated",),
            ).fetchone()
            if row is not None:
                return
            log.warning(
                "Issue 3 migration: clearing all outcome_* labels written under legacy poll windows; "
                "recomputing only from price_bars_1m (bar close, UTC 1m grid). "
                "Rows set horizon_outcome_schema_version=%s.",
                HORIZON_OUTCOME_SCHEMA_BAR_V1,
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    outcome_1c = NULL, outcome_1c_pts = NULL,
                    outcome_3c = NULL, outcome_3c_pts = NULL,
                    outcome_5c = NULL, outcome_5c_pts = NULL,
                    outcome_8c = NULL, outcome_8c_pts = NULL,
                    outcome_13c = NULL, outcome_13c_pts = NULL,
                    outcome_15c = NULL, outcome_15c_pts = NULL,
                    outcome_60c = NULL, outcome_60c_pts = NULL,
                    outcome_filled = 0,
                    horizon_outcome_schema_version = {int(HORIZON_OUTCOME_SCHEMA_BAR_V1)}
                """
            )
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                """,
                (
                    "horizon_bar_v1_legacy_poll_invalidated",
                    "1",
                    _wall_time.time(),
                ),
            )

    def _migrate_outcome_anchor_bar_canonical(self) -> None:
        """
        Issue 4: one-time invalidation of outcomes whose anchor was snapshots.spot.
        Active contract: schema version 3 — anchor_close from price_bars_1m (bar_end_ts_utc <= ts_utc).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                ("horizon_outcome_anchor_bar_close_v1",),
            ).fetchone()
            if row is not None:
                return
            log.warning(
                "Issue 4 migration: clearing outcome_* / outcome_*_pts that used snapshots.spot as anchor; "
                "anchor is now last completed price_bars_1m close (bar_end_ts_utc <= ts_utc). "
                "Rows set horizon_outcome_schema_version=%s.",
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    outcome_1c = NULL, outcome_1c_pts = NULL,
                    outcome_3c = NULL, outcome_3c_pts = NULL,
                    outcome_5c = NULL, outcome_5c_pts = NULL,
                    outcome_8c = NULL, outcome_8c_pts = NULL,
                    outcome_13c = NULL, outcome_13c_pts = NULL,
                    outcome_15c = NULL, outcome_15c_pts = NULL,
                    outcome_60c = NULL, outcome_60c_pts = NULL,
                    outcome_filled = 0,
                    horizon_outcome_schema_version = {int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}
                WHERE COALESCE(horizon_outcome_schema_version, 0) < {int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}
                """
            )
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                """,
                (
                    "horizon_outcome_anchor_bar_close_v1",
                    "1",
                    _wall_time.time(),
                ),
            )

    def _ensure_normalized_table(self):
        """
        Ensure snapshots_1m_normalized exists for training on resampled 1m data.
        Created from snapshots schema + normalized_from_subminute.
        Historical sub-minute snapshots (timeframe='5m') are resampled here.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
            )
            if cur.fetchone() is not None:
                return

            # Create table with same structure as snapshots + normalized_from_subminute
            conn.execute("""
                CREATE TABLE snapshots_1m_normalized AS
                SELECT s.*, 1 AS normalized_from_subminute
                FROM snapshots s WHERE 0
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snap1m_ticker_ts
                ON snapshots_1m_normalized(ticker, ts_utc)
            """)
            log.info("Created snapshots_1m_normalized table for resampled 1m training data")

    # ════════════════════════════════════════════════════════════════════════
    # SNAPSHOT OPERATIONS
    # ════════════════════════════════════════════════════════════════════════

    def insert_snapshot(self, snap: SnapshotRow) -> int:
        """Insert a snapshot row. Returns the new snapshot_id.

        RULE: All live snapshot inserts MUST use timeframe=CANONICAL_TIMEFRAME (1m).
        Non-canonical timeframe is overridden and logged. This prevents legacy 5m
        writes from any code path.
        """
        d = asdict(snap)
        d.pop("snapshot_id", None)  # let DB assign

        # Enforce canonical 1m — fail loudly if caller passed wrong timeframe
        incoming_tf = d.get("timeframe", "")
        if incoming_tf != CANONICAL_TIMEFRAME:
            log.warning(
                "insert_snapshot: timeframe=%r != canonical %r — OVERRIDING to 1m (caller bug or stale process)",
                incoming_tf,
                CANONICAL_TIMEFRAME,
            )
            d["timeframe"] = CANONICAL_TIMEFRAME

        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO snapshots ({cols}) VALUES ({placeholders})"
        vals = list(d.values())
        tkr_w = str(d.get("ticker", "") or "")

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return self._tier1_snapshot_write("insert_snapshot", tkr_w or None, _do)

    def insert_news_event(
        self,
        *,
        ts_iso: str,
        source: str,
        ticker: Optional[str],
        headline: str,
        sentiment_score: Optional[float] = None,
        impact_level: str = "LOW",
        url: str = "",
        raw_json: str = "",
    ) -> Optional[int]:
        """Append one news row (dedupe by headline+timestamp optional at call site)."""
        if not headline:
            return None
        params = (
            ts_iso,
            source[:64],
            (ticker or "")[:32] or None,
            headline[:2000],
            sentiment_score,
            impact_level[:32],
            (url or "")[:2000],
            (raw_json or "")[:16000],
        )

        def _do() -> Optional[int]:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO news_events
                      (timestamp, source, ticker, headline, sentiment_score, impact_level, url, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
                return int(cur.lastrowid) if cur.lastrowid is not None else None

        return _do()

    def upsert_1m_bars(self, ticker: str, bars: list) -> int:
        """
        Authoritative canonical 1m series for horizon labels (Schwab price history + server accumulator).
        Completed bars only; bar_start_ts_utc matches Candle.ts (epoch seconds, bar open).

        Ticker key uses ticker_storage_key (Issue 19): e.g. SPX -> $SPX for parity with snapshots
        and pin_neutral / fill_outcomes joins; $SPX unchanged.

        After each successful upsert, governed BAR_ANCHOR_V1 snapshot outcomes that depend on any
        mutated bar_start are recomputed in the same connection so stored labels cannot drift.

        Returns count of rows written (after timestamp/OHLC validation), 0 if none.
        """
        tkr = ticker_storage_key(ticker)
        if not tkr or not bars:
            return 0
        rows = []
        for b in bars:
            src = AUTHORITATIVE_1M_SOURCE
            if hasattr(b, "ts"):
                ts = float(b.ts)
                o, h, lo, c = float(b.open), float(b.high), float(b.low), float(b.close)
                vol = float(getattr(b, "volume", 0) or 0)
            elif isinstance(b, dict):
                raw_ts = b.get("datetime", b.get("ts", b.get("timestamp", b.get("_ts", 0))))
                try:
                    raw_ts = float(raw_ts)
                except (TypeError, ValueError):
                    continue
                ts = raw_ts / 1000.0 if raw_ts > 1e10 else raw_ts
                try:
                    o = float(b["open"])
                    h = float(b["high"])
                    lo = float(b["low"])
                    c = float(b["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                vol = float(b.get("volume", 0) or 0)
                if b.get("source"):
                    src = str(b["source"])
            else:
                continue
            # Canonical 60s UTC grid: snap bar open to whole-minute epoch seconds (Schwab / adapters
            # may emit sub-second noise). Large drift (>30s from nearest minute) is rejected.
            raw_ts = float(ts)
            grid_ts = round(raw_ts / 60.0) * 60.0
            if abs(raw_ts - grid_ts) > 30.0:
                log.warning(
                    "upsert_1m_bars: skipping bar far from canonical minute grid ts=%.4f (nearest=%.1f) ticker=%s",
                    raw_ts,
                    grid_ts,
                    tkr,
                )
                continue
            if abs(raw_ts - grid_ts) > 0.25:
                log.info(
                    "upsert_1m_bars: snapped bar ts %.6f -> %.1f ticker=%s",
                    raw_ts,
                    grid_ts,
                    tkr,
                )
            bar_start = grid_ts
            # Reject poison timestamps (0/negative breaks anchor SQL and MIN(); Schwab ms→s is always >> 0).
            if bar_start <= 0:
                continue
            bar_end = bar_start + 60.0
            rows.append((tkr, bar_start, bar_end, o, h, lo, c, vol, src))
        if not rows:
            return 0
        rows_tuple = list(rows)

        def _do() -> int:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc,
                        open, high, low, close, volume, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, bar_start_ts_utc) DO UPDATE SET
                        bar_end_ts_utc = excluded.bar_end_ts_utc,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        source = excluded.source
                    """,
                    rows_tuple,
                )
                n_written = len(rows_tuple)
                changed_bar_starts = {float(r[1]) for r in rows_tuple}
                tz_eval = float(_wall_time.time())
                _refresh_governed_outcomes_after_bar_mutation(
                    conn,
                    tkr=tkr,
                    changed_bar_starts=changed_bar_starts,
                    tz=tz_eval,
                )
                return n_written

        return self._tier1_snapshot_write("upsert_1m_bars", tkr, _do)

    def fill_outcomes(self, ticker: str, timeframe: str, ts_utc_now: float) -> None:
        """
        Universal bar-based horizon outcomes (Issue 3 forward + Issue 4 anchor).

        For each snapshot at time T (ts_utc):
          anchor_close = close of the last price_bars_1m row with bar_end_ts_utc <= T
          forward_close = close of the bar with bar_start_ts_utc = floor((T+N*60)/60)*60
          outcome_Nc = classify_direction(forward_close - anchor_close, anchor_close)

        Poll-window fills are not used. Rows must have horizon_outcome_schema_version = BAR_ANCHOR_V1.

        outcome_filled is set only when every column in OUTCOME_BAR_SPECS is non-null (backfill-queue
        completion). ML training eligibility is per-horizon (label IS NOT NULL); do not use outcome_filled there.
        """
        if timeframe != CANONICAL_TIMEFRAME:
            return

        tkr = ticker_storage_key(ticker)
        if not tkr:
            return

        tz = float(ts_utc_now)
        min_snap_ts = tz - 14 * 86400.0
        # Prefetch forward bars through the longest OUTCOME_BAR_SPECS horizon (+ padding).
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        _bar_start_upper = tz + float(_max_fwd_min) * 60.0 + 120.0
        tf = timeframe

        def _do() -> None:
            with self._connect() as conn:
                close_by_start: dict[float, float] = {}
                for r in conn.execute(
                    """
                    SELECT bar_start_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                    """,
                    (tkr, min_snap_ts - 5000.0, _bar_start_upper),
                ).fetchall():
                    close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])

                bar_end_rows = conn.execute(
                    """
                    SELECT bar_end_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                    ORDER BY bar_end_ts_utc ASC
                    """,
                    (tkr, min_snap_ts - 5000.0, tz),
                ).fetchall()
                bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                bar_end_closes = [float(r["close"]) for r in bar_end_rows]

                unfilled = conn.execute(
                    """
                    SELECT snapshot_id, ts_utc, atr
                    FROM snapshots
                    WHERE ticker = ? AND timeframe = ?
                      AND outcome_filled = 0
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                      AND ts_utc < ? AND ts_utc > ?
                    """,
                    (
                        tkr,
                        tf,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        tz,
                        min_snap_ts,
                    ),
                ).fetchall()

                _apply_bar_based_outcome_updates(
                    conn,
                    tz=tz,
                    unfilled_rows=unfilled,
                    bar_ends=bar_ends,
                    bar_end_closes=bar_end_closes,
                    close_by_start=close_by_start,
                )

        _t0 = _wall_time.perf_counter()
        _do()
        _exec_ms = (_wall_time.perf_counter() - _t0) * 1000.0
        _th = threading.current_thread().name
        _db_s = str(self.db_path)
        if _exec_ms >= 10000.0:
            log.warning(
                "sqlite_bg_write_slow op=fill_outcomes tier=10s+ ticker=%s exec_ms=%.1f thread=%s db_path=%s",
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )
        elif _exec_ms >= 5000.0:
            log.warning(
                "sqlite_bg_write_slow op=fill_outcomes tier=5s+ ticker=%s exec_ms=%.1f thread=%s db_path=%s",
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )
        elif _exec_ms >= 1000.0:
            log.info(
                "sqlite_bg_write op=fill_outcomes ticker=%s exec_ms=%.1f thread=%s db_path=%s",
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )

    def refresh_all_governed_bar_anchor_outcomes_v1(self) -> dict:
        """
        Recompute all BAR_ANCHOR_V1 / 1m snapshot horizon outcomes from current price_bars_1m.

        Use after bulk bar repairs or before governed-dataset certification when labels must
        match authoritative closes. Live upsert_1m_bars already refreshes affected snapshots.
        """
        tz = float(_wall_time.time())
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        _bar_start_upper = tz + float(_max_fwd_min) * 60.0 + 120.0
        audit: dict = {
            "schema": "refresh_all_governed_bar_anchor_outcomes_v1",
            "ts_eval_utc": tz,
            "updates_executed": 0,
            "tickers": [],
        }
        total_updates = 0
        with self._connect() as conn:
            tickers = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT DISTINCT ticker FROM snapshots
                    WHERE timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    """,
                    (
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                )
            ]
            for tkr in tickers:
                rows = conn.execute(
                    """
                    SELECT snapshot_id, ts_utc, atr FROM snapshots
                    WHERE ticker = ? AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                      AND ts_utc < ?
                    """,
                    (
                        tkr,
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        tz,
                    ),
                ).fetchall()
                if not rows:
                    continue
                min_snap_ts = min(float(r["ts_utc"]) for r in rows)
                bar_low = min_snap_ts - 5000.0
                close_by_start: dict[float, float] = {}
                for r in conn.execute(
                    """
                    SELECT bar_start_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                    """,
                    (tkr, bar_low, _bar_start_upper),
                ).fetchall():
                    close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])
                bar_end_rows = conn.execute(
                    """
                    SELECT bar_end_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                    ORDER BY bar_end_ts_utc ASC
                    """,
                    (tkr, bar_low, tz),
                ).fetchall()
                bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                bar_end_closes = [float(r["close"]) for r in bar_end_rows]
                n = _apply_bar_based_outcome_updates(
                    conn,
                    tz=tz,
                    unfilled_rows=rows,
                    bar_ends=bar_ends,
                    bar_end_closes=bar_end_closes,
                    close_by_start=close_by_start,
                    force_refresh=True,
                )
                total_updates += n
                audit["tickers"].append({"ticker": tkr, "updates": n, "snapshots": len(rows)})
        audit["updates_executed"] = total_updates
        return audit

    def refresh_governed_outcomes_for_mutated_bar_starts(
        self,
        ticker: str,
        bar_start_ts_utc: set[float] | list[float],
        *,
        ts_eval_utc: float | None = None,
    ) -> int:
        """
        Recompute BAR_ANCHOR_V1 snapshot rows affected by 1m bars at the given starts.

        Call after any price_bars_1m write that does not go through upsert_1m_bars (e.g. repair SQL).
        """
        tz = float(ts_eval_utc if ts_eval_utc is not None else _wall_time.time())
        tkr = ticker_storage_key(ticker)
        if not tkr:
            return 0
        changed = {float(x) for x in bar_start_ts_utc}
        if not changed:
            return 0
        with self._connect() as conn:
            n = _refresh_governed_outcomes_after_bar_mutation(
                conn, tkr=tkr, changed_bar_starts=changed, tz=tz
            )
            conn.commit()
            return n

    def fill_outcomes_pin_neutral_backfill_v1(
        self,
        *,
        dry_run: bool = False,
    ) -> dict:
        """
        Repair outcomes for historical pin_neutral rows left unfilled because live
        fill_outcomes only considers snapshots in a rolling 14-day window.

        Same bar-anchor contract as fill_outcomes. Evaluation time is wall-clock now
        so forward horizons are complete when 1m bar history exists.

        Scope: zone='pin_neutral', outcome_filled=0, BAR_ANCHOR_V1, **canonical timeframe (1m) only**.
        Legacy ``timeframe='5m'`` rows are **excluded** (counted in ``legacy_timeframe_rows_excluded``)
        so repair does not extend labels into non-canonical snapshot metadata used by Issue 19.
        Labeling still uses ``price_bars_1m`` (same bar grid as ``fill_outcomes``).
        """
        tz = float(_wall_time.time())
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        bar_pad = float(_max_fwd_min) * 60.0 + 120.0
        audit: dict = {
            "schema": "pin_neutral_outcome_repair_v1",
            "dry_run": dry_run,
            "ts_eval_utc": tz,
            "timeframes_in_scope": [CANONICAL_TIMEFRAME],
            "legacy_timeframe_rows_excluded": 0,
            "updates_executed": 0,
            "tickers_touched": [],
            "snapshots_scanned": 0,
        }

        def _do() -> None:
            with self._connect() as conn:
                leg = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM snapshots
                    WHERE zone = 'pin_neutral'
                      AND outcome_filled = 0
                      AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    """,
                    (
                        DERIVED_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                ).fetchone()
                audit["legacy_timeframe_rows_excluded"] = int(leg["n"] if leg else 0)
                if audit["legacy_timeframe_rows_excluded"]:
                    log.info(
                        "fill_outcomes_pin_neutral_backfill_v1: excluding %s legacy %s pin_neutral rows "
                        "(canonical repair is 1m-only)",
                        audit["legacy_timeframe_rows_excluded"],
                        DERIVED_TIMEFRAME,
                    )
                rows = conn.execute(
                    """
                    SELECT ticker, snapshot_id, ts_utc, atr
                    FROM snapshots
                    WHERE zone = 'pin_neutral'
                      AND outcome_filled = 0
                      AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    ORDER BY ticker, ts_utc
                    """,
                    (
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                ).fetchall()
                audit["snapshots_scanned"] = len(rows)
                by_ticker: dict[str, list] = {}
                for r in rows:
                    tkr_row = r["ticker"]
                    by_ticker.setdefault(tkr_row, []).append(r)

                total_updates = 0
                tickers_touched: list[str] = []
                for tkr_raw, trows in sorted(by_ticker.items()):
                    t_key = ticker_storage_key(tkr_raw)
                    min_ts = min(float(x["ts_utc"]) for x in trows)
                    bar_low = min_ts - 120.0 * 86400.0
                    bar_high = tz + bar_pad

                    close_by_start: dict[float, float] = {}
                    for r in conn.execute(
                        """
                        SELECT bar_start_ts_utc, close FROM price_bars_1m
                        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                        """,
                        (t_key, bar_low, bar_high),
                    ).fetchall():
                        close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])

                    bar_end_rows = conn.execute(
                        """
                        SELECT bar_end_ts_utc, close FROM price_bars_1m
                        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                        ORDER BY bar_end_ts_utc ASC
                        """,
                        (t_key, bar_low, tz),
                    ).fetchall()
                    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                    bar_end_closes = [float(r["close"]) for r in bar_end_rows]

                    if dry_run:
                        tickers_touched.append(t_key)
                        continue
                    n = _apply_bar_based_outcome_updates(
                        conn,
                        tz=tz,
                        unfilled_rows=trows,
                        bar_ends=bar_ends,
                        bar_end_closes=bar_end_closes,
                        close_by_start=close_by_start,
                    )
                    total_updates += n
                    if n:
                        tickers_touched.append(t_key)

                audit["updates_executed"] = total_updates
                audit["tickers_touched"] = sorted(set(tickers_touched))

        _do()
        return audit

    def get_recent_snapshots(
        self,
        ticker: str,
        timeframe: str,
        n: int = 5000,
        filled_only: bool = False,
        *,
        as_of_ts_utc: Optional[float] = None,
    ) -> list:
        """Return the N most recent snapshots for a ticker/timeframe (DESC by ts_utc).

        as_of_ts_utc: when set (replay / causal inference), only rows with ts_utc < as_of_ts_utc
        are eligible — same strict ordering contract as get_similar_setups. Default None preserves
        legacy unbounded history reads (training/offline tools must pass explicitly when simulating
        a decision at time T).
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_recent_snapshots")
        ticker = ticker_storage_key(ticker)
        filled_clause = "AND outcome_filled = 1" if filled_only else ""
        asof_clause = " AND ts_utc < ? " if as_of_ts_utc is not None else ""
        params: tuple = (ticker, timeframe)
        if as_of_ts_utc is not None:
            params = params + (float(as_of_ts_utc),)
        params = params + (n,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM snapshots
                WHERE ticker = ? AND timeframe = ?
                {filled_clause}
                {asof_clause}
                ORDER BY ts_utc DESC
                LIMIT ?
            """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_similar_setups(self, ticker: str, timeframe: str,
                            zone: str, vwap_side: str,
                            nearest_above_dist: Optional[float],
                            nearest_below_dist: Optional[float],
                            n_similar: int = 500,
                            *,
                            return_trace: bool = False,
                            as_of_ts_utc: Optional[float] = None) -> list | tuple[list, dict]:
        """
        Find historical snapshots similar to current setup.
        Uses PROGRESSIVE RELAXATION — tries tight match first, then
        loosens criteria until empirical viability is met (Issue 19), or tier 5 is reached.

        Tiers (Issue 19 — stop at the **narrowest** tier where **SIMILARITY_TIER_STOP_OUTCOME_COLUMNS**
        (1c / 5c / 15c) each have >= MIN_SAMPLES_STATISTICAL labeled rows — aligned with
        multi_horizon_decision primary candidates except sparse 60c; same bar as
        prediction_engine._literal_empirical_horizon for those columns):
          1. zone + vwap_side + both distance buckets  (tightest)
          2. zone + vwap_side + above distance bucket only
          3. zone + vwap_side  (drop all distance criteria)
          4. zone only  (drop vwap_side)
          5. all filled snapshots for this ticker  (broadest; always returned if reached)

        SQL still requires outcome_1c IS NOT NULL for pool membership; tier-stop viability uses
        SIMILARITY_TIER_STOP_OUTCOME_COLUMNS. Auxiliary horizons (3c/8c/13c/60c) may still be
        withheld per _literal_empirical_horizon without broadening the match tier.

        Returns: list of snapshot dicts, plus a 'match_tier' key on each
        indicating which tier matched (1=tightest, 5=broadest).

        If return_trace is True, returns (rows, trace_dict) for verification only;
        default False preserves the original single-list return type.

        as_of_ts_utc: when set (e.g. replay), only rows with ts_utc < as_of_ts_utc are
        considered. Default None is identical to historical behavior (all history visible).
        Production callers do not pass this.
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_similar_setups")
        ticker = ticker_storage_key(ticker)
        # Issue 19 / production similarity: canonical 1m snapshot rows only — no 5m legacy pool mixing.
        if timeframe != CANONICAL_TIMEFRAME:
            log.warning(
                "get_similar_setups: timeframe=%r is not canonical %r — Issue 19 similarity is "
                "1m-only; returning empty similar set (legacy timeframes excluded by policy).",
                timeframe,
                CANONICAL_TIMEFRAME,
            )
            if return_trace:
                return [], {
                    "trace_schema": "similarity_trace_issue21_v1",
                    "rejected": True,
                    "reject_reason": "non_canonical_timeframe_for_issue19",
                    "requested_timeframe": timeframe,
                    "canonical_timeframe": CANONICAL_TIMEFRAME,
                    "ticker": ticker,
                    "zone": zone,
                    "vwap_side": vwap_side,
                    "final_similar_count": 0,
                    "tiers": [],
                }
            return []

        above_bucket = _dist_bucket(nearest_above_dist)
        below_bucket = _dist_bucket(nearest_below_dist)
        _asof_sql = "" if as_of_ts_utc is None else " AND ts_utc < ? "

        _query_ctx: Optional[dict] = None
        trace: Optional[dict] = None
        if return_trace:
            _query_ctx = query_context_for_similarity(
                ticker=ticker,
                timeframe=timeframe,
                zone=zone,
                vwap_side=vwap_side,
                nearest_above_dist=nearest_above_dist,
                nearest_below_dist=nearest_below_dist,
                n_similar=n_similar,
                as_of_ts_utc=as_of_ts_utc,
            )
            trace = {
                "trace_schema": "similarity_trace_issue21_v1",
                "ticker": ticker,
                "timeframe": timeframe,
                "zone": zone,
                "vwap_side": vwap_side,
                "nearest_above_dist": nearest_above_dist,
                "nearest_below_dist": nearest_below_dist,
                "query_context": _query_ctx,
                "MIN_SAMPLES_STATISTICAL": MIN_SAMPLES_STATISTICAL,
                "empirical_outcome_columns": list(SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS),
                "tier_stop_outcome_columns": list(SIMILARITY_TIER_STOP_OUTCOME_COLUMNS),
                "LIMIT": n_similar,
                "as_of_ts_utc": as_of_ts_utc,
                "note": (
                    "Session/regime are NOT SQL filters here; narrowing is tier 1–5 only. "
                    "All tiers require outcome_1c IS NOT NULL for SQL pool membership. "
                    "Tiers 1–4 stop when SIMILARITY_TIER_STOP_OUTCOME_COLUMNS (1c/5c/15c) "
                    f"each have ≥{MIN_SAMPLES_STATISTICAL} labeled rows."
                ),
                "tiers": [],
            }

        def _finish(rows_raw, tier_num: int, *, stop_reason: str):
            out = [dict(r) for r in rows_raw]
            if return_trace and trace is not None:
                trace["chosen_tier"] = tier_num
                trace["final_similar_count"] = len(out)
                trace["final_labeled_counts"] = similarity_labeled_counts(out)
                fc = trace["final_labeled_counts"]
                ftsv = similarity_tier_stop_viable(fc)
                fatv = similarity_empirically_viable(fc)
                trace["final_empirically_viable"] = ftsv
                trace["final_all_tracked_viable"] = fatv
                trace["final_selected_tier"] = tier_num
                trace["final_selected_row_count"] = len(out)
                trace["final_selected_labeled_counts"] = dict(fc)
                trace["final_tier_stop_viable"] = ftsv
                trace["stop_reason"] = stop_reason
                trace["withheld_horizons"] = withheld_horizons_report(fc)
                trace["tier_stop_weak_horizons"] = tier_stop_weak_horizons(fc)
                trace["weakest_tracked_horizons"] = weakest_tracked_horizons(fc)
                trace["widening_analysis"] = widening_summary_from_tiers(
                    trace.get("tiers", []), tier_num
                )
                return out, trace
            return out

        def _append_tier(
            tier_num: int,
            nrows: int,
            selected: bool,
            *,
            counts: Optional[dict[str, int]] = None,
            stop_reason: Optional[str] = None,
        ):
            if trace is not None and _query_ctx is not None:
                c = dict(counts or {})
                tsv = similarity_tier_stop_viable(c) if c else False
                atv = similarity_empirically_viable(c) if c else False
                entry: dict = {
                    "tier": tier_num,
                    "constraint_definition": structured_constraints_for_tier(tier_num, _query_ctx),
                    "relaxed_vs_previous_tier": relaxed_constraints_vs_previous_tier(tier_num),
                    "row_count_after_query_limit": nrows,
                    "selected": selected,
                    "labeled_counts": c,
                    "tier_stop_viable": tsv,
                    "empirically_viable": tsv,
                    "all_tracked_viable": atv,
                }
                if stop_reason:
                    entry["stop_reason"] = stop_reason
                trace["tiers"].append(entry)

        def _maybe_return_tier(rows_raw, tier_num: int):
            """Return this tier if it satisfies full empirical viability; else record trace and continue."""
            out_dicts = [dict(r) for r in rows_raw]
            counts = similarity_labeled_counts(out_dicts)
            viable = similarity_tier_stop_viable(counts)
            _append_tier(tier_num, len(rows_raw), viable, counts=counts)
            if viable:
                log.debug(
                    "get_similar_setups %s/%s zone=%s vwap_side=%s: tier %s ACCEPT "
                    "(n=%s labeled_counts=%s min=%s)",
                    ticker,
                    timeframe,
                    zone,
                    vwap_side,
                    tier_num,
                    len(out_dicts),
                    counts,
                    MIN_SAMPLES_STATISTICAL,
                )
                return _finish(rows_raw, tier_num, stop_reason="tier_stop_satisfied")
            log.debug(
                "get_similar_setups %s/%s: tier %s not empirically viable (n=%s counts=%s need %s each) — widening",
                ticker,
                timeframe,
                tier_num,
                len(out_dicts),
                counts,
                MIN_SAMPLES_STATISTICAL,
            )
            return None

        with self._connect() as conn:

            # ── Tier 1: zone + vwap_side + both distance buckets ──────────
            _p1 = (
                ticker, timeframe, zone, vwap_side,
                nearest_above_dist,
                _bucket_lo(above_bucket), _bucket_hi(above_bucket),
                nearest_below_dist,
                _bucket_lo(below_bucket), _bucket_hi(below_bucket),
            )
            if as_of_ts_utc is not None:
                _p1 = _p1 + (as_of_ts_utc, n_similar)
            else:
                _p1 = _p1 + (n_similar,)
            rows = conn.execute("""
                SELECT *, 1 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                  AND outcome_1c IS NOT NULL
                  AND (
                    (nearest_above_dist IS NULL AND ? IS NULL)
                    OR (nearest_above_dist BETWEEN ? AND ?)
                  )
                  AND (
                    (nearest_below_dist IS NULL AND ? IS NULL)
                    OR (nearest_below_dist BETWEEN ? AND ?)
                  )
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p1).fetchall()

            done = _maybe_return_tier(rows, 1)
            if done is not None:
                return done

            # ── Tier 2: zone + vwap_side + above distance only ────────────
            _p2 = (
                ticker, timeframe, zone, vwap_side,
                nearest_above_dist,
                _bucket_lo(above_bucket), _bucket_hi(above_bucket),
            )
            if as_of_ts_utc is not None:
                _p2 = _p2 + (as_of_ts_utc, n_similar)
            else:
                _p2 = _p2 + (n_similar,)
            rows = conn.execute("""
                SELECT *, 2 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                  AND outcome_1c IS NOT NULL
                  AND (
                    (nearest_above_dist IS NULL AND ? IS NULL)
                    OR (nearest_above_dist BETWEEN ? AND ?)
                  )
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p2).fetchall()

            done = _maybe_return_tier(rows, 2)
            if done is not None:
                return done

            # ── Tier 3: zone + vwap_side only ─────────────────────────────
            _p3 = (ticker, timeframe, zone, vwap_side)
            if as_of_ts_utc is not None:
                _p3 = _p3 + (as_of_ts_utc, n_similar)
            else:
                _p3 = _p3 + (n_similar,)
            rows = conn.execute("""
                SELECT *, 3 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                  AND outcome_1c IS NOT NULL
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p3).fetchall()

            done = _maybe_return_tier(rows, 3)
            if done is not None:
                return done

            # ── Tier 4: zone only ─────────────────────────────────────────
            _p4 = (ticker, timeframe, zone)
            if as_of_ts_utc is not None:
                _p4 = _p4 + (as_of_ts_utc, n_similar)
            else:
                _p4 = _p4 + (n_similar,)
            rows = conn.execute("""
                SELECT *, 4 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone = ?
                  AND outcome_1c IS NOT NULL
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p4).fetchall()

            done = _maybe_return_tier(rows, 4)
            if done is not None:
                return done

            # ── Tier 5: all filled snapshots for this ticker ──────────────
            _p5 = (ticker, timeframe)
            if as_of_ts_utc is not None:
                _p5 = _p5 + (as_of_ts_utc, n_similar)
            else:
                _p5 = _p5 + (n_similar,)
            rows = conn.execute("""
                SELECT *, 5 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ?
                  AND outcome_1c IS NOT NULL
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p5).fetchall()

            out5 = [dict(r) for r in rows]
            c5 = similarity_labeled_counts(out5)
            v5 = similarity_tier_stop_viable(c5)
            _append_tier(
                5,
                len(rows),
                True,
                counts=c5,
                stop_reason="max_tier_broadest_pool",
            )
            if trace is not None:
                trace["tier5_empirically_viable"] = v5
                trace["tier5_all_tracked_viable"] = similarity_empirically_viable(c5)
                if not v5:
                    trace["tier5_note"] = (
                        "Tier-stop columns (1c/5c/15c) may still be sparse; "
                        "or auxiliary horizons may be withheld per horizon where "
                        f"labeled count < {MIN_SAMPLES_STATISTICAL}."
                    )
            return _finish(rows, 5, stop_reason="max_tier_broadest_pool_forced")

    def count_snapshots(self, ticker: str, timeframe: str) -> dict:
        """Return snapshot counts for UI display.

        'filled' = has at least outcome_1c populated (usable for prediction).
        outcome_filled=1 means every column in OUTCOME_BAR_SPECS is populated
        (db backfill “complete” for that row). ML training uses per-horizon
        IS NOT NULL, not outcome_filled (Issue 14).
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.count_snapshots")
        ticker = ticker_storage_key(ticker)
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=?",
                (ticker, timeframe)
            ).fetchone()[0]
            filled = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND outcome_1c IS NOT NULL",
                (ticker, timeframe)
            ).fetchone()[0]
        return {"total": total, "filled": filled, "pending": total - filled}

    def get_avg_move(self, ticker: str, timeframe: str,
                      zone: str, vwap_side: str,
                      nearest_above_dist: Optional[float],
                      nearest_below_dist: Optional[float],
                      *,
                      as_of_ts_utc: Optional[float] = None) -> dict:
        """
        Return avg and median point move for similar setups.
        Used by 'What the Data Says' to show WHERE price typically goes,
        not just direction probability.

        as_of_ts_utc: when set, only rows with ts_utc < as_of_ts_utc (same contract as get_similar_setups).

        Non-canonical timeframes return empty stats (same policy as get_similar_setups / Issue 19).

        Returns:
          avg_1c_pts   : average move over next 1 candle (signed, +up/-down)
          avg_3c_pts   : average move over next 3 candles
          median_1c_pts: median move
          median_3c_pts: median
          n            : sample count used
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_avg_move")
        if timeframe != CANONICAL_TIMEFRAME:
            log.warning(
                "get_avg_move: timeframe=%r is not canonical %r — returning empty stats (Issue 19).",
                timeframe,
                CANONICAL_TIMEFRAME,
            )
            return {
                "avg_1c_pts": None,
                "avg_3c_pts": None,
                "median_1c_pts": None,
                "median_3c_pts": None,
                "n": 0,
                "reject_reason": "non_canonical_timeframe",
            }
        ticker = ticker_storage_key(ticker)
        above_bucket = _dist_bucket(nearest_above_dist)
        below_bucket = _dist_bucket(nearest_below_dist)
        _asof_sql = "" if as_of_ts_utc is None else " AND ts_utc < ? "

        with self._connect() as conn:
            _params = (
                ticker, timeframe, zone, vwap_side,
                nearest_above_dist,
                _bucket_lo(above_bucket), _bucket_hi(above_bucket),
                nearest_below_dist,
                _bucket_lo(below_bucket), _bucket_hi(below_bucket),
            )
            if as_of_ts_utc is not None:
                _params = _params + (as_of_ts_utc,)
            rows = conn.execute(f"""
                SELECT outcome_1c_pts, outcome_3c_pts
                FROM snapshots
                WHERE ticker = ?
                  AND timeframe = ?
                  AND zone = ?
                  AND vwap_side = ?
                  AND outcome_1c_pts IS NOT NULL
                  AND (
                    (nearest_above_dist IS NULL AND ? IS NULL)
                    OR (nearest_above_dist BETWEEN ? AND ?)
                  )
                  AND (
                    (nearest_below_dist IS NULL AND ? IS NULL)
                    OR (nearest_below_dist BETWEEN ? AND ?)
                  )
                  {_asof_sql}
                ORDER BY ts_utc DESC
                LIMIT 500
            """, _params).fetchall()

        if not rows:
            return {"avg_1c_pts": None, "avg_3c_pts": None,
                    "median_1c_pts": None, "median_3c_pts": None, "n": 0}

        pts1 = [r["outcome_1c_pts"] for r in rows if r["outcome_1c_pts"] is not None]
        pts3 = [r["outcome_3c_pts"] for r in rows if r["outcome_3c_pts"] is not None]

        def _avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else None

        def _median(lst):
            if not lst: return None
            s = sorted(lst)
            n = len(s)
            return round(s[n // 2] if n % 2 else (s[n//2 - 1] + s[n//2]) / 2, 2)

        return {
            "avg_1c_pts":    _avg(pts1),
            "avg_3c_pts":    _avg(pts3),
            "median_1c_pts": _median(pts1),
            "median_3c_pts": _median(pts3),
            "n":             len(pts1),
        }

    # ════════════════════════════════════════════════════════════════════════
    # LEVEL CROSS OPERATIONS
    # ════════════════════════════════════════════════════════════════════════

    def log_level_cross(self, event: LevelCrossEvent) -> int:
        """Log a level crossing event."""
        d = asdict(event)
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO level_crosses ({cols}) VALUES ({placeholders})"
        vals = list(d.values())
        tk = str(d.get("ticker", "") or "")

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return _do()

    def get_recent_crosses(self, ticker: str, n: int = 20) -> list:
        """Return most recent level crossing events."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM level_crosses
                WHERE ticker = ?
                ORDER BY ts_utc DESC
                LIMIT ?
            """, (ticker, n)).fetchall()
        return [dict(r) for r in rows]

    def count_level_tests(self, ticker: str, level_name: str,
                           level_value: float, lookback_hours: float = 6.5) -> dict:
        """
        Count how many times price has tested a level today.
        Used for: "third test of 685 ceiling — rejection likely"
        """
        since_ts = utc_ts() - (lookback_hours * 3600)
        tolerance = 0.50  # pts — within 0.50 of level counts as a test

        with self._connect() as conn:
            crosses = conn.execute("""
                SELECT direction, COUNT(*) as cnt
                FROM level_crosses
                WHERE ticker = ?
                  AND level_name = ?
                  AND ts_utc >= ?
                  AND ABS(level_value - ?) <= ?
                GROUP BY direction
            """, (ticker, level_name, since_ts, level_value, tolerance)).fetchall()

        result = {"up": 0, "down": 0, "total": 0}
        for row in crosses:
            result[row["direction"]] = row["cnt"]
            result["total"] += row["cnt"]
        return result

    # ════════════════════════════════════════════════════════════════════════
    # CONFLUENCE LOG OPERATIONS
    # ════════════════════════════════════════════════════════════════════════

    def log_confluence(self, conf: ConfluenceLog) -> int:
        """Log confluence state."""
        d = asdict(conf)
        # Serialize any dict/list fields to JSON
        for k in ("spy_state", "qqq_state", "iwm_state", "vix_state",
                   "spy_constituents", "iwm_sectors"):
            if isinstance(d.get(k), (dict, list)):
                d[k] = json.dumps(d[k])
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO confluence_log ({cols}) VALUES ({placeholders})"
        vals = list(d.values())
        pt = str(d.get("primary_ticker", "") or "")

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return _do()

    # ════════════════════════════════════════════════════════════════════════
    # MODEL ACCURACY
    # ════════════════════════════════════════════════════════════════════════

    def compute_accuracy(self, ticker: str, timeframe: str,
                          model_version: str = "statistical_v1") -> dict:
        """
        Compute prediction accuracy for a given model version.
        Compares pred_Nc_up/down/flat_prob to actual outcome_Nc.
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.compute_accuracy")
        results = {}
        for horizon in ("1c", "3c", "5c", "8c", "13c", "15c", "60c"):
            pred_col    = f"pred_{horizon}_up_prob"
            outcome_col = f"outcome_{horizon}"

            with self._connect() as conn:
                rows = conn.execute(f"""
                    SELECT {pred_col}, pred_{horizon}_down_prob,
                           pred_{horizon}_flat_prob, {outcome_col}
                    FROM snapshots
                    WHERE ticker = ?
                      AND timeframe = ?
                      AND pred_model_version = ?
                      AND {pred_col} IS NOT NULL
                      AND {outcome_col} IS NOT NULL
                """, (ticker, timeframe, model_version)).fetchall()

            if not rows:
                results[horizon] = {"total": 0, "accuracy": None}
                continue

            correct = 0
            for row in rows:
                # Predicted direction = argmax of up/down/flat probs
                probs = {
                    "up":   row[f"pred_{horizon}_up_prob"]   or 0,
                    "down": row[f"pred_{horizon}_down_prob"] or 0,
                    "flat": row[f"pred_{horizon}_flat_prob"] or 0,
                }
                predicted = max(probs, key=probs.get)
                actual    = row[outcome_col]
                if predicted == actual:
                    correct += 1

            total    = len(rows)
            accuracy = round(correct / total * 100, 1) if total > 0 else None
            results[horizon] = {"total": total, "correct": correct, "accuracy": accuracy}

        return results

    # ════════════════════════════════════════════════════════════════════════
    # SESSION TRACKING
    # ════════════════════════════════════════════════════════════════════════

    def start_session(self, ticker: str) -> int:
        tk = ticker

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO session_log (ticker) VALUES (?)", (tk,)
                )
                return int(cur.lastrowid)

        return _do()

    def end_session(self, session_id: int, snapshots: int, crosses: int):
        sid = session_id
        sn = snapshots
        cr = crosses

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE session_log
                    SET ended_at = datetime('now'),
                        snapshots_taken = ?,
                        crosses_logged = ?
                    WHERE session_id = ?
                    """,
                    (sn, cr, sid),
                )

        _do()

    def update_session_counts(self, session_id: int, snapshots: int, crosses: int):
        sid = session_id
        sn = snapshots
        cr = crosses

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE session_log
                    SET snapshots_taken = ?, crosses_logged = ?
                    WHERE session_id = ?
                    """,
                    (sn, cr, sid),
                )

        _do()

    # ════════════════════════════════════════════════════════════════════════
    # UTILITY
    # ════════════════════════════════════════════════════════════════════════

    def get_db_stats(self) -> dict:
        """Return database statistics for UI display.

        Primary snapshot metrics are **canonical 1m only** (``timeframe='1m'``) to avoid
        mixed-timeframe totals. Audit fields expose row counts across all timeframes.
        """
        with self._connect() as conn:
            snap_count = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE timeframe=?",
                (CANONICAL_TIMEFRAME,),
            ).fetchone()[0]
            by_tf_rows = conn.execute(
                "SELECT timeframe, COUNT(*) AS n FROM snapshots GROUP BY timeframe ORDER BY n DESC"
            ).fetchall()
            total_all_timeframes_audit = sum(int(r[1]) for r in by_tf_rows)
            cross_count = conn.execute("SELECT COUNT(*) FROM level_crosses").fetchone()[0]
            tickers = conn.execute(
                "SELECT DISTINCT ticker FROM snapshots WHERE timeframe=? ORDER BY ticker",
                (CANONICAL_TIMEFRAME,),
            ).fetchall()
            oldest = conn.execute(
                "SELECT MIN(ts_et) FROM snapshots WHERE timeframe=?",
                (CANONICAL_TIMEFRAME,),
            ).fetchone()[0]
            newest = conn.execute(
                "SELECT MAX(ts_et) FROM snapshots WHERE timeframe=?",
                (CANONICAL_TIMEFRAME,),
            ).fetchone()[0]
            filled = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE timeframe=? AND outcome_filled=1",
                (CANONICAL_TIMEFRAME,),
            ).fetchone()[0]

        return {
            "total_snapshots": snap_count,
            "total_snapshots_all_timeframes_audit": int(total_all_timeframes_audit),
            "snapshots_by_timeframe_audit": {r[0]: int(r[1]) for r in by_tf_rows},
            "filled_outcomes": filled,
            "level_crosses": cross_count,
            "tickers_tracked": [r[0] for r in tickers],
            "oldest_snapshot": oldest,
            "newest_snapshot": newest,
            "db_path": str(self.db_path),
            "db_size_mb": round(self.db_path.stat().st_size / 1e6, 2) if self.db_path.exists() else 0,
            "stats_scope": f"snapshot totals scoped to canonical timeframe={CANONICAL_TIMEFRAME!r}",
        }


# ════════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════════

# CENTRALIZED FUNCTIONS (imported from math_exposure at top of file):
#   _classify_direction_central  — percentage-based direction classification
#   _dist_bucket                 — distance bucketing for similar-setup matching
#   _bucket_lo / _bucket_hi     — bucket boundary helpers
#
# DO NOT redefine these here. If you need to change thresholds or logic,
# change them in math_exposure.py ONLY.

def _tf_seconds(timeframe: str) -> float:
    """Return seconds per candle for a given timeframe string."""
    mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    return mapping.get(timeframe, 300)

def _already_filled(conn: sqlite3.Connection, snap_id: int, col: str) -> bool:
    row = conn.execute(
        f"SELECT {col} FROM snapshots WHERE snapshot_id = ?", (snap_id,)
    ).fetchone()
    return row is not None and row[0] is not None


def _snapshot_rows_affected_by_bar_mutations(
    conn: sqlite3.Connection,
    tkr: str,
    changed_bar_starts: set[float],
    tz: float,
) -> list:
    """
    Snapshots whose BAR_ANCHOR_V1 outcomes depend on any bar whose bar_start_ts_utc
    is in changed_bar_starts (anchor bar or forward label bar for any governed horizon).
    """
    if not changed_bar_starts:
        return []
    bar_end_rows = conn.execute(
        """
        SELECT bar_end_ts_utc, close FROM price_bars_1m
        WHERE ticker = ? AND bar_end_ts_utc <= ?
        ORDER BY bar_end_ts_utc ASC
        """,
        (tkr, tz),
    ).fetchall()
    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
    out: list = []
    for row in conn.execute(
        """
        SELECT snapshot_id, ts_utc, atr FROM snapshots
        WHERE ticker = ? AND timeframe = ?
          AND COALESCE(horizon_outcome_schema_version, ?) = ?
          AND ts_utc < ?
        """,
        (
            tkr,
            CANONICAL_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            tz,
        ),
    ):
        t_snap = float(row["ts_utc"])
        anch_idx = bisect.bisect_right(bar_ends, t_snap) - 1
        if anch_idx < 0:
            continue
        anchor_bar_start = bar_ends[anch_idx] - 60.0
        if anchor_bar_start in changed_bar_starts:
            out.append(row)
            continue
        for _, _, n_min in OUTCOME_BAR_SPECS:
            if forward_bar_start_utc(t_snap, n_min) in changed_bar_starts:
                out.append(row)
                break
    return out


def _snapshot_row_atr(row) -> Optional[float]:
    try:
        v = row["atr"]
    except (KeyError, IndexError, TypeError):
        return None
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _apply_bar_based_outcome_updates(
    conn: sqlite3.Connection,
    *,
    tz: float,
    unfilled_rows,
    bar_ends: list[float],
    bar_end_closes: list[float],
    close_by_start: dict[float, float],
    force_refresh: bool = False,
) -> int:
    """
    Shared bar-anchor outcome write path (Issue 4). Used by live fill_outcomes
    (rolling snapshot window) and historical pin_neutral repair (explicit snapshot sets).

    When force_refresh=True, recomputes all governed horizon columns from current
    price_bars_1m (used after authoritative bar mutation so stored labels cannot drift).

    Also writes movement-target columns: outcome_dir_*, outcome_move_*, valid_dir_*,
    threshold_move_* (and duplicate outcome_move_thr_pts_* for backward compatibility).

    Returns count of UPDATE statements executed.
    """
    _outcome_cols = [s[0] for s in OUTCOME_BAR_SPECS]
    _mcfg = load_movement_thresholds_by_horizon_v1()
    n_exec = 0
    for row in unfilled_rows:
        snap_id = int(row["snapshot_id"])
        t_snap = float(row["ts_utc"])
        anch_idx = bisect.bisect_right(bar_ends, t_snap) - 1
        if anch_idx < 0:
            continue
        anchor_close = bar_end_closes[anch_idx]
        atr_v = _snapshot_row_atr(row)

        if force_refresh:
            updates: dict = {}
            for odir, opt, n_min in OUTCOME_BAR_SPECS:
                spec = next(s for s in OUTCOME_MOVEMENT_V1_SPECS if s[5] == n_min)
                dcol, mcol, vdcol, tmcol, legtcol, _nm, slug = spec
                b_start = forward_bar_start_utc(t_snap, n_min)
                if not bar_complete_by_utc(b_start, tz):
                    updates[odir] = None
                    updates[opt] = None
                    updates[dcol] = None
                    updates[mcol] = None
                    updates[vdcol] = None
                    updates[tmcol] = None
                    updates[legtcol] = None
                    continue
                fwd_close = close_by_start.get(float(b_start))
                if fwd_close is None:
                    updates[odir] = None
                    updates[opt] = None
                    updates[dcol] = None
                    updates[mcol] = None
                    updates[vdcol] = None
                    updates[tmcol] = None
                    updates[legtcol] = None
                    continue
                pts_move = fwd_close - anchor_close
                updates[odir] = _classify_direction_central(pts_move, anchor_close)
                updates[opt] = round(pts_move, 4)
                thr = threshold_move_pts_for_slug(
                    slug, anchor_close=anchor_close, atr=atr_v, cfg=_mcfg
                )
                dir_ok = not invalid_for_dir_target(slug, _mcfg)
                dlab, mlab, vdi = directional_and_move_labels_v2(
                    pts_move, thr, dir_allowed=dir_ok
                )
                updates[dcol] = dlab
                updates[mcol] = mlab
                updates[vdcol] = int(vdi)
                updates[tmcol] = round(thr, 8)
                updates[legtcol] = round(thr, 8)
            all_filled = all(updates.get(c) is not None for c in _outcome_cols)
            updates["outcome_filled"] = 1 if all_filled else 0
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE snapshots SET {set_clause} WHERE snapshot_id = ?",
                list(updates.values()) + [snap_id],
            )
            n_exec += 1
            continue

        updates = {}
        for odir, opt, n_min in OUTCOME_BAR_SPECS:
            spec = next(s for s in OUTCOME_MOVEMENT_V1_SPECS if s[5] == n_min)
            dcol, mcol, vdcol, tmcol, legtcol, _nm, slug = spec
            if _already_filled(conn, snap_id, odir):
                ex_v = conn.execute(
                    f"SELECT {vdcol} FROM snapshots WHERE snapshot_id = ?",
                    (snap_id,),
                ).fetchone()
                if ex_v is not None and ex_v[0] is not None:
                    continue
            b_start = forward_bar_start_utc(t_snap, n_min)
            if not bar_complete_by_utc(b_start, tz):
                continue
            fwd_close = close_by_start.get(float(b_start))
            if fwd_close is None:
                continue
            pts_move = fwd_close - anchor_close
            updates[odir] = _classify_direction_central(pts_move, anchor_close)
            updates[opt] = round(pts_move, 4)
            thr = threshold_move_pts_for_slug(
                slug, anchor_close=anchor_close, atr=atr_v, cfg=_mcfg
            )
            dir_ok = not invalid_for_dir_target(slug, _mcfg)
            dlab, mlab, vdi = directional_and_move_labels_v2(
                pts_move, thr, dir_allowed=dir_ok
            )
            updates[dcol] = dlab
            updates[mcol] = mlab
            updates[vdcol] = int(vdi)
            updates[tmcol] = round(thr, 8)
            updates[legtcol] = round(thr, 8)

        if not updates:
            continue

        existing = conn.execute(
            """
            SELECT outcome_1c, outcome_3c, outcome_5c,
                   outcome_8c, outcome_13c, outcome_15c, outcome_60c
            FROM snapshots WHERE snapshot_id = ?
            """,
            (snap_id,),
        ).fetchone()
        all_filled = all(updates.get(c) or existing[c] for c in _outcome_cols)
        if all_filled:
            updates["outcome_filled"] = 1

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE snapshots SET {set_clause} WHERE snapshot_id = ?",
            list(updates.values()) + [snap_id],
        )
        n_exec += 1
    return n_exec


def _refresh_governed_outcomes_after_bar_mutation(
    conn: sqlite3.Connection,
    *,
    tkr: str,
    changed_bar_starts: set[float],
    tz: float,
) -> int:
    """
    Recompute BAR_ANCHOR_V1 snapshot outcomes for rows affected by mutated 1m bars.
    Must run in the same SQLite transaction/connection as the bar upsert.
    """
    affected = _snapshot_rows_affected_by_bar_mutations(conn, tkr, changed_bar_starts, tz)
    if not affected:
        return 0
    _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
    _bar_start_upper = tz + float(_max_fwd_min) * 60.0 + 120.0
    min_snap_ts = min(float(r["ts_utc"]) for r in affected)
    bar_low = min_snap_ts - 5000.0

    close_by_start: dict[float, float] = {}
    for r in conn.execute(
        """
        SELECT bar_start_ts_utc, close FROM price_bars_1m
        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
        """,
        (tkr, bar_low, _bar_start_upper),
    ).fetchall():
        close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])

    bar_end_rows = conn.execute(
        """
        SELECT bar_end_ts_utc, close FROM price_bars_1m
        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
        ORDER BY bar_end_ts_utc ASC
        """,
        (tkr, bar_low, tz),
    ).fetchall()
    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
    bar_end_closes = [float(r["close"]) for r in bar_end_rows]

    return _apply_bar_based_outcome_updates(
        conn,
        tz=tz,
        unfilled_rows=affected,
        bar_ends=bar_ends,
        bar_end_closes=bar_end_closes,
        close_by_start=close_by_start,
        force_refresh=True,
    )


def market_session(et_hour: int, et_minute: int) -> str:
    """Classify current time as market session."""
    mins = et_hour * 60 + et_minute
    if mins < 570:    # before 9:30
        return "premarket"
    elif mins < 960:  # before 4:00pm
        return "rth"
    elif mins < 1200: # before 8:00pm
        return "afterhours"
    return "closed"

def build_ts_et(dt: Optional[datetime] = None) -> str:
    """Return formatted ET timestamp string."""
    dt = dt or now_et()
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")


# --- Dynamic snapshot SQL builders (strict BYPASS: only this file may embed FROM + snapshots) ---


def sql_flow_audit_count_where(base_where: str) -> str:
    return f"SELECT COUNT(*) FROM snapshots {base_where}"


def sql_flow_audit_rows_where(base_where: str) -> str:
    return (
        "SELECT snapshot_id, spot, flow_imbalance, option_chain_json\n        FROM snapshots\n        "
        + base_where.strip()
        + "\n    "
    )


def sql_select_snapshots_columns(cols_sql: str) -> str:
    return f"SELECT {cols_sql} FROM snapshots"


def sql_select_snapshots_ticker_tf_order(sel: str, *, order_suffix: str) -> str:
    return f"SELECT {sel} FROM snapshots WHERE ticker = ? AND timeframe = ? {order_suffix}"


def sql_overlay_count_zpred(zpred: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND outcome_1c IS NOT NULL"
    )


def sql_overlay_count_zpred_vwap(zpred: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND vwap_side = ? AND outcome_1c IS NOT NULL\n            "
    )


def sql_overlay_count_zpred_vwap_bucket(zpred: str, bsql: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND vwap_side = ? AND outcome_1c IS NOT NULL\n              AND ("
        + bsql
        + ")\n            "
    )


def sql_overlay_select_star_where(where_clause: str) -> str:
    return (
        "SELECT * FROM snapshots\n                WHERE "
        + where_clause
        + "\n                ORDER BY ts_utc DESC, snapshot_id DESC\n                LIMIT 1\n            "
    )


def sql_issue19_tier1_candidate_rows(asof_sql: str) -> str:
    return (
        "SELECT * FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?\n"
        "              AND outcome_1c IS NOT NULL\n"
        "              AND (\n"
        "                (nearest_above_dist IS NULL AND ? IS NULL)\n"
        "                OR (nearest_above_dist BETWEEN ? AND ?)\n"
        "              )\n"
        "              AND (\n"
        "                (nearest_below_dist IS NULL AND ? IS NULL)\n"
        "                OR (nearest_below_dist BETWEEN ? AND ?)\n"
        "              )\n            "
        + asof_sql
        + "\n            ORDER BY ts_utc DESC, snapshot_id DESC\n            LIMIT ?\n            "
    )


def sql_adaptive_broad_similarity_pool(asof_sql: str) -> str:
    return (
        "SELECT * FROM snapshots\n            WHERE ticker = ? AND timeframe = ?\n"
        "              AND outcome_1c IS NOT NULL\n            "
        + asof_sql
        + "\n            ORDER BY ts_utc DESC, snapshot_id DESC\n            LIMIT ?\n            "
    )


def sql_db_coverage_snap_tot() -> str:
    return "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=?"


def sql_db_coverage_col_nonnull(col: str) -> str:
    return f"SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND {col} IS NOT NULL"


def sql_db_coverage_col_labeled(col: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND "
        + col
        + " IN ('up','down','flat')"
    )


def sql_db_coverage_gap_lag() -> str:
    return (
        "SELECT COUNT(*) FROM (\n"
        "                      SELECT ts_utc,\n"
        "                        LAG(ts_utc) OVER (ORDER BY ts_utc) AS prev_ts\n"
        "                      FROM snapshots\n"
        "                      WHERE ticker=? AND timeframe=?\n"
        "                    ) x\n"
        "                    WHERE prev_ts IS NOT NULL AND (ts_utc - prev_ts) > 120\n"
        "                    "
    )


def sql_snapshots_training_fingerprint_select(aggs_csv: str) -> str:
    """Grouped aggregate over snapshots for training fingerprinting (caller supplies SELECT list)."""
    return (
        f"SELECT timeframe, {aggs_csv} FROM snapshots "
        "WHERE timeframe IN (?, ?) GROUP BY timeframe ORDER BY timeframe"
    )


_ISSUE19_CTX_GROUP_COLS = frozenset(
    {"session_bucket", "regime_primary", "vix_bucket", "market_session"}
)


def sql_issue19_snapshots_context_group(col: str) -> str:
    """Labeled-row distribution for Issue 19 context audit (whitelist columns only)."""
    if col not in _ISSUE19_CTX_GROUP_COLS:
        raise ValueError(f"unsupported context group column: {col!r}")
    return (
        f"SELECT COALESCE({col}, '(null)') AS k, COUNT(*) AS n FROM snapshots "
        "WHERE timeframe = ? AND outcome_1c IS NOT NULL "
        "GROUP BY k ORDER BY n DESC LIMIT 50"
    )


# ════════════════════════════════════════════════════════════════════════════════
# SNAPSHOT SQL REGISTRY (strict BYPASS closure v3)
# Static SQL strings for callers live under snapshot_sql/*.json (merged by get_snapshot_sql).
# Only this module may define loaders/builders that embed FROM + snapshots in Python source.
# ════════════════════════════════════════════════════════════════════════════════

_snapshot_sql_registry: Optional[dict[str, str]] = None


def get_snapshot_sql(key: str) -> str:
    """Return a registered snapshot SELECT/DELETE/COUNT SQL fragment by key."""
    global _snapshot_sql_registry
    if _snapshot_sql_registry is None:
        import json as _json

        d = Path(__file__).resolve().parent / "snapshot_sql"
        if not d.is_dir():
            raise FileNotFoundError(f"snapshot_sql/ directory missing next to db.py: {d}")
        merged: dict[str, str] = {}
        for p in sorted(d.glob("*.json")):
            merged.update(_json.loads(p.read_text(encoding="utf-8")))
        _snapshot_sql_registry = merged
    if key not in _snapshot_sql_registry:
        raise KeyError(f"Unknown snapshot SQL registry key: {key!r}")
    return _snapshot_sql_registry[key]


# ════════════════════════════════════════════════════════════════════════════════
# SINGLETON — one DB instance for the app (thread-safe)
# ════════════════════════════════════════════════════════════════════════════════

_db_instance: Optional[EdDB] = None
_db_lock: threading.Lock = threading.Lock()


def get_db() -> EdDB:
    """Get or create the singleton DB instance. Thread-safe."""
    global _db_instance
    if _db_instance is not None:
        return _db_instance
    with _db_lock:
        if _db_instance is None:
            _db_instance = EdDB()
    return _db_instance


# ════════════════════════════════════════════════════════════════════════════════
# QUICK SELF-TEST
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile, os
    logging.basicConfig(level=logging.INFO)

    # Use temp DB for test
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_db = EdDB(Path(tmpdir) / "test.db", allow_noncanonical=True)

        t_anchor = float((int(utc_ts()) // 60) * 60) - 70 * 60.0

        et_now = now_et()
        with test_db._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO snapshots (
                    ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                    horizon_outcome_schema_version, outcome_filled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "SPY",
                    CANONICAL_TIMEFRAME,
                    t_anchor,
                    build_ts_et(et_now),
                    et_now.hour,
                    et_now.minute,
                    market_session(et_now.hour, et_now.minute),
                    682.43,
                    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                ),
            )
            snap_id = cur.lastrowid
        print(f"OK Inserted snapshot_id={snap_id} (minimal row, bar-outcome smoke test)")

        bars = []
        for i in range(-20, 120):
            bs = t_anchor + i * 60.0
            c = 682.43 + i * 0.05
            bars.append(
                {"datetime": bs, "open": c - 0.02, "high": c + 0.02, "low": c - 0.02, "close": c, "volume": 1000.0}
            )
        test_db.upsert_1m_bars("SPY", bars)
        test_db.fill_outcomes("SPY", CANONICAL_TIMEFRAME, t_anchor + 8000.0)
        print("OK fill_outcomes (bar-based) ran")

        # Test level cross
        cross = LevelCrossEvent(
            ticker="SPY", ts_utc=utc_ts(), ts_et=build_ts_et(),
            level_name="Call Gamma Wall", level_value=685.0,
            direction="down", spot_at_cross=684.95,
            zone_before="breakout", zone_after="pin", timeframe=CANONICAL_TIMEFRAME
        )
        cross_id = test_db.log_level_cross(cross)
        print(f"OK Logged level cross cross_id={cross_id}")

        # Test counts
        counts = test_db.count_snapshots("SPY", CANONICAL_TIMEFRAME)
        print(f"OK Snapshot counts: {counts}")

        # Test stats
        stats = test_db.get_db_stats()
        print(f"OK DB stats: {stats['total_snapshots']} snapshots, {stats['db_size_mb']}MB")

        print("\nOK All tests passed -- db.py is ready")
