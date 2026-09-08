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
    backup_permanent_database,
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


def _canonical_console_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import runtime_layout

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(runtime_layout, "RUNTIME_ROOT", runtime)
    return runtime / "data" / "ed_console.db"


def test_backup_creates_valid_stable_db_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _canonical_console_path(tmp_path, monkeypatch)
    src.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE snapshots(x INTEGER)")
    conn.execute("INSERT INTO snapshots VALUES (1)")
    conn.commit()
    conn.close()
    root = tmp_path / "backups" / "db"
    bp, mp, man = backup_permanent_database(src, reason="test_op", backup_root=root)
    assert bp.is_file()
    assert mp.is_file()
    assert bp.name == "ed_console_backup.db"
    assert mp.name == "ed_console_backup_manifest.json"
    loaded = json.loads(mp.read_text(encoding="utf-8"))
    assert loaded == man
    assert loaded["reason"] == "test_op"
    assert loaded["source"] == str(src.resolve())
    assert loaded["validation"] == "ok"
    with sqlite3.connect(f"{bp.as_uri()}?mode=ro", uri=True) as check:
        assert check.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert check.execute("SELECT COUNT(*) FROM snapshots").fetchone() == (1,)


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


def test_approved_bulk_mutation_backup_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate bulk path: backup then mutate rows — manifest exists and counts non-decreasing."""
    src = _canonical_console_path(tmp_path, monkeypatch)
    src.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL)")
    conn.executemany("INSERT INTO snapshots (ticker) VALUES (?)", [("A",), ("B",)])
    conn.execute("INSERT INTO price_bars_1m VALUES ('A', 1.0)")
    conn.commit()
    before = critical_table_row_counts(conn)
    conn.close()

    root = tmp_path / "backups" / "db"
    bp, mp, _man = backup_permanent_database(src, reason="bulk_test", backup_root=root)
    assert bp.exists() and mp.exists()

    conn2 = sqlite3.connect(str(src))
    conn2.execute("INSERT INTO snapshots (ticker) VALUES ('C')")
    conn2.commit()
    after = critical_table_row_counts(conn2)
    conn2.close()
    assert_critical_row_counts_no_drop(before, after)


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
        conn.execute("CREATE TABLE stream_producer_heartbeat(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO stream_quotes_raw(value) VALUES ('seed')")
    return console, stream


def test_repeated_refresh_keeps_exactly_two_stable_backup_databases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    console, stream = _seed_both_permanent_databases(tmp_path, monkeypatch)
    root = tmp_path / "backups"
    for reason in ("first", "second"):
        backup_permanent_database(console, reason=reason, backup_root=root)
        backup_permanent_database(stream, reason=reason, backup_root=root)
    assert sorted(path.name for path in root.glob("*.db")) == [
        "ed_console_backup.db",
        "stream_capture_backup.db",
    ]
    assert not list(root.glob("*.db-wal"))
    assert not list(root.glob("*.db-shm"))
    receipts = sorted(path.name for path in root.glob("*_manifest.json"))
    assert receipts == [
        "ed_console_backup_manifest.json",
        "stream_capture_backup_manifest.json",
    ]


@pytest.mark.parametrize("identity", ["console", "stream"])
def test_online_backup_succeeds_with_concurrent_wal_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    console, stream = _seed_both_permanent_databases(tmp_path, monkeypatch)
    source = console if identity == "console" else stream
    table = "snapshots" if identity == "console" else "stream_quotes_raw"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")

    stop = threading.Event()
    wrote = threading.Event()

    def _writer() -> None:
        with sqlite3.connect(source, timeout=10) as conn:
            index = 0
            while not stop.is_set():
                conn.execute(f"INSERT INTO {table}(value) VALUES (?)", (f"v{index}",))
                conn.commit()
                index += 1
                wrote.set()

    thread = threading.Thread(target=_writer)
    thread.start()
    assert wrote.wait(timeout=5)
    try:
        backup_path, _, receipt = backup_permanent_database(
            source, reason="concurrent-writer-test", backup_root=tmp_path / "backups"
        )
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert receipt["validation"] == "ok"
    with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 1


def test_validation_failure_preserves_previous_valid_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db_safety as ds

    console, _ = _seed_both_permanent_databases(tmp_path, monkeypatch)
    root = tmp_path / "backups"
    backup_path, manifest_path, _ = backup_permanent_database(
        console, reason="known-good", backup_root=root
    )
    original_db = backup_path.read_bytes()
    original_manifest = manifest_path.read_bytes()

    def _fail_validation(*args, **kwargs):
        raise RuntimeError("forced validation failure")

    monkeypatch.setattr(ds, "_validate_backup", _fail_validation)
    with pytest.raises(RuntimeError, match="forced validation failure"):
        backup_permanent_database(console, reason="must-fail", backup_root=root)
    assert backup_path.read_bytes() == original_db
    assert manifest_path.read_bytes() == original_manifest
    assert not (root / ".ed_console_backup.db.staging").exists()


def test_manifest_promotion_failure_restores_previous_valid_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db_safety as ds

    console, _ = _seed_both_permanent_databases(tmp_path, monkeypatch)
    root = tmp_path / "backups"
    backup_path, manifest_path, _ = backup_permanent_database(
        console, reason="known-good", backup_root=root
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
        backup_permanent_database(console, reason="must-rollback", backup_root=root)
    assert backup_path.read_bytes() == original_db
    assert manifest_path.read_bytes() == original_manifest
    assert not list(root.glob("*.previous"))
    assert not list(root.glob("*.staging"))


def test_backup_rejects_noncanonical_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE snapshots(id INTEGER)")
    with pytest.raises(ValueError, match="not an approved canonical"):
        backup_permanent_database(source, reason="must-refuse", backup_root=tmp_path / "backups")
