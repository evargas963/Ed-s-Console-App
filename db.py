"""db.py — the console database: 1m bars, level crosses, daily OI and IV, the ticker board."""

from __future__ import annotations

import os
import sqlite3
import time as _wall_time
import logging
import threading
from pathlib import Path

from db_authority import (
    classify_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)
from dataclasses import dataclass, asdict
from typing import Callable, Optional, TypeVar

from instrument_identity import ticker_storage_key
from time_et import is_collect_window_bar_end_ts_utc

log = logging.getLogger(__name__)

T = TypeVar("T")


# Tier 1 only: upsert_1m_bars (short transactions on the live console DB).
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
    Tier-1 writes (upsert_1m_bars) use _tier1_snapshot_write with bounded
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
                self._ensure_logging_universe_table()
                self._migrate_drop_session_log_v1()
                self._migrate_drop_confluence_log_v1()
                self._migrate_drop_news_events_v1()
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
        Serialize 1m bar upserts with bounded sqlite busy/locked retries.
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
                # RC-236: severity calibrated like the SSE-duplicate precedent — a wait the
                # retry contract absorbs on an early attempt is NORMAL WAL contention under
                # 42 writers (SQLite busy_timeout doctrine) and logs INFO; WARNING is reserved
                # for genuine distress (a wait past the distress bar, or a deep retry), so the
                # quiet gate measures real defects instead of routine mid-RTH lock traffic.
                # Escalation retained: distress still WARNs.
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



    def _init_schema(self):
        """Create all tables if they don't exist. Safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""

            -- Schwab's streamed 1m bars (server._write_streamed_bar -> upsert_1m_bars)
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

    def upsert_1m_bars(self, ticker: str, bars: list) -> int:
        """Write Schwab's streamed 1m bars to price_bars_1m. `bars` are Candle objects from
        server._write_streamed_bar: ts is the bar start in epoch seconds, OHLC already read with
        schwab_number. A bar off the minute grid is refused and counted. Only bars ending in the
        RC-183 collect window are persisted. Returns the rows written."""
        tkr = ticker_storage_key(ticker)
        rows = []
        off_grid = 0
        outside_window = 0
        for b in bars:
            if b.ts % 60 != 0:
                off_grid += 1
                continue
            bar_end = b.ts + 60.0
            if not is_collect_window_bar_end_ts_utc(bar_end):
                outside_window += 1
                continue
            rows.append((tkr, b.ts, bar_end, b.open, b.high, b.low, b.close, b.volume))
        if off_grid:
            log.warning("upsert_1m_bars %s: %d bar(s) off the minute grid refused", tkr, off_grid)
        if outside_window:
            log.debug("upsert_1m_bars %s: %d bar(s) outside the collect window not persisted",
                      tkr, outside_window)
        if not rows:
            return 0

        def _do() -> int:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc,
                        open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, bar_start_ts_utc) DO UPDATE SET
                        bar_end_ts_utc = excluded.bar_end_ts_utc,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        source = excluded.source
                    """,
                    rows,
                )
            return len(rows)

        return self._tier1_snapshot_write("upsert_1m_bars", tkr, _do)


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

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return _do()

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
