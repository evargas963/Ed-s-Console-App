"""db_safety: SQL guard, backups/manifests, row-count invariants, canonical shutil policy."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from db_safety import (
    UnsafeSqlError,
    assert_critical_row_counts_no_drop,
    backup_console_database,
    critical_table_row_counts,
    install_production_sql_authorizer,
    refuse_canonical_db_path_as_shutil_destination,
    validate_sql_for_production_guard,
)


def test_validate_blocks_drop_without_override() -> None:
    with pytest.raises(UnsafeSqlError, match="DROP"):
        validate_sql_for_production_guard("DROP TABLE snapshots;")


def test_validate_blocks_delete_without_where() -> None:
    with pytest.raises(UnsafeSqlError, match="DELETE"):
        validate_sql_for_production_guard("DELETE FROM snapshots")


def test_validate_allows_delete_with_where(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", raising=False)
    validate_sql_for_production_guard("DELETE FROM snapshots WHERE ticker='X'")


def test_validate_respects_dangerous_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", "1")
    validate_sql_for_production_guard("DROP TABLE IF EXISTS z")


def test_backup_creates_db_copy_and_manifest(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t(x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    root = tmp_path / "backups" / "db"
    bp, mp, man = backup_console_database(src, operation_name="test_op", backup_root=root)
    assert bp.is_file()
    assert mp.is_file()
    loaded = json.loads(mp.read_text(encoding="utf-8"))
    assert loaded["operation_name"] == "test_op"
    assert loaded["sha256"] == man["sha256"]
    assert loaded["source_db_path"] == str(src.resolve())


def test_row_count_drop_raises() -> None:
    with pytest.raises(RuntimeError, match="dropped"):
        assert_critical_row_counts_no_drop({"snapshots": 10}, {"snapshots": 9})


def test_critical_table_row_counts_minimal(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE snapshots (id INTEGER)")
    conn.execute("INSERT INTO snapshots VALUES (1)")
    conn.commit()
    cts = critical_table_row_counts(conn)
    conn.close()
    assert cts.get("snapshots") == 1


def test_authorizer_blocks_drop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", raising=False)
    p = tmp_path / "g.db"
    conn = sqlite3.connect(str(p))
    install_production_sql_authorizer(conn)
    conn.execute("CREATE TABLE zz(a INTEGER)")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|authorized"):
        conn.execute("DROP TABLE zz")


def test_refuse_canonical_as_shutil_destination(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import db_safety as ds

    fake_canon = (tmp_path / "ed_console.db").resolve()
    fake_canon.parent.mkdir(parents=True, exist_ok=True)
    fake_canon.write_bytes(b"x")

    def _is_canon(p: Path | str) -> bool:
        return Path(p).resolve() == fake_canon

    monkeypatch.setattr(ds, "is_canonical_db_path", _is_canon)
    monkeypatch.delenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", raising=False)

    with pytest.raises(ValueError, match="refusing shutil"):
        refuse_canonical_db_path_as_shutil_destination(fake_canon)

    monkeypatch.setenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", "1")
    refuse_canonical_db_path_as_shutil_destination(fake_canon)  # does not raise


def test_approved_bulk_mutation_backup_recorded(tmp_path: Path) -> None:
    """Simulate bulk path: backup then mutate rows — manifest exists and counts non-decreasing."""
    src = tmp_path / "live.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL)")
    conn.executemany("INSERT INTO snapshots (ticker) VALUES (?)", [("A",), ("B",)])
    conn.execute("INSERT INTO price_bars_1m VALUES ('A', 1.0)")
    conn.commit()
    before = critical_table_row_counts(conn)
    conn.close()

    root = tmp_path / "backups" / "db"
    bp, mp, _man = backup_console_database(src, operation_name="bulk_test", backup_root=root)
    assert bp.exists() and mp.exists()

    conn2 = sqlite3.connect(str(src))
    conn2.execute("INSERT INTO snapshots (ticker) VALUES ('C')")
    conn2.commit()
    after = critical_table_row_counts(conn2)
    conn2.close()
    assert_critical_row_counts_no_drop(before, after)
