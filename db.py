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
import time as _wall_time
import bisect
import logging
import threading
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

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
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    OUTCOME_BAR_SPECS,
    OUTCOME_MOVEMENT_V1_SPECS,
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
    MIN_SAMPLES_STATISTICAL,
)

# Issue 19 / 21 — tier column tuples + audit helpers (single source: similarity_audit)
from similarity_audit import (
    SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS,
    SIMILARITY_TIER_STOP_OUTCOME_COLUMNS,
)

from instrument_identity import ticker_storage_key
from db_logging_universe import LoggingUniverseMixin
from db_schema import SchemaMixin
from db_snapshots import SnapshotOutcomesMixin

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


def sqlite_contention_metrics_snapshot() -> dict[str, Any]:
    """Process-local tier-1 contention totals + recent events (for /api/diagnostics)."""
    with _SQLITE_CONTENTION_METRICS_LOCK:
        recent = list(_sqlite_contention_recent)[-50:]
        totals = {
            k: v
            for k, v in _sqlite_contention_totals.items()
            if k not in ("operations", "tickers", "threads")
        }
        return {
            "sqlite_lock_wait_count": int(totals.get("sqlite_lock_wait_count", 0)),
            "sqlite_lock_wait_total_ms": round(float(totals.get("sqlite_lock_wait_total_ms", 0.0)), 3),
            "sqlite_lock_wait_max_ms": round(float(totals.get("sqlite_lock_wait_max_ms", 0.0)), 3),
            "sqlite_busy_retry_count": int(totals.get("sqlite_busy_retry_count", 0)),
            "sqlite_database_locked_count": int(totals.get("sqlite_database_locked_count", 0)),
            "sqlite_tier1_fail_count": int(totals.get("sqlite_tier1_fail_count", 0)),
            "operations_affected": dict(_sqlite_contention_totals.get("operations") or {}),
            "tickers_affected": dict(_sqlite_contention_totals.get("tickers") or {}),
            "threads_affected": dict(_sqlite_contention_totals.get("threads") or {}),
            "recent_events": recent,
            "config": {
                "busy_timeout_ms": 30000,
                "journal_mode": "WAL",
                "busy_max_retries": SQLITE_BUSY_MAX_RETRIES,
                "lock_wait_warn_ms": SQLITE_LOCK_WAIT_WARN_MS,
            },
        }


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

# ── Database location (ONE APP, ONE MAIN, ONE DB) ───────────────────────────
# Default: data/ed_console.db, for every process and every worktree.
# RC-401 removed the per-agent fork that returned data/ed_console_claude.db under
# ED_AGENT_ROLE=claude — ambient process state was deciding which database the money
# path addressed, and it had already scattered rows into three sibling files.
# RC-534 removed ED_CONSOLE_DB / ED_DB_PATH from default production selection after an
# acknowledged override created an actively written worktree-local console authority.
# Recovery and tests pass explicit paths to EdDB; runtime placement belongs only to
# runtime_layout.
from runtime_layout import data_dir as _runtime_data_dir  # noqa: E402

DB_DIR = _runtime_data_dir()


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


def ensure_console_db_training_schema(db_path: Path | None = None) -> Path:
    """Idempotent: console DB must expose ``snapshots_1m_normalized`` for training fingerprints.

    Used by pytest, CI objective-audit, and governance live-drift reads. An empty or
    schema-less console DB file is in-scope — bootstrap via ``EdDB`` rather than
    surfacing raw ``OperationalError`` from ad-hoc SQL.
    """
    path = Path(db_path if db_path is not None else DB_PATH).resolve()
    if path.is_file():
        with sqlite3.connect(str(path), timeout=30.0) as conn:
            configure_sqlite_connection(conn)
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
            ).fetchone():
                return path
    EdDB(path)
    return path

# ── ET timezone (DST-aware; see time_et.py) ───────────────────────────────────
from time_et import now_et  # noqa: E402  — re-export for legacy `from db import now_et`
from time_et import (  # noqa: E402  — RC-345/F09: single RTH-boundary authority
    RTH_START_MINS as _RTH_START_MINS_AUTH,
    RTH_END_MINS as _RTH_END_MINS_AUTH,
)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

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

