"""db.py — the program's reads of the one database (db_authority.canonical_db_path).

Every read is read-only (SQLite's mode=ro): the rows a start reads back (stored_rows), each
ticker's stored chain captures (last_capture_per_day) and the level crosses (EdDB). The Recorder
(stream_spine.CaptureWriter) is the database's one writer.
"""

from __future__ import annotations

import functools
import sqlite3
from contextlib import closing
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from calibration.complete_chain_capture import CAPTURE_BASIS, StoredCapture
from db_authority import (
    canonical_db_path,
    eddb_allow_noncanonical_path,
    is_canonical_db_path,
)
from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob
from option_contract import read_chain
from time_et import ET


def stored_rows(db_path: str | Path, table: str, query: str, *args: object) -> list[Any]:
    """Return the rows `query` reads of the record's `table`, read once at startup.

    The database is opened read-only. One that does not exist yet, or holds no such table (a
    first start), has no rows.
    """
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return []
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def last_capture_per_day(
    db_path: Path | str,
    ticker: str,
    days: int,
    *,
    before_et_date: str | None = None,
) -> list[StoredCapture]:
    """Return the last capture of each of the newest `days` market days (newest first).

    That is the close, with every expiry of that capture, its contracts read once
    (option_contract.read_chain). `before_et_date` keeps only days before it (the previous
    market day for a day-over-day view). No capture stored yet (no database, or no capture
    table) is none.
    """
    tk = ticker_storage_key(ticker)
    picked: list[tuple[str, float]] = []
    for (ts,) in stored_rows(
        db_path,
        "complete_chain_captures",
        "SELECT DISTINCT ts_utc FROM complete_chain_captures "
        "WHERE ticker=? AND completeness_basis=? ORDER BY ts_utc DESC",
        tk,
        CAPTURE_BASIS,
    ):
        day = datetime.fromtimestamp(ts, ET).date().isoformat()
        if before_et_date is not None and day >= before_et_date:
            continue
        if picked and picked[-1][0] == day:
            continue
        picked.append((day, ts))
        if len(picked) == days:
            break
    out: list[StoredCapture] = []
    for _day, ts in picked:
        rows = stored_rows(
            db_path,
            "complete_chain_captures",
            "SELECT chain_spot, chain_spot_ts, completeness_basis, chain_json "
            "FROM complete_chain_captures "
            "WHERE ticker=? AND completeness_basis=? AND ts_utc=? ORDER BY expiry",
            tk,
            CAPTURE_BASIS,
            ts,
        )
        out.append(
            StoredCapture.taken(
                ts,
                (rows[0][0], rows[0][1]),
                read_chain(c for r in rows for c in decode_json_blob(r[3])),
                rows[0][2],
            )
        )
    return out


#: SQLite access tuning (read-side accelerants for the large WAL DB).
#: mmap_size is a memory-mapped window over the DB file, backed by the shared OS page
#: cache (NOT per-connection heap), so a large value is cheap; 2 GiB covers the hot
#: index/recent-rows working set. cache_size is per-connection page cache — SQLite reads
#: a NEGATIVE value as KiB, so -131072 == 128 MiB (vs the ~2 MiB / -2000 default).
SQLITE_MMAP_SIZE_BYTES = 2 * 1024**3  # 2 GiB
SQLITE_CACHE_SIZE_KIB = -131072  # 128 MiB (negative = KiB in SQLite's PRAGMA convention)


def configure_sqlite_connection(conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000) -> None:
    """Set a reader's pragmas on a connection to the console's database (EdDB, read-only).

    How long it waits on the writer's lock, and its access tuning for a large database: the
    defaults (2 MB page cache, no memory-mapping) re-fault every read from disk through a tiny
    per-connection cache. mmap_size maps the hot working set (shared via the OS page cache, not
    per-connection memory), and a 128 MB page cache holds hot index and data pages across a
    query. Measured: a wide-row read 8.55 -> 6.59 ms. The database's journal mode and its
    synchronous setting are the writer's (stream_spine: WAL as it prepares the database, NORMAL
    on each connection it opens, CaptureWriter._open); a read-only connection changes neither.
    A pragma SQLite refuses raises.
    """
    for pragma in (
        f"PRAGMA busy_timeout={int(busy_timeout_ms)}",
        f"PRAGMA mmap_size={SQLITE_MMAP_SIZE_BYTES}",
        f"PRAGMA cache_size={SQLITE_CACHE_SIZE_KIB}",
    ):
        conn.execute(pragma)


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
        """Return the level crosses within `within_sec` of the ticker's newest, newest first.

        Each is the row the Recorder stored. None stored yet (no database, or no level_crosses
        table before the Recorder's first start) is no cross.
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
