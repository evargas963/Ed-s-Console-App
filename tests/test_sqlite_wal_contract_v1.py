"""Runtime seam: configure_sqlite_connection sets a reader's wait and access tuning."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from db import (
    SQLITE_CACHE_SIZE_KIB,
    SQLITE_MMAP_SIZE_BYTES,
    configure_sqlite_connection,
)

pytestmark = pytest.mark.rail


def test_configure_sqlite_connection_applies_access_tuning_rc50():
    """RC-50: every configured connection must carry the mmap + cache tuning.

    Not the 2 MB / no-mmap defaults that starved reads on the ~30 GB DB. The durability
    settings are the writer's (WAL, synchronous=NORMAL, as stream_spine sets them), and the
    tuning leaves them as the writer set them.
    """
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        conn = sqlite3.connect(str(p), timeout=30.0)
        try:
            conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            configure_sqlite_connection(conn)
            mmap = int(conn.execute("PRAGMA mmap_size").fetchone()[0])
            cache = int(conn.execute("PRAGMA cache_size").fetchone()[0])
            # mmap is ENABLED and ~requested; SQLite rounds/caps it down to a page/mmap
            # boundary (this build caps a 2 GiB request at 2 GiB - 64 KiB), so assert
            # "enabled and within 1 MiB of the request", not exact equality.
            assert SQLITE_MMAP_SIZE_BYTES == 2 * 1024**3
            assert 0 < mmap <= SQLITE_MMAP_SIZE_BYTES
            assert mmap >= SQLITE_MMAP_SIZE_BYTES - (1024 * 1024)
            assert cache == SQLITE_CACHE_SIZE_KIB == -131072  # 128 MiB (negative = KiB)
            # tuning must not have disturbed durability settings
            assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
            assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 1
        finally:
            conn.close()


def test_a_read_only_reader_of_a_database_in_the_default_journal_mode_is_refused_nothing():
    """A read-only connection, as EdDB opens one, to a database not in WAL.

    Each of the reader's pragmas is one a read-only connection may set: none is refused, so
    nothing is passed over in silence (a write pragma here was refused and logged at debug);
    the journal mode stays the database's own.
    """
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        made = sqlite3.connect(p)
        made.execute("CREATE TABLE t (a)")
        made.commit()
        made.close()
        reader = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        try:
            configure_sqlite_connection(reader, busy_timeout_ms=1234)
            assert int(reader.execute("PRAGMA busy_timeout").fetchone()[0]) == 1234
            assert str(reader.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "delete"
        finally:
            reader.close()
