"""Runtime seam: configure_sqlite_connection applies WAL + NORMAL + busy_timeout."""
import sqlite3
import tempfile
from pathlib import Path

from db import configure_sqlite_connection


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
