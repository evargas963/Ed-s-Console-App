"""db.py — the console database: level crosses."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from db_authority import (
    classify_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)

log = logging.getLogger(__name__)


# One-time EdDB schema bootstrap (single-threaded init; avoids overlapping CREATE/migrate).
_SCHEMA_INIT_LOCK = threading.Lock()


#: SQLite access tuning (read-side accelerants for the large WAL DB).
#: mmap_size is a memory-mapped window over the DB file, backed by the shared OS page
#: cache (NOT per-connection heap), so a large value is cheap; 2 GiB covers the hot
#: index/recent-rows working set. cache_size is per-connection page cache — SQLite reads
#: a NEGATIVE value as KiB, so -131072 == 128 MiB (vs the ~2 MiB / -2000 default).
SQLITE_MMAP_SIZE_BYTES = 2 * 1024**3  # 2 GiB
SQLITE_CACHE_SIZE_KIB = -131072  # 128 MiB (negative = KiB in SQLite's PRAGMA convention)


def configure_sqlite_connection(conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000) -> None:
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
        # access tuning for a large DB: the defaults (2 MB page cache, no
        # memory-mapping) re-fault every read from disk through a tiny per-connection
        # cache. mmap_size maps the hot working set (shared via the OS page cache — not
        # per-connection RAM), and a 128 MB page cache holds hot index/data pages across
        # a query. Both are read-side accelerants; neither changes durability (WAL +
        # synchronous=NORMAL unchanged). Measured: wide-row read 8.55 -> 6.59 ms.
        f"PRAGMA mmap_size={SQLITE_MMAP_SIZE_BYTES}",
        f"PRAGMA cache_size={SQLITE_CACHE_SIZE_KIB}",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error as e:
            log.debug("configure_sqlite_connection: %s failed: %s", pragma, e)


# ── Database location (ONE APP, ONE MAIN, ONE DB) ───────────────────────────
# Default: data/ed_console.db, for every process and every worktree. No ambient setting
# (an agent role, ED_CONSOLE_DB, ED_DB_PATH) selects the production database: recovery and
# tests pass explicit paths to EdDB; runtime placement belongs only to runtime_layout.


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

    ticker: str
    ts_utc: float
    ts_et: str
    level_name: str  # 'Call Gamma Wall', 'VWAP', etc.
    level_value: float
    direction: str  # 'up', 'down'
    spot_at_cross: float
    zone_before: str | None
    zone_after: str | None
    timeframe: str


# ════════════════════════════════════════════════════════════════════════════════
# DATABASE MANAGER
# ════════════════════════════════════════════════════════════════════════════════


class EdDB:
    """
    Main database interface for Ed Console.
    Reads use a fresh connection per call (WAL allows concurrent readers). Writes use
    ordinary connections + SQLite busy_timeout/WAL.
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

    def _init_schema(self):
        """Create all tables if they don't exist. Safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""

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

    # ════════════════════════════════════════════════════════════════════════
    # LEVEL CROSS OPERATIONS
    # ════════════════════════════════════════════════════════════════════════

    def record_level_crosses(self, events: list[LevelCrossEvent]) -> list[dict]:
        """Store the level crosses of one price (server._log_level_crosses decides them), all in
        one transaction: every one is stored, or none is and the error is raised. Returns the
        rows stored, each as get_recent_crosses reads it back."""
        cols = [f.name for f in fields(LevelCrossEvent)]
        sql = (
            f"INSERT INTO level_crosses ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        )
        logged: list[dict] = []
        with self._connect() as conn:
            for event in events:
                d = asdict(event)
                cross_id = int(conn.execute(sql, [d[c] for c in cols]).lastrowid)
                logged.append({**d, "cross_id": cross_id})  # the stored row
        return logged

    def get_recent_crosses(self, ticker: str, n: int = 20) -> list:
        """The most recent level crosses, each the row record_level_crosses returns."""
        cols = ", ".join(["cross_id", *(f.name for f in fields(LevelCrossEvent))])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {cols} FROM level_crosses
                WHERE ticker = ?
                ORDER BY ts_utc DESC
                LIMIT ?
            """,
                (ticker, n),
            ).fetchall()
        return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════════
# SINGLETON — one DB instance for the app (thread-safe)
# ════════════════════════════════════════════════════════════════════════════════

_db_instance: EdDB | None = None
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