class EdDB(SchemaMixin, LoggingUniverseMixin, SnapshotOutcomesMixin):
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


    #: Best-effort durability checkpoint (operator directive, 2026-09-15, LOCK DISCIPLINE):
    #: never a critical write, so a genuinely stuck DB should fail this fast and loudly rather
    #: than tie up a caller for the class's normal 30s connection timeout. Callers (server.py)
    #: must never hold their own lock across a call into either method below -- these open and
    #: close their own connection per call, exactly like every other "ordinary write" in this
    #: class (see the class docstring: tier-1 hot-path writes get _tier1_snapshot_write's
    #: retry/lock discipline; this is not that -- it is throttled to roughly once per 20s per
    #: ticker by the caller and degrades to in-memory-only-this-session on failure).
    GAMMA_LAST_VALID_DB_TIMEOUT_SEC = 3.0

    def load_gamma_surface_last_valid(self, ticker: str) -> dict[tuple[float, str], dict]:
        """Every persisted last-known-valid gamma-surface cell for `ticker` -- the durable
        backing for the Options/Gamma heatmap's in-memory last-valid cache, read once per
        ticker to rehydrate it after a process restart. Raises on any real failure; the caller
        decides how to log/record it (server.py's own _LAST_VALID_GEX_CELLS_ERRORS)."""
        tk = ticker_storage_key(ticker)
        with self._connect(timeout_sec=self.GAMMA_LAST_VALID_DB_TIMEOUT_SEC) as conn:
            rows = conn.execute(
                "SELECT strike, expiry, gex, dex, vanna, captured_ts_utc "
                "FROM gamma_surface_last_valid WHERE ticker=?",
                (tk,),
            ).fetchall()
        return {
            (float(r["strike"]), str(r["expiry"])): {
                "gex": r["gex"], "dex": r["dex"], "vanna": r["vanna"],
                "captured_ts_utc": float(r["captured_ts_utc"]),
            }
            for r in rows
        }

    def persist_gamma_surface_last_valid(self, *, ticker: str, cells: list[dict]) -> None:
        """Durably upsert the CURRENTLY-valid gamma-surface cells only -- one batched
        transaction, never one write per cell. Raises on any real failure; the caller decides
        how to log/record it. See GAMMA_LAST_VALID_DB_TIMEOUT_SEC's own note on why this uses a
        short timeout rather than the class's normal 30s connection default."""
        tk = ticker_storage_key(ticker)
        if not tk or not cells:
            return
        rows = [
            (tk, float(c["strike"]), str(c["expiry"]), c.get("gex"), c.get("dex"), c.get("vanna"),
             float(c["captured_ts_utc"]))
            for c in cells
        ]
        with self._connect(timeout_sec=self.GAMMA_LAST_VALID_DB_TIMEOUT_SEC) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO gamma_surface_last_valid "
                "(ticker, strike, expiry, gex, dex, vanna, captured_ts_utc) VALUES (?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()



    # ════════════════════════════════════════════════════════════════════════
    # SNAPSHOT OPERATIONS
    # ════════════════════════════════════════════════════════════════════════


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

    def get_zone_distribution(self, ticker: str, timeframe: str) -> dict[str, int]:
        """Count snapshots per zone for ticker/timeframe (debug / diagnostics)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT zone, COUNT(*) AS cnt
                FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone IS NOT NULL
                GROUP BY zone
                ORDER BY cnt DESC
                """,
                (ticker, timeframe),
            ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            r = dict(row)
            zone = r.get("zone")
            if zone is not None:
                out[str(zone)] = int(r.get("cnt") or 0)   # external-key-ok: SQL alias (GROUP BY zone / ORDER BY cnt)
        return out

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

    def compute_accuracy(self, ticker: str, timeframe: str,
                          model_version: str = "statistical_v1",
                          *, rth_only: bool = False) -> dict:
        """
        Compute prediction accuracy for a given model version.
        Compares pred_Nc_up/down/flat_prob to actual outcome_Nc.

        rth_only (2026-07-06 operator decision): restrict to rows stamped inside
        RTH (09:30–16:00 ET). The model-accuracy audit measured SPY 5c at 40.1%
        all-hours but 34.5% RTH-only vs a 38.1% RTH majority baseline — the
        all-hours number flatters tradeable-session performance, so trading-facing
        surfaces read rth_only=True and keep all-hours as audit context only.

        Each horizon entry also carries the majority-class baseline of the SAME
        row set (baseline_pct / baseline_label / edge_vs_baseline_pp) so raw
        accuracy can never masquerade as edge, plus a scope stamp.
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.compute_accuracy")
        results = {}
        from ml_horizon import PRIMARY_DECISION_HORIZONS

        scope = "rth_0930_1600_et" if rth_only else "all_hours"
        rth_clause = ""
        if rth_only:
            rth_clause = (
                f" AND (et_hour * 60 + COALESCE(et_minute, 0)) >= {self.ACCURACY_RTH_START_MIN}"
                f" AND (et_hour * 60 + COALESCE(et_minute, 0)) < {self.ACCURACY_RTH_END_MIN} "
            )

        for horizon in PRIMARY_DECISION_HORIZONS:
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
                      {rth_clause}
                """, (ticker, timeframe, model_version)).fetchall()

            if not rows:
                # Fail closed: no rows in scope -> accuracy None (consumers drop the
                # horizon); NEVER silently widen the scope to all-hours.
                results[horizon] = {"total": 0, "accuracy": None, "scope": scope}
                continue

            correct = 0
            scored = 0
            from numeric_contract import direction_from_normalized_triplet, float_finite_or_none
            outcome_counts: dict[str, int] = {}
            for row in rows:
                # RC-345 / F22: predicted direction = the ONE argmax authority
                # numeric_contract.direction_from_normalized_triplet (same up>down>flat
                # tie-break), not a local max(probs, key=...). A row whose pred triplet is
                # MISSING is SKIPPED — never scored as a fabricated 'up' via `or 0`.
                _pu = float_finite_or_none(row[f"pred_{horizon}_up_prob"])
                _pd = float_finite_or_none(row[f"pred_{horizon}_down_prob"])
                _pf = float_finite_or_none(row[f"pred_{horizon}_flat_prob"])
                if _pu is None or _pd is None or _pf is None:
                    continue
                predicted = direction_from_normalized_triplet(_pu, _pd, _pf)
                actual    = row[outcome_col]
                outcome_counts[actual] = outcome_counts.get(actual, 0) + 1
                scored += 1
                if predicted == actual:
                    correct += 1

            total    = scored  # only rows with a real predicted triplet are scored (F22)
            accuracy = round(correct / total * 100, 1) if total > 0 else None
            baseline_label = max(outcome_counts, key=outcome_counts.get) if outcome_counts else None
            baseline_pct = (round(outcome_counts[baseline_label] / total * 100, 1)
                            if (total > 0 and baseline_label is not None) else None)
            results[horizon] = {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "scope": scope,
                "baseline_pct": baseline_pct,
                "baseline_label": baseline_label,
                "edge_vs_baseline_pp": (
                    round(accuracy - baseline_pct, 1) if accuracy is not None else None
                ),
            }

        return results

    # Pass 5a: minimum delta between two persisted accuracy rows for the same
    # (ticker, timeframe, model_version, horizon). The accuracy_pct value
    # itself only changes when new outcomes land, so equality of the value
    # is the natural dedup signal — but small floating noise should not skip.
    MODEL_ACCURACY_DEDUP_EPSILON: float = 0.05  # percentage points

    def log_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        total_predictions: int,
        correct_direction: Optional[int],
        accuracy_pct: Optional[float],
        avg_confidence: Optional[float] = None,
        ts_utc: Optional[float] = None,
    ) -> int:
        """Pass 5a writer for model_accuracy.

        Schema (see db.py:1247): one row per accuracy snapshot per
        (ticker, timeframe, model_version, horizon, ts_utc). Caller is
        expected to dedup via get_latest_model_accuracy before INSERT
        (the accuracy value only changes when new outcomes land — natural
        throttle).
        """
        ts = float(ts_utc) if ts_utc is not None else utc_ts()
        cd = int(correct_direction) if correct_direction is not None else None
        ap = float(accuracy_pct) if accuracy_pct is not None else None
        ac = float(avg_confidence) if avg_confidence is not None else None

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO model_accuracy "
                    "(ts_utc, ticker, timeframe, model_version, horizon, "
                    " total_predictions, correct_direction, accuracy_pct, avg_confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts, ticker, timeframe, model_version, horizon,
                        int(total_predictions), cd, ap, ac,
                    ),
                )
                return int(cur.lastrowid)

        return _do()

    def get_latest_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
    ) -> Optional[dict]:
        """Pass 5a reader: latest row for (ticker, timeframe, model_version, horizon)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_accuracy "
                "WHERE ticker = ? AND timeframe = ? "
                "  AND model_version = ? AND horizon = ? "
                "ORDER BY ts_utc DESC LIMIT 1",
                (ticker, timeframe, model_version, horizon),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_model_accuracy_history(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        limit: int = 50,
    ) -> list[dict]:
        """Pass 5a/5b reader: history of accuracy snapshots for chart / panel."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_accuracy "
                "WHERE ticker = ? AND timeframe = ? "
                "  AND model_version = ? AND horizon = ? "
                "ORDER BY ts_utc DESC LIMIT ?",
                (ticker, timeframe, model_version, horizon, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def maybe_log_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        total_predictions: int,
        correct_direction: Optional[int],
        accuracy_pct: Optional[float],
        avg_confidence: Optional[float] = None,
        ts_utc: Optional[float] = None,
    ) -> Optional[int]:
        """Pass 5a throttled writer: log only when accuracy_pct meaningfully changed
        vs the latest persisted row for this (ticker, timeframe, model_version, horizon).

        Returns the new row id when logged, or None when skipped (dedup or input None).
        """
        if accuracy_pct is None:
            return None
        latest = self.get_latest_model_accuracy(
            ticker=ticker, timeframe=timeframe,
            model_version=model_version, horizon=horizon,
        )
        if latest is not None:
            prev = latest.get("accuracy_pct")   # external-key-ok: sqlite column from get_latest_model_accuracy()
            if prev is not None and abs(float(prev) - float(accuracy_pct)) < self.MODEL_ACCURACY_DEDUP_EPSILON:
                return None
        return self.log_model_accuracy(
            ticker=ticker, timeframe=timeframe, model_version=model_version,
            horizon=horizon, total_predictions=total_predictions,
            correct_direction=correct_direction, accuracy_pct=accuracy_pct,
            avg_confidence=avg_confidence, ts_utc=ts_utc,
        )

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

def _tf_seconds(timeframe: str) -> float:
    """Return seconds per candle for a given timeframe string."""
    mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    return mapping.get(timeframe, 300)

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
