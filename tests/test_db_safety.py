"""db_safety: SQL guard, backups/manifests, row-count invariants, canonical shutil policy."""

from __future__ import annotations

import json
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
    assert validate_sql_for_production_guard("DELETE FROM snapshots WHERE ticker='X'") is None


def test_validate_respects_dangerous_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED", "1")
    assert validate_sql_for_production_guard("DROP TABLE IF EXISTS z") is None


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


# ─────────────────────────────────────────────────────────────────────────────
# LIVE BACKUP SNAPSHOT SAFETY
#
# In WAL mode every transaction committed since the last checkpoint lives in the
# -wal file. A backup that copies only the .db file loses exactly those, and the
# loss is invisible to both the manifest SHA-256 and PRAGMA quick_check.
# ─────────────────────────────────────────────────────────────────────────────


def _wal_db_with_uncheckpointed_commits(path: Path, n: int) -> sqlite3.Connection:
    """WAL-mode DB with `n` rows COMMITTED and deliberately NOT checkpointed.

    Returns the still-open connection, because a live server holds connections open —
    closing the last one would checkpoint the WAL and dissolve the very condition under
    test."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.commit()
    conn.executemany("INSERT INTO snapshots (ticker) VALUES (?)",
                     [(f"T{i}",) for i in range(n)])
    conn.commit()
    assert Path(str(path) + "-wal").stat().st_size > 0, (
        "the attack requires committed rows still sitting in the WAL")
    return conn


def test_backup_captures_transactions_still_in_the_wal(tmp_path: Path) -> None:
    """A backup must contain every transaction COMMITTED at backup time.

    MEASURED against the previous `shutil.copy2` implementation on exactly this setup:
    rows committed with the WAL uncheckpointed produced a backup that answered
    `no such table: snapshots` — the table itself was absent — while `PRAGMA
    quick_check` on that backup still returned "ok". Size and SHA-256 describe the bytes
    copied, not the transactions that should have been there, so neither can catch it."""
    src = tmp_path / "live.db"
    live = _wal_db_with_uncheckpointed_commits(src, 500)
    try:
        bp, _mp, _man = backup_console_database(
            src, operation_name="wal_snapshot_test", backup_root=tmp_path / "out")
        got = sqlite3.connect(f"file:{bp}?mode=ro", uri=True)
        try:
            assert got.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 500, (
                "the backup is missing transactions committed before it started")
        finally:
            got.close()
    finally:
        live.close()


def test_mutation_control_a_file_copy_backup_loses_committed_wal_rows(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Reproduce the original mechanism — copy the .db file only — and
    show the data loss returns. Without this the test above could pass for the wrong
    reason (an incidental checkpoint) and prove nothing about the mechanism."""
    import shutil

    src = tmp_path / "live.db"
    live = _wal_db_with_uncheckpointed_commits(src, 500)
    try:
        dest = tmp_path / "copied.db"
        shutil.copy2(src, dest)          # the pre-fix mechanism, verbatim
        got = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
        try:
            try:
                n = got.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            except sqlite3.DatabaseError:
                n = None                  # table absent entirely — the observed failure
            assert n != 500, (
                "MUTATION CONTROL FAILED TO BITE: a .db-only file copy must NOT return "
                "all committed rows while they are still in the WAL")
            assert got.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok", (
                "quick_check is expected to report ok on the lossy copy — that is "
                "precisely why it cannot serve as backup-correctness evidence")
        finally:
            got.close()
    finally:
        live.close()
