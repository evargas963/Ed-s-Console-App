"""Runtime seam: configure_sqlite_connection applies WAL + NORMAL + busy_timeout."""
import sqlite3
import tempfile
from pathlib import Path

from db import (
    SQLITE_CACHE_SIZE_KIB,
    SQLITE_MMAP_SIZE_BYTES,
    configure_sqlite_connection,
)


def test_configure_sqlite_connection_enforces_wal_and_normal():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        conn = sqlite3.connect(str(p), timeout=30.0)
        try:
            configure_sqlite_connection(conn)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            # synchronous NORMAL == 1
            assert str(mode).lower() == "wal"
            assert int(sync) == 1
        finally:
            conn.close()


def test_configure_sqlite_connection_applies_access_tuning_rc50():
    """RC-50: every configured connection must carry the mmap + cache tuning, not the
    2 MB / no-mmap defaults that starved reads on the ~30 GB DB. Durability PRAGMAs
    (WAL, synchronous=NORMAL) must remain untouched by the tuning."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        conn = sqlite3.connect(str(p), timeout=30.0)
        try:
            configure_sqlite_connection(conn)
            mmap = int(conn.execute("PRAGMA mmap_size").fetchone()[0])
            cache = int(conn.execute("PRAGMA cache_size").fetchone()[0])
            # mmap is ENABLED and ~requested; SQLite rounds/caps it down to a page/mmap
            # boundary (this build caps a 2 GiB request at 2 GiB - 64 KiB), so assert
            # "enabled and within 1 MiB of the request", not exact equality.
            assert SQLITE_MMAP_SIZE_BYTES == 2 * 1024 ** 3
            assert 0 < mmap <= SQLITE_MMAP_SIZE_BYTES
            assert mmap >= SQLITE_MMAP_SIZE_BYTES - (1024 * 1024)
            assert cache == SQLITE_CACHE_SIZE_KIB == -131072  # 128 MiB (negative = KiB)
            # tuning must not have disturbed durability settings
            assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
            assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 1
        finally:
            conn.close()
