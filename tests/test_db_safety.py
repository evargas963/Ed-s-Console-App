"""db_safety: SQL guard, backups/manifests, row-count invariants, canonical shutil policy."""

from __future__ import annotations

import json
import sqlite3
import threading
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
    assert validate_sql_for_production_guard("DELETE FROM snapshots WHERE ticker='X'") is None


def test_validate_respects_dangerous_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", "1")
    assert validate_sql_for_production_guard("DROP TABLE IF EXISTS z") is None


def test_backup_creates_db_copy_and_manifest(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE snapshots(x INTEGER)")
    conn.execute("INSERT INTO snapshots VALUES (1)")
    conn.commit()
    conn.close()
    root = tmp_path / "backups" / "db"
    bp, mp, man = backup_console_database(src, operation_name="test_op", backup_root=root)
    assert bp.is_file()
    assert mp.is_file()
    loaded = json.loads(mp.read_text(encoding="utf-8"))
    assert loaded["operation_name"] == "test_op"
    assert loaded == man
    assert loaded["source"] == str(src.resolve())
    assert loaded["destination"] == str(bp.resolve())
    assert loaded["validation"] == "ok"


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


def _seed_console_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO snapshots(value) VALUES ('seed')")


def test_repeated_refresh_keeps_one_stable_main_backup(tmp_path: Path) -> None:
    source = tmp_path / "ed_console.db"
    _seed_console_database(source)
    root = tmp_path / "backups"
    for operation in ("first", "second"):
        backup_console_database(source, operation_name=operation, backup_root=root)
    assert sorted(path.name for path in root.glob("*.db")) == ["ed_console_backup.db"]
    assert sorted(path.name for path in root.glob("*_manifest.json")) == [
        "ed_console_backup_manifest.json"
    ]
    assert not list(root.glob("*.db-wal"))
    assert not list(root.glob("*.db-shm"))


def test_online_backup_succeeds_with_concurrent_wal_writer(tmp_path: Path) -> None:
    source = tmp_path / "ed_console.db"
    _seed_console_database(source)
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")

    stop = threading.Event()
    wrote = threading.Event()

    def _writer() -> None:
        with sqlite3.connect(source, timeout=10) as conn:
            index = 0
            while not stop.is_set():
                conn.execute("INSERT INTO snapshots(value) VALUES (?)", (f"v{index}",))
                conn.commit()
                index += 1
                wrote.set()

    thread = threading.Thread(target=_writer)
    thread.start()
    assert wrote.wait(timeout=5)
    try:
        backup_path, _, receipt = backup_console_database(
            source,
            operation_name="concurrent-writer-test",
            backup_root=tmp_path / "backups",
        )
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert receipt["validation"] == "ok"
    with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] >= 1


def test_validation_failure_preserves_previous_valid_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db_safety as ds

    source = tmp_path / "ed_console.db"
    _seed_console_database(source)
    root = tmp_path / "backups"
    backup_path, manifest_path, _ = backup_console_database(
        source, operation_name="known-good", backup_root=root
    )
    original_db = backup_path.read_bytes()
    original_manifest = manifest_path.read_bytes()

    def _fail_validation(*args, **kwargs):
        raise RuntimeError("forced validation failure")

    monkeypatch.setattr(ds, "_validate_console_backup", _fail_validation)
    with pytest.raises(RuntimeError, match="forced validation failure"):
        backup_console_database(source, operation_name="must-fail", backup_root=root)
    assert backup_path.read_bytes() == original_db
    assert manifest_path.read_bytes() == original_manifest
    assert not (root / ".ed_console_backup.db.staging").exists()


def test_manifest_promotion_failure_restores_previous_valid_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db_safety as ds

    source = tmp_path / "ed_console.db"
    _seed_console_database(source)
    root = tmp_path / "backups"
    backup_path, manifest_path, _ = backup_console_database(
        source, operation_name="known-good", backup_root=root
    )
    original_db = backup_path.read_bytes()
    original_manifest = manifest_path.read_bytes()
    real_replace = ds.os.replace
    failed = False

    def _fail_manifest_once(src, dst):
        nonlocal failed
        if Path(src).name == ".ed_console_backup_manifest.json.staging" and not failed:
            failed = True
            raise OSError("forced manifest promotion failure")
        return real_replace(src, dst)

    monkeypatch.setattr(ds.os, "replace", _fail_manifest_once)
    with pytest.raises(OSError, match="forced manifest promotion failure"):
        backup_console_database(source, operation_name="must-rollback", backup_root=root)
    assert backup_path.read_bytes() == original_db
    assert manifest_path.read_bytes() == original_manifest
    assert not list(root.glob("*.previous"))
    assert not list(root.glob("*.staging"))


def test_default_backup_refuses_noncanonical_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    _seed_console_database(source)
    with pytest.raises(ValueError, match="not the canonical console database"):
        backup_console_database(source, operation_name="must-refuse")
