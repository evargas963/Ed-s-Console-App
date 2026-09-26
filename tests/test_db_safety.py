"""db_safety: SQL guard, backups/manifests, row-count invariants, canonical shutil policy."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db_safety import (
    install_production_sql_authorizer,
)


















def test_authorizer_blocks_drop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", raising=False)
    p = tmp_path / "g.db"
    conn = sqlite3.connect(str(p))
    install_production_sql_authorizer(conn)
    conn.execute("CREATE TABLE zz(a INTEGER)")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DROP TABLE zz")
















