"""db_safety: SQL guard, backups/manifests, row-count invariants, canonical shutil policy."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db_safety import (
    install_production_sql_authorizer,
)










def _canonical_console_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import runtime_layout

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(runtime_layout, "RUNTIME_ROOT", runtime)
    return runtime / "data" / "ed_console.db"








def test_authorizer_blocks_drop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", raising=False)
    p = tmp_path / "g.db"
    conn = sqlite3.connect(str(p))
    install_production_sql_authorizer(conn)
    conn.execute("CREATE TABLE zz(a INTEGER)")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DROP TABLE zz")






def _seed_both_permanent_databases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    import runtime_layout

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(runtime_layout, "RUNTIME_ROOT", runtime)
    console = runtime / "data" / "ed_console.db"
    stream = runtime / "data" / "stream_capture.db"
    console.parent.mkdir(parents=True)
    with sqlite3.connect(console) as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO snapshots(value) VALUES ('seed')")
    with sqlite3.connect(stream) as conn:
        conn.execute("CREATE TABLE stream_quotes_raw(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE stream_subscriptions(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO stream_quotes_raw(value) VALUES ('seed')")
    return console, stream










