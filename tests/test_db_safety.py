"""db_safety: a canonical database refuses DROP and DETACH."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db_safety import (
    install_production_sql_authorizer,
)


def test_authorizer_blocks_drop(tmp_path: Path) -> None:
    p = tmp_path / "g.db"
    conn = sqlite3.connect(str(p))
    install_production_sql_authorizer(conn)
    conn.execute("CREATE TABLE zz(a INTEGER)")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DROP TABLE zz")
    conn.execute("CREATE INDEX zz_a ON zz(a)")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DROP INDEX zz_a")
    conn.execute("ATTACH DATABASE ':memory:' AS other")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DETACH DATABASE other")
