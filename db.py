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
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone

from db_authority import (
    classify_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)
from typing import Callable, Optional, TypeVar

# ── Canonical timeframe (central config) ───────────────────────────────────
from timeframe_config import CANONICAL_TIMEFRAME
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1

# ── Centralized math (single source of truth) ────────────────────────────────
# Direction classification, distance bucketing, and all thresholds live in
# math_exposure.py. db.py MUST NOT define its own versions.
from math_exposure import MIN_SAMPLES_STATISTICAL  # noqa: F401 -- re-export: tests/test_action12_12_similar_setup_filters_fail_closed.py, tests/test_issue19_similarity_viability.py, tests/test_issue21_similarity_audit.py

# Issue 19 / 21 — tier column tuples + readiness checks (single source: similarity_audit;
# RC-REHAB-1 moved similarity_labeled_counts/similarity_tier_stop_viable/
# similarity_empirically_viable there too -- db.py MUST NOT define its own versions).
from similarity_audit import (  # noqa: F401 -- re-export: db_snapshots.py + external `from db import` callers
    SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS,
    SIMILARITY_TIER_STOP_OUTCOME_COLUMNS,
    similarity_labeled_counts,
    similarity_tier_stop_viable,
    similarity_empirically_viable,
)

from instrument_identity import ticker_storage_key
from db_logging_universe import LoggingUniverseMixin
from db_schema import SchemaMixin
from db_snapshots import SnapshotOutcomesMixin
from db_level_crossing import LevelCrossingMixin
from db_model_accuracy import ModelAccuracyMixin

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

# Live bar-upsert incremental window: closed bars already persisted are immutable on the
# live path; only the in-progress bar plus this overlap is rewritten each cycle. Three
# minutes covers the in-flight bar and clock skew between the accumulator and the DB grid.
LIVE_BARS_REUPSERT_OVERLAP_SEC = 180.0

# Live fill_outcomes caps work per call (newest-first). MEASURED 2026-08-03: EXACT 5394
# unfilled SPY BAR_ANCHOR_V1 rows on ~26.7GB DB made unbounded scans hit ~23s WARNING.
# Backlog drains across successive bg submits; do not demote WARNING to hide the cost.
FILL_OUTCOMES_LIVE_BATCH_LIMIT = max(
    1, int(os.environ.get("ED_FILL_OUTCOMES_LIVE_BATCH", "250"))  # caps-ok: optional operator env var
)

# RC-REHAB-1 (2026-09-22): SQLite connection tuning + tier-1 contention diagnostics
# extracted to db_sqlite_utils.py -- pure module-level functions/state, zero EdDB
# instance coupling; configure_sqlite_connection already had ~70 external callers
# treating it as a standalone utility. EdDB._connect/_tier1_snapshot_write (below)
# reference these as bare names resolved through db.py's own module globals (this
# import), which is what tests/test_db_sqlite_tier1_retry.py's
# monkeypatch.setattr("db.SQLITE_BUSY_MAX_RETRIES"/"db.SQLITE_LOCK_WAIT_WARN_MS"/
# "db.SQLITE_LOCK_WAIT_DISTRESS_MS", ...) patches; a plain re-export is sufficient
# since _tier1_snapshot_write itself stays in db.py.
from db_sqlite_utils import (  # noqa: F401
    SQLITE_BUSY_MAX_RETRIES,
    SQLITE_BUSY_BASE_SLEEP_SEC,
    SQLITE_BUSY_MAX_SLEEP_SEC,
    SQLITE_LOCK_WAIT_WARN_MS,
    SQLITE_LOCK_WAIT_DISTRESS_MS,
    SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT,
    SQLITE_WRITE_SLOW_MS,
    SQLITE_MMAP_SIZE_BYTES,
    SQLITE_CACHE_SIZE_KIB,
    record_sqlite_contention_event,
    sqlite_contention_metrics_snapshot,  # noqa: F401 -- re-export: server.py, app/api/routes/diagnostics.py, tests
    _sqlite_busy_or_locked,  # noqa: F401 -- re-export: tests/test_db_sqlite_tier1_retry.py
    configure_sqlite_connection,  # noqa: F401 -- re-export: ~70 external callers; delattr-tested by test_canonical_enforcement.py
)


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
# RC-REHAB-1 (2026-09-22): market_session/build_ts_et moved to time_et.py -- they had zero
# EdDB coupling and time_et.py is already the RTH_START_MINS/RTH_END_MINS/is_trading_day_et
# authority they depend on (previously aliased across the module boundary as _RTH_*_MINS_AUTH
# only so db.py could hold its own copy of market_session; that alias is gone with it).
from time_et import (  # noqa: E402,F401 -- re-export for legacy `from db import now_et/market_session/build_ts_et`
    now_et,
    market_session,
    build_ts_et,
)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def utc_ts() -> float:
    return _wall_time.time()


