"""db.py — the level crosses in the one database (db_authority.canonical_db_path)."""

from __future__ import annotations

import functools
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass, fields
from pathlib import Path

from db_authority import (
    canonical_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)

log = logging.getLogger(__name__)


#: SQLite access tuning (read-side accelerants for the large WAL DB).
#: mmap_size is a memory-mapped window over the DB file, backed by the shared OS page
#: cache (NOT per-connection heap), so a large value is cheap; 2 GiB covers the hot
#: index/recent-rows working set. cache_size is per-connection page cache — SQLite reads
#: a NEGATIVE value as KiB, so -131072 == 128 MiB (vs the ~2 MiB / -2000 default).
SQLITE_MMAP_SIZE_BYTES = 2 * 1024**3  # 2 GiB
SQLITE_CACHE_SIZE_KIB = -131072  # 128 MiB (negative = KiB in SQLite's PRAGMA convention)


def configure_sqlite_connection(conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000) -> None:
    """Set the production pragmas for any sqlite3 connection touching the console DB.

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
# Default: data/ed.db, for every process and every worktree. No setting selects the
# production database: recovery and tests pass explicit paths to EdDB; runtime placement
# belongs only to runtime_layout.


@dataclass
class LevelCrossEvent:
    """Logged every time price crosses a key level.

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


@dataclass
class StoredCross(LevelCrossEvent):
    """A level cross as stored: the event and the id the database gave its row."""

    cross_id: int


@dataclass(frozen=True)
class ColumnInventory:
    """One column as SQLite's table_info reports it.

    `default_sql` is the DEFAULT clause SQLite
    holds for it, None when the column has none.
    """

    name: str
    default_sql: str | None


@dataclass(frozen=True)
class TableInventory:
    """One table of a database: its row count, columns and indexes."""

    name: str
    rows: int
    columns: tuple[ColumnInventory, ...]
    indexes: tuple[str, ...]


def inventory(db_path: Path) -> tuple[TableInventory, ...]:
    """Return every table of the database at `db_path`, read through a read-only connection.

    Read-only, so the census counts it without writing to it. A file that is not there raises.
    """
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        tables: list[TableInventory] = []
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall():
            quoted = name.replace('"', '""')
            (rows,) = conn.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()
            columns = tuple(
                ColumnInventory(c[1], c[4])
                for c in conn.execute(f'PRAGMA table_info("{quoted}")').fetchall()
            )
            indexes = tuple(
                i
                for (i,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                    (name,),
                ).fetchall()
            )
            tables.append(TableInventory(name, rows, columns, indexes))
        return tuple(tables)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════════
# DATABASE MANAGER
# ════════════════════════════════════════════════════════════════════════════════


class EdDB:
    """The console's read of the one database: its stored level crosses, read-only.

    The Recorder (stream_spine.CaptureWriter, store_crosses) is the database's one writer; every
    connection here is opened read-only (SQLite's mode=ro), so a write through it fails.
    """

    def __init__(
        self, db_path: Path | None = None, *, allow_noncanonical: bool | None = None
    ) -> None:
        self.db_path = Path(db_path or canonical_db_path()).resolve()
        if not is_canonical_db_path(self.db_path) and not eddb_allow_noncanonical_path(
            allow_noncanonical
        ):
            raise ValueError(
                f"EdDB: non-canonical database path {self.db_path!r}. "
                "Pass allow_noncanonical=True, or set ED_CONSOLE_ALLOW_NONCANONICAL_DB=1 "
                "for harness/test/alternate DBs."
            )

    def _connect(self, *, timeout_sec: float = 30.0) -> sqlite3.Connection:
        conn = sqlite3.connect(
            f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=timeout_sec
        )
        conn.row_factory = sqlite3.Row
        configure_sqlite_connection(conn, busy_timeout_ms=int(timeout_sec * 1000))
        return conn

    def get_recent_crosses(self, ticker: str, within_sec: float) -> list[StoredCross]:
        """Return the level crosses within `within_sec` of the ticker's newest, newest first,
        each the row the Recorder stored.

        None stored yet (no database, or no level_crosses table before the Recorder's first
        start) is no cross.
        """
        if not self.db_path.is_file():
            return []
        cols = ", ".join(["cross_id", *(f.name for f in fields(LevelCrossEvent))])
        with closing(self._connect()) as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'level_crosses'"
            ).fetchone():
                return []
            rows = conn.execute(
                f"""
                SELECT {cols} FROM level_crosses
                WHERE ticker = ?
                  AND ts_utc >= (SELECT MAX(ts_utc) FROM level_crosses WHERE ticker = ?) - ?
                ORDER BY ts_utc DESC
            """,
                (ticker, ticker, within_sec),
            ).fetchall()
        return [StoredCross(**dict(r)) for r in rows]


@functools.cache
def get_db() -> EdDB:
    """Return the program's one EdDB, made at the first call (functools.cache).

    An EdDB holds nothing but its path (a read-only connection per call), so a second one made by
    a concurrent first call reads the same database; the cache keeps one.
    """
    return EdDB()
