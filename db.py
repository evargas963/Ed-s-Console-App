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
from collections import deque
from pathlib import Path
from datetime import datetime

from db_authority import (
    classify_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)
from dataclasses import dataclass, asdict
from typing import Any, Callable, Optional, TypeVar

# ── Canonical timeframe (central config) ───────────────────────────────────
from timeframe_config import CANONICAL_TIMEFRAME
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
    classify_direction_pts as _classify_direction_per_horizon,
)

# Issue 19 / 21 — tier column tuples + audit helpers (single source: similarity_audit)

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

T = TypeVar("T")


def _dedup_preserve(items: list[str]) -> list[str]:
    """Order-preserving unique — used when canonicalizing enrollment reads can collapse a legacy
    bare-root alias (``SPX``) and its canonical form (``$SPX``) onto one identity (RC-345/F25)."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out

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
# RC-236: the distress bar separating routine absorbed waits (INFO) from real contention
# (WARNING). 2s ~ 5x the retry ladder's max sleep; attempt 4+ means the ladder is failing.
SQLITE_LOCK_WAIT_DISTRESS_MS = float(os.environ.get("ED_SQLITE_LOCK_WAIT_DISTRESS_MS", "2000"))
SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT = int(os.environ.get("ED_SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT", "4"))
SQLITE_WRITE_SLOW_MS = float(os.environ.get("ED_SQLITE_WRITE_SLOW_MS", "500"))
# Live bar-upsert incremental window: closed bars already persisted are immutable on the
# live path; only the in-progress bar plus this overlap is rewritten each cycle. Three
# minutes covers the in-flight bar and clock skew between the accumulator and the DB grid.
LIVE_BARS_REUPSERT_OVERLAP_SEC = 180.0

# Live fill_outcomes caps work per call (newest-first). MEASURED 2026-08-03: EXACT 5394
# unfilled SPY BAR_ANCHOR_V1 rows on ~26.7GB DB made unbounded scans hit ~23s WARNING.
# Backlog drains across successive bg submits; do not demote WARNING to hide the cost.
FILL_OUTCOMES_LIVE_BATCH_LIMIT = max(
    1, int(os.environ.get("ED_FILL_OUTCOMES_LIVE_BATCH", "250"))
)

# In-process tier-1 contention counters (audit/diagnostics; does not change retry policy).
_SQLITE_CONTENTION_METRICS_LOCK = threading.Lock()
_SQLITE_CONTENTION_RECENT_MAX = 500
_sqlite_contention_recent: deque[dict[str, Any]] = deque(maxlen=_SQLITE_CONTENTION_RECENT_MAX)
_sqlite_contention_totals: dict[str, Any] = {
    "sqlite_lock_wait_count": 0,
    "sqlite_lock_wait_total_ms": 0.0,
    "sqlite_lock_wait_max_ms": 0.0,
    "sqlite_busy_retry_count": 0,
    "sqlite_database_locked_count": 0,
    "sqlite_tier1_fail_count": 0,
    "operations": {},
    "tickers": {},
    "threads": {},
}


def record_sqlite_contention_event(
    *,
    kind: str,
    op: str,
    ticker: Optional[str],
    thread: str,
    wait_ms: float = 0.0,
    attempt: int = 0,
    db_path: str = "",
    error: str = "",
) -> None:
    """Record tier-1 SQLite contention for diagnostics (thread-safe, bounded ring)."""
    ts = float(_wall_time.time())
    row = {
        "kind": kind,
        "op": op,
        "ticker": ticker,
        "thread": thread,
        "wait_ms": round(float(wait_ms), 3),
        "attempt": int(attempt),
        "ts_utc": ts,
        "db_path": db_path,
        "error": (error or "")[:200],
    }
    with _SQLITE_CONTENTION_METRICS_LOCK:
        _sqlite_contention_recent.append(row)
        totals = _sqlite_contention_totals
        if kind == "lock_wait":
            totals["sqlite_lock_wait_count"] = int(totals["sqlite_lock_wait_count"]) + 1
            totals["sqlite_lock_wait_total_ms"] = float(totals["sqlite_lock_wait_total_ms"]) + float(
                wait_ms
            )
            totals["sqlite_lock_wait_max_ms"] = max(
                float(totals["sqlite_lock_wait_max_ms"]), float(wait_ms)
            )
        elif kind == "busy_retry":
            totals["sqlite_busy_retry_count"] = int(totals["sqlite_busy_retry_count"]) + 1
        elif kind in ("database_locked", "tier1_fail"):
            totals["sqlite_database_locked_count"] = int(
                totals["sqlite_database_locked_count"]
            ) + 1
            totals["sqlite_tier1_fail_count"] = int(totals["sqlite_tier1_fail_count"]) + 1
        for bucket, key in (("operations", op), ("tickers", ticker or ""), ("threads", thread)):
            if not key:
                continue
            sub = totals[bucket]
            sub[key] = int(sub.get(key, 0)) + 1




def _sqlite_busy_or_locked(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


#: RC-50 SQLite access tuning (read-side accelerants for the ~30 GB WAL DB).
#: mmap_size is a memory-mapped window over the DB file, backed by the shared OS page
#: cache (NOT per-connection heap), so a large value is cheap; 2 GiB covers the hot
#: index/recent-rows working set. cache_size is per-connection page cache — SQLite reads
#: a NEGATIVE value as KiB, so -131072 == 128 MiB (vs the ~2 MiB / -2000 default).
SQLITE_MMAP_SIZE_BYTES = 2 * 1024 ** 3   # 2 GiB
SQLITE_CACHE_SIZE_KIB = -131072          # 128 MiB (negative = KiB in SQLite's PRAGMA convention)


def configure_sqlite_connection(
    conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000
) -> None:
    """
    Production pragmas for any sqlite3 connection touching the console DB.
    Safe to call on every new connection (WAL is idempotent once enabled on the file).

    PRAGMA failures are rare (each pragma is well-formed) but possible if the DB file
    is locked by a separate WAL-mode-incompatible client or filesystem permissions
    block fsync. Log at debug so operators can spot pragmas silently degrading
    (e.g. journal_mode falls back to DELETE under read-only mounts) instead of
    inheriting whatever default the connection had.
    """
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        f"PRAGMA busy_timeout={int(busy_timeout_ms)}",
        "PRAGMA foreign_keys=ON",
        # RC-50 access tuning for a ~30 GB DB: the defaults (2 MB page cache, no
        # memory-mapping) re-fault every read from disk through a tiny per-connection
        # cache. mmap_size maps the hot working set (shared via the OS page cache — not
        # per-connection RAM), and a 128 MB page cache holds hot index/data pages across
        # a query. Both are read-side accelerants; neither changes durability (WAL +
        # synchronous=NORMAL unchanged). Measured: wide-row read 8.55 -> 6.59 ms; the
        # larger win is cold-start / concurrency, which the 2 MB default starved.
        f"PRAGMA mmap_size={SQLITE_MMAP_SIZE_BYTES}",
        f"PRAGMA cache_size={SQLITE_CACHE_SIZE_KIB}",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error as e:
            log.debug("configure_sqlite_connection: %s failed: %s", pragma, e)







# ── Database location (ONE APP, ONE MAIN, ONE DB) ───────────────────────────
# Default: data/ed_console.db, for every process and every worktree.
# RC-401 removed the per-agent fork that returned data/ed_console_claude.db under
# ED_AGENT_ROLE=claude — ambient process state was deciding which database the money
# path addressed, and it had already scattered rows into three sibling files.
# RC-534 removed ED_CONSOLE_DB / ED_DB_PATH from default production selection after an
# acknowledged override created an actively written worktree-local console authority.
# Recovery and tests pass explicit paths to EdDB; runtime placement belongs only to
# runtime_layout.



def _resolve_console_db_path() -> Path:
    from db_authority import default_console_db_path

    blocked = [name for name in ("ED_CONSOLE_DB", "ED_DB_PATH") if os.environ.get(name, "").strip()]
    if blocked:
        raise RuntimeError(
            "ambient console database overrides are disabled: "
            f"{', '.join(blocked)}. Configure ED_RUNTIME_ROOT for a dedicated runtime, "
            "or pass an explicit path to a recovery/test API."
        )
    return default_console_db_path()


DB_PATH = _resolve_console_db_path()



# ── ET timezone (DST-aware; see time_et.py) ───────────────────────────────────
from time_et import now_et  # noqa: E402  — re-export for legacy `from db import now_et`
from time_et import is_collect_window_bar_end_ts_utc  # noqa: E402  — RC-183 collect-window law
from time_et import (  # noqa: E402  — RC-345/F09: single RTH-boundary authority
    RTH_START_MINS as _RTH_START_MINS_AUTH,
    RTH_END_MINS as _RTH_END_MINS_AUTH,
)


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
    hours_to_expiry:    Optional[float] = None  # hours until session close on expiry date (early-close 13:00 ET)
    candle_open:        Optional[float] = None
    candle_high:        Optional[float] = None
    candle_low:         Optional[float] = None
    candle_close:       Optional[float] = None
    candle_volume:      Optional[float] = None
    candle_direction:   Optional[str] = None  # 'up', 'down', 'flat'
    candle_body_pts:    Optional[float] = None  # abs(close - open)
    candle_range_pts:   Optional[float] = None  # high - low
    spread:             Optional[float] = None   # bid-ask spread (pts)

    # ── execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY) ────
    # MODEL_DERIVED rows carry the immutable decision-cycle identity; quote-only
    # rows are explicitly NOT_APPLICABLE with NULL identity.  Linkage integrity
    # is trigger-enforced against model_execution_identities + the persistence
    # ledger (see execution_identity.py).
    decision_id:                Optional[str] = None
    execution_identity_sha256:  Optional[str] = None
    execution_identity_class:   Optional[str] = None  # 'MODEL_DERIVED' | 'NOT_APPLICABLE'

    # ── Raw Schwab quote primitives (CSV-first leaves; not derived) ────────────
    # quotes.{SYM}.bidPrice / askPrice / bidSize / askSize / lastSize / totalVolume.
    # Logged so ablation can judge the primitives that spread / vol_oi_ratio were
    # derived from (order-flow pressure: size imbalance, print size, volume rate).
    bid_price:          Optional[float] = None
    ask_price:          Optional[float] = None
    bid_size:           Optional[float] = None
    ask_size:           Optional[float] = None
    last_size:          Optional[float] = None
    total_volume:       Optional[float] = None

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
    # vix_bucket: produced by math_volatility.vix_bucket → 'vix_low' | 'vix_normal' | 'vix_elevated' | 'vix_high' | None.
    # COH-SA-VIX-TIER (commit 2c5cef5) consolidated the 15/20/30 cuts in math_volatility.vix_tier_token.
    vix_bucket:         Optional[str] = None
    put_call_oi_ratio:  Optional[float] = None
    oi_center:          Optional[float] = None
    gamma_pin:          Optional[float] = None  # terrain total-gamma after SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC (RC-429); earlier rows are selected-expiry net-GEX peak — do not mix eras. COLUMN name is historical (RC-292 renamed the live payload field absolute_gamma_strike; same quantity, no third era)

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
    goog_chg_pct:       Optional[float] = None  # RC-UI-3 (2026-09-12): GOOG is Alphabet's OWN
    # class-C share, a distinct instrument from GOOGL (class A) with its own confluence
    # weight in SPY_TOP/QQQ_TOP (market_context.py) -- it must not read GOOGL's column.
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
    iwm_weighted_push:  Optional[float] = None  # retired producer (index confluence, 2026-09-24): historical rows only

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
    pred_5c_up_prob:    Optional[float] = None
    pred_5c_down_prob:  Optional[float] = None
    pred_5c_flat_prob:  Optional[float] = None
    pred_15c_up_prob:   Optional[float] = None  # 15×1m forward — product 15m clock
    pred_15c_down_prob: Optional[float] = None
    pred_15c_flat_prob: Optional[float] = None
    pred_60c_up_prob:   Optional[float] = None  # 60×1m forward — product 60m clock
    pred_60c_down_prob: Optional[float] = None
    pred_60c_flat_prob: Optional[float] = None
    pred_model_version: Optional[str] = None  # 'statistical_v1', 'xgb_v1', etc.
    pred_model_source:  Optional[str] = None  # 'ml', 'rules', 'statistical'
    pred_override_source: Optional[str] = None  # override source if user overrode
    logger_source:      Optional[str] = None  # base_money_path | background_logger | ui_sse | ui_rest | manual_backfill
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

    # ── Price-action cone (operator 2026-06-11) — bar-derived primitives so the
    # ML stack can see price movement, not just options-structure distances.
    # Producer: features/signal_layer_v1.compute_price_action_snapshot_columns
    # (leakage-guarded: completed 1m bars with bar_end <= ts_utc only). ─────────
    pa_ret_1m_pct:          Optional[float] = None  # 1m log return ×100
    pa_ret_3m_pct:          Optional[float] = None
    pa_ret_5m_pct:          Optional[float] = None
    pa_ret_15m_pct:         Optional[float] = None
    pa_ret_30m_pct:         Optional[float] = None
    pa_ret_60m_pct:         Optional[float] = None
    pa_trend_slope_log20:   Optional[float] = None  # OLS slope of log close, 20 bars
    pa_trend_slope_log40:   Optional[float] = None
    pa_structure_state:     Optional[float] = None  # +1 HH/HL … -1 LH/LL
    pa_bos_up:              Optional[float] = None  # break of structure above swing high
    pa_bos_down:            Optional[float] = None
    pa_dist_swing_high_atr: Optional[float] = None  # ATR-scaled distance to swing high
    pa_dist_swing_low_atr:  Optional[float] = None
    pa_range_position_n20:  Optional[float] = None  # close position in 20-bar range 0..1
    pa_vwap_zscore:         Optional[float] = None
    pa_atr_pctile_60:       Optional[float] = None
    pa_atr_expansion_5_20:  Optional[float] = None
    pa_realized_vol_ann:    Optional[float] = None  # annualized 1m realized vol proxy
    pa_wick_asymmetry:      Optional[float] = None
    pa_close_location:      Optional[float] = None  # close position within last bar 0..1
    pa_impulse_run_signed:  Optional[float] = None  # ±consecutive close run length
    pa_mtf_trend_1m:        Optional[float] = None  # sign of 1m trend slope
    pa_mtf_trend_5m:        Optional[float] = None
    pa_mtf_bias_15m:        Optional[float] = None
    pa_mtf_alignment:       Optional[float] = None  # +1 aligned / -1 conflicted / 0 mixed
    pa_relative_volume:     Optional[float] = None
    pa_move_efficiency:     Optional[float] = None  # |body| vs 5-bar true-range sum

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
    mc_vol_source:          Optional[str]   = None  # VOLATILITY source: 'garch' or 'blend'
    mc_sigma_value:         Optional[float] = None  # ANNUALIZED decimal vol, post regime mult (path-independent)
    # DRIFT source: 'ml_conditioned' (unified-stack team authorized a directional prior) or
    # 'base_neutral' (MC ran with no prior; per_bar_drift == 0). REQUIRED durably: the persisted
    # xgb/lstm/transformer_available columns store layer `available`, while the team gate keys on
    # triplet COMPLETENESS — so a base-neutral row can carry three available layers and would
    # otherwise read as ML-conditioned. NULL on rows written before this column existed.
    mc_conditioning:        Optional[str]   = None

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
    flow_imbalance_source:  Optional[str] = None  # RC-345/F11: 'book'|'volume'|'none' economic identity
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
    outcome_5c:         Optional[str]   = None
    outcome_1c_pts:     Optional[float] = None  # actual point move
    outcome_5c_pts:     Optional[float] = None
    outcome_15c:        Optional[str]   = None  # 15×1m bars — true 15m label
    outcome_15c_pts:    Optional[float] = None
    outcome_60c:        Optional[str]   = None  # 60×1m bars — true 60m label
    outcome_60c_pts:    Optional[float] = None
    # Movement-target v1 labels (filled by fill_outcomes / refresh; NULL on fresh inserts)
    outcome_dir_1c:     Optional[str]   = None
    outcome_move_1c:    Optional[str]   = None
    outcome_move_thr_pts_1c: Optional[float] = None
    outcome_dir_5c:     Optional[str]   = None
    outcome_move_5c:    Optional[str]   = None
    outcome_move_thr_pts_5c: Optional[float] = None
    outcome_dir_15c:    Optional[str]   = None
    outcome_move_15c:   Optional[str]   = None
    outcome_move_thr_pts_15c: Optional[float] = None
    outcome_dir_60c:    Optional[str]   = None
    outcome_move_60c:   Optional[str]   = None
    outcome_move_thr_pts_60c: Optional[float] = None
    valid_dir_1c:       Optional[int]   = None
    threshold_move_1c:  Optional[float] = None
    valid_dir_5c:       Optional[int]   = None
    threshold_move_5c:  Optional[float] = None
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
    fused_move_prob_5c: Optional[float] = None
    fused_dir_up_prob_5c: Optional[float] = None
    fused_confidence_5c: Optional[float] = None
    fused_contributing_models_5c: Optional[str] = None
    fused_stack_status_5c: Optional[str] = None
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
                self._ensure_confluence_quote_table()
                self._ensure_normalized_table()
            finally:
                self._bootstrap_sql_guard_suppress = False
        log.info(f"EdDB initialized at {self.db_path}")

    def _connect(self, *, timeout_sec: float = 30.0) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=timeout_sec)
        conn.row_factory = sqlite3.Row
        configure_sqlite_connection(conn, busy_timeout_ms=int(timeout_sec * 1000))
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
            if lock_wait_ms > 0:
                record_sqlite_contention_event(
                    kind="lock_wait",
                    op=op,
                    ticker=ticker,
                    thread=thread_name,
                    wait_ms=lock_wait_ms,
                    attempt=attempt,
                    db_path=db_s,
                )
            if lock_wait_ms >= SQLITE_LOCK_WAIT_WARN_MS:
                # RC-236: severity calibrated like the SSE-duplicate precedent — a wait the
                # retry contract absorbs on an early attempt is NORMAL WAL contention under
                # 42 writers (SQLite busy_timeout doctrine) and logs INFO; WARNING is reserved
                # for genuine distress (a wait past the distress bar, or a deep retry), so the
                # quiet gate measures real defects instead of routine mid-RTH lock traffic.
                # Escalation retained: distress still WARNs and the contention telemetry event
                # above records EVERY wait regardless of severity.
                distress = (lock_wait_ms >= SQLITE_LOCK_WAIT_DISTRESS_MS
                            or attempt >= SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT)
                (log.warning if distress else log.info)(
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
                retryable = _sqlite_busy_or_locked(e)
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
                    record_sqlite_contention_event(
                        kind="database_locked" if retryable else "tier1_fail",
                        op=op,
                        ticker=ticker,
                        thread=thread_name,
                        wait_ms=total_wait_lock_ms,
                        attempt=attempt,
                        db_path=db_s,
                        error=str(e),
                    )
                    raise
                sleep_s = min(
                    SQLITE_BUSY_MAX_SLEEP_SEC,
                    SQLITE_BUSY_BASE_SLEEP_SEC * (2 ** (attempt - 1)),
                )
                record_sqlite_contention_event(
                    kind="busy_retry",
                    op=op,
                    ticker=ticker,
                    thread=thread_name,
                    wait_ms=total_wait_lock_ms,
                    attempt=attempt,
                    db_path=db_s,
                    error=str(e),
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
                goog_chg_pct        REAL,
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
                pred_5c_up_prob     REAL,
                pred_5c_down_prob   REAL,
                pred_5c_flat_prob   REAL,
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
                mc_conditioning          TEXT,

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
                flow_imbalance_source   TEXT,   -- RC-345/F11: book|volume|none economic identity
                smart_money_score       REAL,
                smart_money_direction   TEXT,
                iv_model_spread         REAL,

                -- Outcomes (NULL until filled)
                outcome_1c          TEXT,
                outcome_5c          TEXT,
                outcome_1c_pts      REAL,
                outcome_5c_pts      REAL,
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
            -- idx_snap_similarity_zone_vwap, idx_snap_similarity_zone_only, and
            -- idx_snap_avg_move_zone_vwap (get_similar_setups' and get_avg_move's own
            -- hot-path indexes -- see each index's own comment further down for why all
            -- three exist) are created further down, guarded, after the legacy-column
            -- ALTER TABLE migration -- NOT here. This executescript's own CREATE TABLE above
            -- already carries zone/vwap_side for a fresh DB, but a pre-existing snapshots
            -- table missing either column made this CREATE INDEX IF NOT EXISTS raise
            -- sqlite3.OperationalError: no such column: zone and abort _init_db entirely
            -- (caught live by test_migration_issue4_clears_v2_labels' minimal legacy
            -- fixture).

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

            -- ── RC-354: daily ATM-IV history (IV Rank / IV Percentile burn-in) ──
            -- One row per (ticker, ET date); the writer UPSERTs so the LAST write of the
            -- session wins — the banked value converges to the day's CLOSING ATM IV, the
            -- convention IVR/IVP are defined against. Source = the terrain sigma-band's
            -- own ATM-IV computation (one faucet, zero added vendor calls).
            CREATE TABLE IF NOT EXISTS iv_daily (
                ticker        TEXT NOT NULL,
                date_et       TEXT NOT NULL,
                atm_iv_pct    REAL NOT NULL,
                dte_used      INTEGER,
                method        TEXT,
                ts_utc        REAL NOT NULL,
                PRIMARY KEY (ticker, date_et)
            );

            -- ── RC-359: daily per-strike OI (ΔOI walls: fresh vs stale positioning) ──
            -- One row per (ticker, ET date, strike); last write of the session wins. The
            -- overnight diff vs the prior banked session is the ΔOI read — computable only
            -- once two sessions exist (honest burn-in, same doctrine as iv_daily).
            CREATE TABLE IF NOT EXISTS oi_daily (
                ticker   TEXT NOT NULL,
                date_et  TEXT NOT NULL,
                strike   REAL NOT NULL,
                call_oi  REAL,
                put_oi   REAL,
                ts_utc   REAL NOT NULL,
                PRIMARY KEY (ticker, date_et, strike)
            );

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

            -- ── Options/Gamma heatmap restart-durable snapshot (operator directive,
            -- 2026-09-15, canonical input-validity rules; DB ownership review, 2026-09-15,
            -- fourth pass) ── Per (ticker, strike, expiry) last-known-VALID gex/dex/vanna, so
            -- a genuine current-cycle vendor failure (invalid greeks, or a whole-surface OI
            -- outage) can display the latest valid timestamped snapshot instead of erasing the
            -- cell, and that snapshot survives a process restart. ALWAYS-LATEST, not a time
            -- series (INSERT OR REPLACE on this exact primary key) -- a display-durability
            -- checkpoint only ever needs the newest known-good value per cell, never a history.
            -- Not a duplicate of option_chain_accrual (RC-159): that table is a per-STRIKE
            -- aggregate collapsed across every expiry (a session gamma-ladder time series);
            -- this table is the per-CELL (strike × expiry) analogue the Options/Gamma heatmap
            -- grid actually needs, which nothing else in this schema persists at that
            -- granularity. Owned here (schema + read/write), not by server.py independently
            -- opening its own raw connections -- this IS the canonical database interface.
            CREATE TABLE IF NOT EXISTS gamma_surface_last_valid (
                ticker          TEXT NOT NULL,
                strike          REAL NOT NULL,
                expiry          TEXT NOT NULL,
                gex             REAL,
                dex             REAL,
                vanna           REAL,
                captured_ts_utc REAL NOT NULL,
                PRIMARY KEY (ticker, strike, expiry)
            );

            """)
        log.info("Schema initialized")

    #: Best-effort durability checkpoint (operator directive, 2026-09-15, LOCK DISCIPLINE):
    #: never a critical write, so a genuinely stuck DB should fail this fast and loudly rather
    #: than tie up a caller for the class's normal 30s connection timeout. Callers (server.py)
    #: must never hold their own lock across a call into either method below -- these open and
    #: close their own connection per call, exactly like every other "ordinary write" in this
    #: class (see the class docstring: tier-1 hot-path writes get _tier1_snapshot_write's
    #: retry/lock discipline; this is not that -- it is throttled to roughly once per 20s per
    #: ticker by the caller and degrades to in-memory-only-this-session on failure).
    GAMMA_LAST_VALID_DB_TIMEOUT_SEC = 3.0

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

    def _ensure_confluence_quote_table(self):
        """Thin quote ticks for panel_auto / cross-instrument symbols (not full snapshots)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS confluence_quote_ticks (
                    ticker      TEXT NOT NULL,
                    ts_utc      REAL NOT NULL,
                    ts_et       TEXT NOT NULL,
                    last_price  REAL,
                    chg_pct     REAL,
                    PRIMARY KEY (ticker, ts_utc)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_confluence_quote_ticks_ticker_ts "
                "ON confluence_quote_ticks (ticker, ts_utc DESC)"
            )


    def confluence_quote_tick_inventory(self) -> dict[str, int]:
        """Read-side inventory for panel_auto thin quotes (persistence consumer)."""
        self._ensure_confluence_quote_table()

        def _do() -> dict[str, int]:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM confluence_quote_ticks"
                ).fetchone()[0]
                tickers = conn.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM confluence_quote_ticks"
                ).fetchone()[0]
            return {"total_rows": int(total), "distinct_tickers": int(tickers)}

        return _do()


    def logging_universe_sync_panel_auto(self, panel_candidates: list[str], now_ts: float) -> dict[str, Any]:
        """
        Upsert ``panel_auto`` rows — cross-instrument panel symbols discovered from the
        market-context panel. The ``panel_auto`` CATEGORY records how a ticker was enrolled
        (auto, from the panel) — not how much data it gets: since 2026-08-25 (RC-482/RC-483,
        universal collection) panel_auto tickers take full option-chain snapshot rotation on
        the same terms as every other enrolled ticker (the roster loops in server.py include
        them). They also still feed the thin ``confluence_quote_ticks`` path via
        ``fetch_market_context``.

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
                    t = ticker_storage_key(raw)  # RC-345/F25: canonical enrollment write identity
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
            return _dedup_preserve([ticker_storage_key(r[0]) for r in rows])  # RC-345/F25: canonical read identity (legacy bare rows resolve on-read)


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
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — touch hits the $-canonical row via any alias
        nt = now_ts

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                    (nt, t),
                )

        _do()




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


    # Category protection priority — the SAME hierarchy the eviction/protection logic already uses.
    # Used as the deterministic collision-merge rule when a legacy alias row (e.g. "SPX") must fold
    # into its canonical form ("$SPX") that already exists.
    _LU_CATEGORY_PRIORITY = {"core": 0, "pinned": 1, "panel_auto": 2, "user_persisted": 3}



    def _migrate_schema(self):
        """Add columns that may be missing from older databases.
        Safe to call repeatedly — silently skips columns that already exist."""
        NEW_COLUMNS = [
            # (column_name, column_type)
            ("charm_magnitude",     "REAL"),
            ("session_bucket",      "TEXT"),
            ("vix_bucket",          "TEXT"),
            ("pred_15c_up_prob",    "REAL"),
            ("pred_15c_down_prob",  "REAL"),
            ("pred_15c_flat_prob",  "REAL"),
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
            ("flow_imbalance_source",   "TEXT"),   # RC-345/F11: economic book identity
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
            ("mc_conditioning",         "TEXT"),
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
            # ── Raw Schwab quote primitives (2026-06-10, operator: log leaves, not
            # only derivations — order-flow ablation candidates) ────────────────
            ("bid_price",                "REAL"),
            ("ask_price",                "REAL"),
            ("bid_size",                 "REAL"),
            ("ask_size",                 "REAL"),
            ("last_size",                "REAL"),
            ("total_volume",             "REAL"),
            # ── SnapshotRow fields absent from fresh-DB schema (FIND 2026-06-10):
            # insert_snapshot writes every dataclass field, so a fresh DB failed
            # with "no column named pred_model_source". Canonical DB only worked
            # because these columns were added historically outside this list. ──
            ("pred_model_source",        "TEXT"),
            ("pred_override_source",     "TEXT"),
            ("reward_risk",              "REAL"),
            ("reward_risk2",             "REAL"),
            # ── Price-action cone (operator 2026-06-11) — see SnapshotRow pa_* block.
            # Names must match features/signal_layer_v1.SNAPSHOT_PRICE_ACTION_COLUMNS.
            ("pa_ret_1m_pct",            "REAL"),
            ("pa_ret_3m_pct",            "REAL"),
            ("pa_ret_5m_pct",            "REAL"),
            ("pa_ret_15m_pct",           "REAL"),
            ("pa_ret_30m_pct",           "REAL"),
            ("pa_ret_60m_pct",           "REAL"),
            ("pa_trend_slope_log20",     "REAL"),
            ("pa_trend_slope_log40",     "REAL"),
            ("pa_structure_state",       "REAL"),
            ("pa_bos_up",                "REAL"),
            ("pa_bos_down",              "REAL"),
            ("pa_dist_swing_high_atr",   "REAL"),
            ("pa_dist_swing_low_atr",    "REAL"),
            ("pa_range_position_n20",    "REAL"),
            ("pa_vwap_zscore",           "REAL"),
            ("pa_atr_pctile_60",         "REAL"),
            ("pa_atr_expansion_5_20",    "REAL"),
            ("pa_realized_vol_ann",      "REAL"),
            ("pa_wick_asymmetry",        "REAL"),
            ("pa_close_location",        "REAL"),
            ("pa_impulse_run_signed",    "REAL"),
            ("pa_mtf_trend_1m",          "REAL"),
            ("pa_mtf_trend_5m",          "REAL"),
            ("pa_mtf_bias_15m",          "REAL"),
            ("pa_mtf_alignment",         "REAL"),
            ("pa_relative_volume",       "REAL"),
            ("pa_move_efficiency",       "REAL"),
        ]
        # Normalized training table must carry the same price-action columns or the
        # normalizer's column-intersection INSERT silently drops them (Issue 16 class).
        _PA_NEW_COLUMNS = [(c, t) for c, t in NEW_COLUMNS if c.startswith("pa_")]

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

        # RC spot/gamma-360-audit (2026-09-14): get_similar_setups' tiers 1-4 filter on
        # (ticker, timeframe, zone, vwap_side, outcome_1c IS NOT NULL), then ORDER BY
        # ts_utc DESC LIMIT n. idx_snap_ticker_tf_ts covers only (ticker, timeframe, ts_utc),
        # so SQLite must walk the WHOLE ticker+timeframe partition in ts_utc order, reading
        # every row's on-disk page (each row carries two large JSON blob columns -- reading
        # them off disk costs the same whether or not they end up SELECTed) until it finds
        # n_similar (500) matches on the far narrower zone+vwap_side+outcome_1c predicate.
        # MEASURED live (406,532-row snapshots table, 72,285 SPY/1m rows): a single real
        # get_similar_setups call took 11.1-13.8s -- run from 3-4 background threads on every
        # analytics cycle, this is the dominant, proven source of the "app is slow" and "spot
        # has latency" symptoms reported live during RTH (py-spy caught these threads parked
        # here at the exact moments ordinary quote reads stalled 1-7s).
        # Partial (WHERE outcome_1c IS NOT NULL, mirroring idx_snap_outcome_unfilled's own
        # precedent) so the ~half of rows that can never qualify are never indexed at all, and
        # ts_utc last so tier queries' ORDER BY ts_utc DESC LIMIT n is satisfied directly from
        # the index without a separate sort step. Guarded (not in the executescript above):
        # runs after the ALTER TABLE column-patch loop just above, so a legacy/minimal
        # snapshots table genuinely missing zone or vwap_side skips the index instead of
        # aborting _init_db (see the executescript's own note at this index's old location).
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_snap_similarity_zone_vwap "
                    "ON snapshots(ticker, timeframe, zone, vwap_side, ts_utc) "
                    "WHERE outcome_1c IS NOT NULL"
                )
        except sqlite3.OperationalError:
            pass  # zone/vwap_side not present on this schema

        # RC-REHAB-1 (2026-09-22): idx_snap_similarity_zone_vwap (above) covers get_similar_setups'
        # tiers 1-3 (zone AND vwap_side both fixed) but not tier 4 (zone only, vwap_side dropped --
        # "zone + vwap_side (drop all distance criteria)" -> "zone only (drop vwap_side)" in that
        # function's own tier docstring). MEASURED live: EXPLAIN QUERY PLAN showed SQLite choosing
        # idx_snap_ticker_tf_ts (ticker, timeframe, ts_utc) for the tier-4 query instead -- it
        # satisfies ORDER BY ts_utc DESC directly with no extra sort, but has no index support for
        # zone at all, so it has to scan every ticker+timeframe row (in ts_utc order) filtering zone
        # row-by-row until it finds n_similar matches or exhausts the partition. On SPY specifically
        # (76,957 total 1m rows / 39,812 with outcome_1c IS NOT NULL, by far the largest of any
        # tracked ticker) a single tier-4 probe measured 1,227ms for this reason alone -- reached on
        # essentially every call, since tiers 1-3's much narrower zone+vwap_side+distance match is
        # rare. Confirmed live with a matching index present: the identical query dropped to 31.6ms
        # (a real zone value ran in 2.15ms) -- SQLite correctly switches to a SEARCH using this index
        # (ticker=? AND timeframe=? AND zone=?), satisfying both the filter and the ORDER BY from the
        # index's own trailing ts_utc column, eliminating the scan-until-give-up entirely. Tier 4 is
        # a REJECTED-or-selected probe like every other tier -- this changes only how fast SQLite
        # finds the SAME rows tier 4's query has always asked for, never which rows.
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_snap_similarity_zone_only "
                    "ON snapshots(ticker, timeframe, zone, ts_utc) "
                    "WHERE outcome_1c IS NOT NULL"
                )
        except sqlite3.OperationalError:
            pass  # zone not present on this schema

        # RC-REHAB-1 (2026-09-22, same live-RTH trace as the two indexes above):
        # get_avg_move ("What the Data Says" avg/median point move) runs its own zone+
        # vwap_side query on the SAME hot path as get_similar_setups (compute_prediction_core
        # calls both back to back), but filters WHERE outcome_1c_pts IS NOT NULL -- a
        # DIFFERENT column from idx_snap_similarity_zone_vwap's own partial-index predicate
        # (outcome_1c IS NOT NULL). SQLite cannot prove one column's null-ness from the
        # other's (even though they are in practice always set together), so that index is
        # unusable for this query no matter how well it otherwise matches -- confirmed live:
        # EXPLAIN QUERY PLAN showed the same idx_snap_ticker_tf_ts scan-until-exhausted
        # fallback as the tier-4 defect above. MEASURED: 2,332ms for a single call matching
        # zero rows; 107ms with a matching index. A new index (not reusing/widening the
        # existing one) is the safe fix here -- changing the query's own filter column to
        # match the existing index would be a real behavioral bet on a column-equivalence
        # assumption never verified end-to-end; a dedicated index carries no such risk.
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_snap_avg_move_zone_vwap "
                    "ON snapshots(ticker, timeframe, zone, vwap_side, ts_utc) "
                    "WHERE outcome_1c_pts IS NOT NULL"
                )
        except sqlite3.OperationalError:
            pass  # zone/vwap_side not present on this schema

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
                # RC-6 (reopened 2026-07-28): option_chain_json and replay_context_json are
                # DELIBERATELY ABSENT from this list. They are the normalized table's SECOND
                # copy of multi-MB blobs the cull ledger retired — yet this migrate re-ADDed
                # them on every boot where they were missing, and the normalizer's
                # column-intersection INSERT refilled them (measured regrowth: 1,097 rows /
                # 187,193,762 bytes). The intersection DROPS absent columns silently by
                # design, so their absence is safe; the raw `snapshots` table keeps the one
                # authoritative copy. Re-introducing them here requires the supervised
                # migration (operator, due 2026-08-09) — never a silent boot-time ADD.
                # Raw Schwab quote primitives — must exist here too or the
                # normalizer's column-intersection INSERT silently drops them.
                ("bid_price", "REAL"),
                ("ask_price", "REAL"),
                ("bid_size", "REAL"),
                ("ask_size", "REAL"),
                ("last_size", "REAL"),
                ("total_volume", "REAL"),
            ):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        for col_name, col_type in _PA_NEW_COLUMNS:
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE snapshots_1m_normalized ADD COLUMN {col_name} {col_type}"
                    )
                log.info("DB migration: added %s to snapshots_1m_normalized", col_name)
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

        for col_name, col_type in (("logger_source", "TEXT"),):
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        # Independent-review finding (2026-09-12), REPRODUCED: market_context.py's
        # SYMBOL_TO_SNAPSHOT_CHG_COL aliased GOOG onto this same googl_chg_pct column
        # (there was no goog_chg_pct to point to), so every confluence recompute silently
        # substituted GOOGL's change for GOOG's own -- double-counting GOOGL's move at both
        # symbols' weights in SPY_TOP/QQQ_TOP and dropping GOOG's real, independently
        # diverging price action entirely. GOOG is Alphabet's class-C share, a distinct
        # instrument from GOOGL (class A); it gets its own column, same as every other
        # constituent.
        for col_name, col_type in (("goog_chg_pct", "REAL"),):
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
        self._migrate_drop_session_log_v1()
        self._migrate_drop_confluence_log_v1()
        self._migrate_drop_news_events_v1()

        # execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1):
        # additive — identity tables + (decision_id, execution_identity_sha256,
        # execution_identity_class) columns + linkage triggers.  Legacy rows keep
        # NULL identity forever (no backfill of any kind).
        # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the dependent tables MUST
        # exist BEFORE the identity schema runs, or a FRESH database gets no
        # linkage triggers on the decision-record and calibration decision-log
        # tables and identity-less governed rows can land ungoverned (caught by
        # the 2026-07-13 noncanonical runtime proof: 2 decision rows persisted
        # with a decision_id and no identity on a fresh proof DB). Existence is
        # checked read-only first so an already-migrated database never starts
        # a write transaction here (a held BEGIN IMMEDIATE elsewhere must keep
        # aborting preflights gracefully, not leak a locked error from init).
        try:
            from calibration.schema import CALIBRATION_DECISION_LOG_TABLE
            from execution_identity import ensure_execution_identity_schema

            with self._connect() as conn:
                existing = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "production_decision_records" not in existing:
                    from decision_record import ensure_production_decision_schema

                    ensure_production_decision_schema(conn)
                if CALIBRATION_DECISION_LOG_TABLE not in existing:
                    from calibration.schema import ensure_calibration_schema

                    ensure_calibration_schema(conn)
                ensure_execution_identity_schema(conn)
        except sqlite3.OperationalError as exc:
            log.error("execution identity schema migration failed: %s", exc)
            raise

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
            _null_outcomes = ", ".join(
                f"{odir} = NULL, {opt} = NULL"
                for odir, opt, _n in OUTCOME_BAR_SPECS
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    {_null_outcomes},
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
            _null_outcomes = ", ".join(
                f"{odir} = NULL, {opt} = NULL"
                for odir, opt, _n in OUTCOME_BAR_SPECS
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    {_null_outcomes},
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

    def _migrate_drop_session_log_v1(self) -> None:
        """Pass 6 — drop the session_log table.

        session_log was scaffolded with start_session / end_session /
        update_session_counts writers but zero production callers (one of the
        4 originally-known dormants). verification/daily_health.py already
        covers richer per-ticker session telemetry, so the table delivers
        no incremental value. Drop is idempotent (IF EXISTS).
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP TABLE IF EXISTS session_log")
            except sqlite3.OperationalError as exc:
                log.warning("drop session_log failed: %s", exc)

    def _migrate_drop_news_events_v1(self) -> None:
        """Pass 8 — drop the news_events table.

        news_events was scaffolded with insert_news_event writer and a single
        guarded call site in news_sentiment.py:refresh_and_context, but zero
        production readers. Operator-authorized drop 2026-05-26 after Cursor
        identified it as the only remaining table-level dormancy with a live
        writer post-Pass 7. News headlines reach the operator UI via
        ms.news_context (live aggregator), persistence added no value.
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP INDEX IF EXISTS idx_news_ticker_ts")
                conn.execute("DROP INDEX IF EXISTS idx_news_impact_ts")
                conn.execute("DROP TABLE IF EXISTS news_events")
            except sqlite3.OperationalError as exc:
                log.warning("drop news_events failed: %s", exc)

    def _migrate_drop_confluence_log_v1(self) -> None:
        """Pass 7 — drop the confluence_log table.

        confluence_log was scaffolded with log_confluence writer + ConfluenceLog
        dataclass but zero production callers / zero readers. Cross-instrument
        confluence state (spy_state / qqq_state / iwm_state / vix_state) is
        already computed live per refresh in market_state and surfaced through
        ms_dict for /api/state consumers; persisting it added no incremental
        value because no analyzer ever read confluence_log rows back. Drop is
        idempotent (IF EXISTS).
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP TABLE IF EXISTS confluence_log")
            except sqlite3.OperationalError as exc:
                log.warning("drop confluence_log failed: %s", exc)

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

        # RC-REHAB-3 (2026-09-23): option_chain_json/replay_context_json (19.46 GB
        # combined, measured) are DELIBERATELY NOT compressed here. Investigated and
        # deferred: 20+ files read these two columns (live_vs_replay_validation.py,
        # realized_contract_eval.py, replay_bundle_coverage.py, a dozen tools/liquidity_*
        # research scripts, tools/measure_post_fix_theta_v1.py, and more), several using a
        # SQL-level `length(option_chain_json) > REPLAY_BUNDLE_MIN_JSON_LENGTH` (==10)
        # sanity filter to distinguish real content from a trivial/near-empty value.
        # MEASURED: gzip's own fixed per-blob overhead is 22-24 bytes even for the most
        # trivial content ("[]", "{}", "null") -- exceeding that threshold on its own, so
        # compressing this column would silently turn that filter into a permanent no-op
        # across every consumer that uses it, not a crash. That is a correctness
        # regression, not just a storage question, and needs its own dedicated pass
        # (auditing every LENGTH()-based filter's threshold, not just wiring the codec)
        # rather than being rushed through alongside the other tables.

        # execution_identity_v1 fail-closed coherence: a MODEL_DERIVED row must
        # carry its identity pair; a NOT_APPLICABLE (quote-only) row must not.
        # When identity fields arrive without a class, the row IS model-derived.
        # (Trigger-level linkage against the identity table + ledger enforces
        # registration and same-identity-per-decision below the Python layer.)
        # Schwab CSV authority checked: yes
        # CSV row(s): NO_SCHWAB_EQUIVALENT — execution-identity provenance
        #   linkage only; no market field read, derived, or emitted here.
        # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (n/a — no
        #   derivation in this block).
        # All consumers checked: yes — identity columns are additive; every
        #   existing snapshot reader ignores unknown columns by name.
        # SCHWAB_CSV_CHECKED
        _xid_class = d.get("execution_identity_class")
        _xid = d.get("execution_identity_sha256")
        _did = d.get("decision_id")
        if _xid_class or _xid or _did:
            from execution_identity import require_identity_for_model_derived_write

            d["execution_identity_class"] = require_identity_for_model_derived_write(
                is_model_derived=(_xid_class != "NOT_APPLICABLE"),
                decision_id=_did,
                execution_identity_sha256=_xid,
                surface="snapshots",
            )

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

    def upsert_1m_bars(
        self,
        ticker: str,
        bars: list,
        *,
        refresh_governed_outcomes: bool = True,
    ) -> int:
        """
        Authoritative canonical 1m series for horizon labels (Schwab price history + server accumulator).
        Completed bars only; bar_start_ts_utc matches Candle.ts (epoch seconds, bar open).

        Ticker key uses ticker_storage_key (Issue 19): e.g. SPX -> $SPX for parity with snapshots
        and pin_neutral / fill_outcomes joins; $SPX unchanged.

        By default, after each successful upsert, governed BAR_ANCHOR_V1 snapshot outcomes that
        depend on any mutated bar_start are recomputed in the same connection so stored labels
        cannot drift. Historical bulk backfills may pass ``refresh_governed_outcomes=False`` and
        run ``refresh_all_governed_bar_anchor_outcomes_v1`` once after the batch.

        Returns count of rows written (after timestamp/OHLC validation), 0 if none.
        """
        tkr = ticker_storage_key(ticker)
        if not tkr or not bars:
            return 0
        rows = []
        def _volume_or_none(raw):
            if raw is None:
                return None
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return None
            return v if v >= 0 else None

        for b in bars:
            src = AUTHORITATIVE_1M_SOURCE
            if hasattr(b, "ts"):
                ts = float(b.ts)
                o, h, lo, c = float(b.open), float(b.high), float(b.low), float(b.close)
                vol = _volume_or_none(getattr(b, "volume", None))
            elif isinstance(b, dict):
                raw_ts = b.get("datetime", b.get("ts", b.get("timestamp", b.get("_ts", 0))))
                try:
                    ts = float(raw_ts)
                except (TypeError, ValueError):
                    continue
                try:
                    o = float(b["open"])
                    h = float(b["high"])
                    lo = float(b["low"])
                    c = float(b["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                vol = _volume_or_none(b.get("volume"))
                if b.get("source"):
                    src = str(b["source"])
            else:
                continue
            # Unit normalization for BOTH input shapes (Candle objects and dicts): Schwab wire
            # times are epoch ms; the canonical bar grid is epoch seconds. 2026-06-09 regression:
            # Candle.ts arrived in ms via the object path (which previously skipped this), writing
            # ms-grid rows that the outcome filler could never match.
            # Canonical 60s UTC grid: snap bar open to whole-minute epoch seconds (Schwab / adapters
            # may emit sub-second noise). Large drift (>30s from nearest minute) is rejected.
            raw_ts = float(ts)
            if raw_ts > 1e10:
                raw_ts = raw_ts / 1000.0
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
            # RC-183 collect-window law (operator, non-negotiable): price_bars_1m persists ET
            # bar-END minutes (555, min(975, cash_close+15)] on trading days only. This is the
            # ONE write seam for the table; every producer inherits the gate here.
            if not is_collect_window_bar_end_ts_utc(bar_end):
                continue
            rows.append((tkr, bar_start, bar_end, o, h, lo, c, vol, src))
        if not rows:
            return 0
        rows_tuple = list(rows)

        def _do() -> int:
            with self._connect() as conn:
                write_rows = rows_tuple
                if refresh_governed_outcomes:
                    # LIVE-path incremental write (2026-07-03 console usability): the in-memory
                    # accumulator re-seeds days of Schwab pricehistory, and rewriting the whole
                    # list every cycle held the tier-1 write lock for seconds (17.8s first-cycle
                    # exec observed live; ~0.6s every cycle after) and recomputed governed
                    # outcomes for EVERY bar. A bar is written only when it is MISSING from the
                    # DB, its values CHANGED (mutation → governed-outcome refresh contract), or
                    # it sits in the recent overlap window (in-progress bar). Identical
                    # re-upserts of persisted history are no-ops. One narrow index-range read
                    # replaces thousands of redundant writes. Bulk backfills pass
                    # refresh_governed_outcomes=False and keep the unconditional full write.
                    lo = min(float(t[1]) for t in rows_tuple)
                    hi = max(float(t[1]) for t in rows_tuple)
                    existing: dict[float, tuple] = {
                        float(er[0]): (
                            float(er[1]), float(er[2]), float(er[3]), float(er[4]),
                            None if er[5] is None else float(er[5]),
                        )
                        for er in conn.execute(
                            "SELECT bar_start_ts_utc, open, high, low, close, volume "
                            "FROM price_bars_1m WHERE ticker = ? "
                            "AND bar_start_ts_utc BETWEEN ? AND ?",
                            (tkr, lo, hi),
                        ).fetchall()
                    }
                    r = conn.execute(
                        "SELECT MAX(bar_start_ts_utc) FROM price_bars_1m WHERE ticker = ?",
                        (tkr,),
                    ).fetchone()
                    db_max = float(r[0]) if r is not None and r[0] is not None else None
                    if db_max is not None:
                        cutoff = db_max - LIVE_BARS_REUPSERT_OVERLAP_SEC

                        def _needs_write(t: tuple) -> bool:
                            bs = float(t[1])
                            if bs >= cutoff:
                                return True
                            prev = existing.get(bs)
                            if prev is None:
                                return True  # mid-history hole — repair it
                            # (open, high, low, close, volume) — REAL round-trips exactly.
                            return prev != (t[3], t[4], t[5], t[6], t[7])

                        write_rows = [t for t in rows_tuple if _needs_write(t)]
                if not write_rows:
                    return 0
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
                    write_rows,
                )
                n_written = len(write_rows)
                if refresh_governed_outcomes and write_rows:
                    # RC-166/RC-243: the refresh is DEFERRED to after the tier-1 lock is
                    # released — see the post-unlock block below. Only the bar starts travel
                    # out of the critical section.
                    _pending_refresh["starts"] = {float(r[1]) for r in write_rows}
                return n_written

        # RC-166 (root reached 2026-08-04, RC-243): the governed-outcome recompute used to run
        # INSIDE _do(), i.e. while _TIER1_SNAPSHOT_WRITE_LOCK was held, so every bar upsert held
        # the one global write lock for the whole recompute. On a 27 GB file that is precisely
        # the 38–180 s holds measured on the live console, and it is why adding bar workers made
        # the console slower rather than faster: they queue behind one another's refreshes.
        # tests/test_db_perf_rc166_v1.py has asserted this contract ("outcome refresh must not
        # hold the tier-1 lock") since 2026-07-31 and had been RED — the fix was specified and
        # never landed. Bars commit under the lock; labels are recomputed after release on a
        # separate connection, so a concurrent writer can proceed between the two.
        _pending_refresh: dict[str, set[float]] = {}

        def _post_unlock_refresh() -> None:
            """post-unlock governed outcome refresh — runs with tier-1 RELEASED."""
            starts = _pending_refresh.get("starts")
            if not starts:
                return
            with self._connect() as refresh_conn:
                _refresh_governed_outcomes_after_bar_mutation(
                    refresh_conn,
                    tkr=tkr,
                    changed_bar_starts=starts,
                    tz=float(_wall_time.time()),
                )

        n_written_total = self._tier1_snapshot_write("upsert_1m_bars", tkr, _do)
        _post_unlock_refresh()
        return n_written_total

    def fill_outcomes(self, ticker: str, timeframe: str, ts_utc_now: float) -> None:
        """
        Universal bar-based horizon outcomes (Issue 3 forward + Issue 4 anchor).

        For each snapshot at time T (ts_utc):
          anchor_close = close of the last price_bars_1m row with bar_end_ts_utc <= T
          forward_close = close of the bar with bar_start_ts_utc = floor((T+N*60)/60)*60
          outcome_Nc = classify_direction_pts(forward_close - anchor_close,
                                              threshold_move_pts_for_slug(slug, anchor_close, atr))
          (per-horizon ATR-scaled threshold — same scale as the v2 move gate, so
           outcome_Nc is balanced on each horizon's own volatility, not a fixed 0.05% cut)

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

                # Prefetch outcome/valid_dir cols so _apply skips N+1 per-horizon SELECTs.
                _odir_cols = ", ".join(s[0] for s in OUTCOME_BAR_SPECS)
                _vd_cols = ", ".join(s[2] for s in OUTCOME_MOVEMENT_V1_SPECS)
                unfilled = conn.execute(
                    f"""
                    SELECT snapshot_id, ts_utc, atr, {_odir_cols}, {_vd_cols}
                    FROM snapshots
                    WHERE ticker = ? AND timeframe = ?
                      AND outcome_filled = 0
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                      AND ts_utc < ? AND ts_utc > ?
                    ORDER BY ts_utc DESC
                    LIMIT ?
                    """,
                    (
                        tkr,
                        tf,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        tz,
                        min_snap_ts,
                        int(FILL_OUTCOMES_LIVE_BATCH_LIMIT),
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
        # Honest SLA: 5s+/10s+ remain WARNING (quiet-window FAIL). Perf fix is the
        # live batch + N+1 cut above — do not demote severity to greenwash 23s runs.
        _level, _tier = _fill_outcomes_latency_log(_exec_ms)
        if _level is logging.WARNING:
            log.warning(
                "sqlite_bg_write_slow op=fill_outcomes tier=%s ticker=%s exec_ms=%.1f "
                "thread=%s db_path=%s",
                _tier,
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )
        elif _level is logging.INFO:
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
        str(d.get("ticker", "") or "")

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return _do()

    def bank_daily_atm_iv(self, ticker: str, date_et: str, atm_iv_pct: float,
                          dte_used: int | None, method: str | None,
                          ts_utc: float) -> None:
        """RC-354: UPSERT the day's ATM IV — last write of the session wins, so the
        banked value converges to the CLOSING ATM IV (the convention IV Rank/Percentile
        are defined against). One row per (ticker, ET date); idempotent."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO iv_daily (ticker, date_et, atm_iv_pct, dte_used, method, ts_utc) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker, date_et) DO UPDATE SET "
                "atm_iv_pct=excluded.atm_iv_pct, dte_used=excluded.dte_used, "
                "method=excluded.method, ts_utc=excluded.ts_utc",
                (ticker, date_et, float(atm_iv_pct), dte_used, method, float(ts_utc)),
            )

    def bank_daily_strike_oi(self, ticker: str, date_et: str,
                             rows: list[tuple[float, float | None, float | None]],
                             ts_utc: float) -> None:
        """RC-359: batch-UPSERT the day's per-strike OI — last write of the session wins.
        rows = [(strike, call_oi, put_oi), ...]; empty rows write nothing (a gap is
        visible, a fabricated observation is not)."""
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO oi_daily (ticker, date_et, strike, call_oi, put_oi, ts_utc) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker, date_et, strike) DO UPDATE SET "
                "call_oi=excluded.call_oi, put_oi=excluded.put_oi, ts_utc=excluded.ts_utc",
                [(ticker, date_et, float(k), c, p, float(ts_utc)) for k, c, p in rows],
            )

    def prev_session_strike_oi(self, ticker: str, before_date_et: str) -> dict[float, tuple[float | None, float | None]]:
        """RC-359: the most recent banked session STRICTLY BEFORE before_date_et, as
        {strike: (call_oi, put_oi)}. Empty dict when no prior session exists (fail-closed:
        the ΔOI walls then render 'banking' — never a fabricated diff)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(date_et) FROM oi_daily WHERE ticker=? AND date_et<?",
                (ticker, before_date_et)).fetchone()
            prev = row[0] if row else None
            if not prev:
                return {}
            out: dict[float, tuple[float | None, float | None]] = {}
            for k, c, p in conn.execute(
                    "SELECT strike, call_oi, put_oi FROM oi_daily WHERE ticker=? AND date_et=?",
                    (ticker, prev)):
                out[float(k)] = (c, p)
            return out

    # Pass 4: minimum seconds between two recorded crosses of the same
    # (ticker, level_name, direction). Prevents tape-oscillation spam without
    # losing signal when price genuinely reverses (an "up" cross does not
    # debounce a subsequent "down" cross of the same level).
    LEVEL_CROSS_DEBOUNCE_S: float = 60.0

    def detect_and_log_level_crosses(
        self,
        *,
        ticker: str,
        prev_spot: float | None,
        cur_spot: float | None,
        levels: list[tuple[float, str]],
        ts_utc: float,
        ts_et: str,
        timeframe: str = "1m",
        zone_before: Optional[str] = None,
        zone_after: Optional[str] = None,
        debounce_s: Optional[float] = None,
    ) -> list[dict]:
        """Detect spot-vs-level crossings between two ticks and persist them.

        Pass 4 wire from server tick path. For each (level_value, level_name)
        in ``levels``, records a `level_crosses` row when prev_spot and cur_spot
        sit on opposite sides of level_value, debounced by
        (ticker, level_name, direction) within ``debounce_s`` seconds.

        Returns the list of crosses actually logged (so the caller can emit
        a single log line per cross — Pass 4 telemetry).
        """
        if prev_spot is None or cur_spot is None:
            return []
        if float(prev_spot) == float(cur_spot):
            return []
        direction = "up" if cur_spot > prev_spot else "down"
        deb = float(debounce_s) if debounce_s is not None else self.LEVEL_CROSS_DEBOUNCE_S
        debounce_since = float(ts_utc) - deb
        logged: list[dict] = []
        for raw_value, name in levels:
            if raw_value is None or name is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            crossed_up = float(prev_spot) < value <= float(cur_spot)
            crossed_down = float(cur_spot) <= value < float(prev_spot)
            if not (crossed_up or crossed_down):
                continue
            with self._connect() as conn:
                last = conn.execute(
                    "SELECT ts_utc FROM level_crosses "
                    "WHERE ticker = ? AND level_name = ? AND direction = ? "
                    "ORDER BY ts_utc DESC LIMIT 1",
                    (ticker, name, direction),
                ).fetchone()
            if last is not None and float(last["ts_utc"]) >= debounce_since:
                continue
            event = LevelCrossEvent(
                ticker=ticker,
                ts_utc=float(ts_utc),
                ts_et=str(ts_et),
                level_name=str(name),
                level_value=value,
                direction=direction,
                spot_at_cross=float(cur_spot),
                zone_before=zone_before,
                zone_after=zone_after,
                timeframe=str(timeframe),
            )
            self.log_level_cross(event)
            logged.append(
                {
                    "level_name": name,
                    "level_value": value,
                    "direction": direction,
                    "spot_at_cross": float(cur_spot),
                }
            )
        return logged

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
    # MODEL ACCURACY
    # ════════════════════════════════════════════════════════════════════════

    # RTH window for accuracy scoping: 9:30 inclusive to 16:00 exclusive, using the row's
    # stamped et_hour/et_minute. RC-345 / F09: the boundary is owned by the one authority,
    # time_et.RTH_START_MINS / RTH_END_MINS — not a second 570/960 literal here.
    ACCURACY_RTH_START_MIN: int = _RTH_START_MINS_AUTH
    ACCURACY_RTH_END_MIN: int = _RTH_END_MINS_AUTH


    # Pass 5a: minimum delta between two persisted accuracy rows for the same
    # (ticker, timeframe, model_version, horizon). The accuracy_pct value
    # itself only changes when new outcomes land, so equality of the value
    # is the natural dedup signal — but small floating noise should not skip.
    MODEL_ACCURACY_DEDUP_EPSILON: float = 0.05  # percentage points





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
#   _classify_direction_per_horizon  — points-threshold (per-horizon ATR-scaled) direction classification
#   _dist_bucket                 — distance bucketing for similar-setup matching
#   _bucket_lo / _bucket_hi     — bucket boundary helpers
#
# DO NOT redefine these here. If you need to change thresholds or logic,
# change them in math_exposure.py ONLY.


def _snapshot_update_key(row) -> tuple[str, int | None]:
    """
    UPDATE key for governed snapshot outcomes — `snapshot_id` only (Stage A2b).

    After snapshots schema repair (O-39), `rowid` must not substitute for application
    identity. Missing or invalid `snapshot_id` returns ("snapshot_id", None); callers
    must skip and log (see `_apply_bar_based_outcome_updates`).
    """
    try:
        snap_id = row["snapshot_id"]
    except (KeyError, IndexError, TypeError):
        snap_id = None
    if snap_id is not None:
        try:
            sid = int(snap_id)
        except (TypeError, ValueError):
            return "snapshot_id", None
        if sid > 0:
            return "snapshot_id", sid
    return "snapshot_id", None


def _fill_outcomes_latency_log(exec_ms: float) -> tuple[int | None, str | None]:
    """Classify fill_outcomes wall time → (logging level, tier label).

    SLA: >=5s and >=10s are WARNING (operator quiet-window FAIL). 1s+ is INFO.
    Live path must stay under SLA via FILL_OUTCOMES_LIVE_BATCH_LIMIT — not by
    demoting multi-second runs to INFO.
    """
    if exec_ms >= 10_000.0:
        return logging.WARNING, "10s+"
    if exec_ms >= 5_000.0:
        return logging.WARNING, "5s+"
    if exec_ms >= 1_000.0:
        return logging.INFO, "1s+"
    return None, None


def _row_has_nonnull(row, col: str) -> bool | None:
    """True/False if *col* present on *row*; None if the column is absent (fallback)."""
    try:
        return row[col] is not None
    except (KeyError, IndexError, TypeError):
        return None


def _already_filled(conn: sqlite3.Connection, row_key_col: str, row_key: int, col: str) -> bool:
    row = conn.execute(
        f"SELECT {col} FROM snapshots WHERE {row_key_col} = ?", (row_key,)
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
        row_key_col, row_key = _snapshot_update_key(row)
        if row_key is None:
            try:
                ts_u = float(row["ts_utc"])
            except (KeyError, IndexError, TypeError, ValueError):
                ts_u = None
            try:
                raw_sid = row["snapshot_id"]
            except (KeyError, IndexError, TypeError):
                raw_sid = None
            log.warning(
                "governed_outcome_skip_missing_snapshot_id ts_utc=%r snapshot_id=%r",
                ts_u,
                raw_sid,
            )
            continue
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
                thr = threshold_move_pts_for_slug(
                    slug, anchor_close=anchor_close, atr=atr_v, cfg=_mcfg
                )
                updates[odir] = _classify_direction_per_horizon(pts_move, thr)
                updates[opt] = round(pts_move, 4)
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
                f"UPDATE snapshots SET {set_clause} WHERE {row_key_col} = ?",
                list(updates.values()) + [row_key],
            )
            n_exec += 1
            continue

        updates = {}
        for odir, opt, n_min in OUTCOME_BAR_SPECS:
            spec = next(s for s in OUTCOME_MOVEMENT_V1_SPECS if s[5] == n_min)
            dcol, mcol, vdcol, tmcol, legtcol, _nm, slug = spec
            odir_filled = _row_has_nonnull(row, odir)
            if odir_filled is None:
                odir_filled = _already_filled(conn, row_key_col, row_key, odir)
            if odir_filled:
                vd_filled = _row_has_nonnull(row, vdcol)
                if vd_filled is None:
                    ex_v = conn.execute(
                        f"SELECT {vdcol} FROM snapshots WHERE {row_key_col} = ?",
                        (row_key,),
                    ).fetchone()
                    vd_filled = ex_v is not None and ex_v[0] is not None
                if vd_filled:
                    continue
            b_start = forward_bar_start_utc(t_snap, n_min)
            if not bar_complete_by_utc(b_start, tz):
                continue
            fwd_close = close_by_start.get(float(b_start))
            if fwd_close is None:
                continue
            pts_move = fwd_close - anchor_close
            thr = threshold_move_pts_for_slug(
                slug, anchor_close=anchor_close, atr=atr_v, cfg=_mcfg
            )
            updates[odir] = _classify_direction_per_horizon(pts_move, thr)
            updates[opt] = round(pts_move, 4)
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

        # Prefer prefetched outcome cols on *row* (live fill_outcomes batch path).
        existing_vals: dict[str, Any] = {}
        need_select = False
        for c in _outcome_cols:
            present = _row_has_nonnull(row, c)
            if present is None:
                need_select = True
                break
            existing_vals[c] = row[c] if present else None
        if need_select:
            _outcome_dir_cols = ", ".join(_outcome_cols)
            existing = conn.execute(
                f"""
                SELECT {_outcome_dir_cols}
                FROM snapshots WHERE {row_key_col} = ?
                """,
                (row_key,),
            ).fetchone()
            existing_vals = {c: existing[c] for c in _outcome_cols}
        all_filled = all(updates.get(c) or existing_vals.get(c) for c in _outcome_cols)
        if all_filled:
            updates["outcome_filled"] = 1

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE snapshots SET {set_clause} WHERE {row_key_col} = ?",
            list(updates.values()) + [row_key],
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


def market_session(et_hour: int, et_minute: int, *, et_date: str) -> str:
    """Classify an ET clock reading as a market session. With `et_date`, the CALENDAR decides first.

    RC-278: this returned "rth" for 10:00 on a Saturday, because minutes-since-midnight is not a
    session test — on five days in seven the two questions happen to agree. Every row this
    labelled fed `market_session` into `snapshots` and into the training filters, so a weekend
    reading entered the sample wearing the same label as a real one.

    RC-281: `et_date` is REQUIRED, not optional. It was optional for one commit and Cursor's
    audit measured the hole — `market_session(10, 0)` still returned "rth" on a Saturday, so
    the next caller could silently reintroduce weekend RTH labels and the training
    contamination of RC-54/57/58. Cursor confirmed no production caller omits it, so
    requiring it costs nothing and closes the reintroduction path. Without the date this
    function cannot know whether a session exists at all, and it must not guess.
    """
    from time_et import is_trading_day_et
    if not is_trading_day_et(str(et_date)):
        return "closed"
    mins = et_hour * 60 + et_minute
    # RC-345 / F09: the RTH open/close boundary is the ONE authority time_et.RTH_START_MINS /
    # RTH_END_MINS (aliased _RTH_*_MINS_AUTH), not a second 570/960 literal in this classifier.
    if mins < _RTH_START_MINS_AUTH:    # before 9:30
        return "premarket"
    elif mins < _RTH_END_MINS_AUTH:    # before 4:00pm
        return "rth"
    elif mins < 1200:                  # before 8:00pm (extended-hours end)
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


























def sql_snapshots_training_fingerprint_select(aggs_csv: str) -> str:
    """Grouped aggregate over snapshots for training fingerprinting (caller supplies SELECT list)."""
    return (
        f"SELECT timeframe, {aggs_csv} FROM snapshots "
        "WHERE timeframe IN (?, ?) GROUP BY timeframe ORDER BY timeframe"
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
                    market_session(et_now.hour, et_now.minute,
                                   et_date=et_now.strftime("%Y-%m-%d")),  # RC-278
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