# ════════════════════════════════════════════════════════════════════════════════
# DATACLASSES — typed snapshot structure
# ════════════════════════════════════════════════════════════════════════════════

from db_models import (
    SnapshotRow,  # noqa: F401 -- re-export: 12 external `from db import SnapshotRow`
                  # callers (db_snapshots.py, server.py, base_money_path_capture.py,
                  # similarity_feature_universe.py, features/db_feature_adapter.py,
                  # tools/phase2_forward_write_verify.py, and several tests)
    LevelCrossEvent,
)


# ════════════════════════════════════════════════════════════════════════════════
# DATABASE MANAGER
# ════════════════════════════════════════════════════════════════════════════════

class EdDB(SchemaMixin, LoggingUniverseMixin, SnapshotOutcomesMixin, LevelCrossingMixin, ModelAccuracyMixin):
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
        if not getattr(self, "_bootstrap_sql_guard_suppress", False):  # caps-ok: fail-safe default -- a missing attribute (subclass/test harness bypassing __init__) defaults to installing the SQL guard, the more conservative direction, not a silent bypass
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
            return str(row[0]) if row and row[0] is not None else None  # caps-ok: keyed WHERE lookup, row is genuinely absent when the flag doesn't exist (see docstring)

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

# Re-exported for real external callers verified via a repo-wide search (both
# `from db import <name>` and `db.<name>` attribute-access forms): tests/
# test_ed_server_warn_quiet_window.py and calibration/repair_canonical_1m_shared.py
# respectively. The other 7 functions moved alongside these two have zero callers
# outside db_snapshots.py itself (verified the same way) and are not re-exported.
from db_snapshots import (
    _fill_outcomes_latency_log,  # noqa: F401
    _refresh_governed_outcomes_after_bar_mutation,  # noqa: F401
)


# All re-exported for external callers that do `from db import <name>`:
# db_health_audit.py, ml_data_common.py, similarity_feature_search.py,
# adaptive_similarity_engine.py, normalized_training_sync.py,
# verification/db_coverage.py, tools/issue19_option_a_post_validate.py.
from db_sql_fragments import (
    sql_flow_audit_count_where,  # noqa: F401
    sql_flow_audit_rows_where,  # noqa: F401
    sql_select_snapshots_columns,  # noqa: F401
    sql_select_snapshots_ticker_tf_order,  # noqa: F401
    sql_overlay_count_zpred,  # noqa: F401
    sql_overlay_count_zpred_vwap,  # noqa: F401
    sql_overlay_count_zpred_vwap_bucket,  # noqa: F401
    sql_overlay_select_star_where,  # noqa: F401
    sql_issue19_tier1_candidate_rows,  # noqa: F401
    sql_adaptive_broad_similarity_pool,  # noqa: F401
    sql_db_coverage_snap_tot,  # noqa: F401
    sql_db_coverage_col_nonnull,  # noqa: F401
    sql_db_coverage_col_labeled,  # noqa: F401
    sql_db_coverage_gap_lag,  # noqa: F401
    sql_snapshots_training_fingerprint_select,  # noqa: F401
    sql_issue19_snapshots_context_group,  # noqa: F401
    get_snapshot_sql,  # noqa: F401
)


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
