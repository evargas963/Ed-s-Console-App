"""Tests for migrate_snapshots_drop_retired_horizons_v1 (temp DB only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools import migrate_snapshots_drop_retired_horizons_v1 as mig
from tools.migrate_snapshots_drop_retired_horizons_v1 import AUDIT_EXPECTED_KEYS, RETIRED_COLUMNS


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_seeded_db(path: Path, *, n_rows: int = 4) -> None:
    retired_defs = ",\n                ".join(f"{c} REAL" for c in RETIRED_COLUMNS)
    with _connect(path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE ed_schema_flags (
                flag_key TEXT PRIMARY KEY,
                flag_value TEXT NOT NULL,
                set_ts_utc REAL NOT NULL
            );
            CREATE TABLE snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                ts_utc REAL NOT NULL,
                outcome_1c TEXT,
                outcome_5c TEXT,
                outcome_15c TEXT,
                outcome_60c TEXT,
                {retired_defs}
            );
            CREATE INDEX idx_snap_ticker_tf_ts ON snapshots(ticker, timeframe, ts_utc);
            """
        )
        for i in range(n_rows):
            conn.execute(
                """
                INSERT INTO snapshots (ticker, timeframe, ts_utc, outcome_1c)
                VALUES (?, ?, ?, ?)
                """,
                ("SPY", "1m", 1_800.0 + i * 60.0, "up"),
            )
        conn.commit()


def _column_names(path: Path) -> list[str]:
    with _connect(path) as conn:
        return [r["name"] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()]


def test_dry_run_does_not_mutate_and_reports_minus_fifteen_delta(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    audit_root = tmp_path / "audits"
    _create_seeded_db(db_path)
    before_cols = _column_names(db_path)

    audit = mig.run(db_path, apply=False, audit_root=audit_root)

    assert audit["success"] is True
    assert audit["status"] == "dry_run"
    assert audit["mode"] == "dry_run"
    assert audit["ddl_column_delta"] == -len(RETIRED_COLUMNS)
    assert set(audit["columns_dropped"]) == set(RETIRED_COLUMNS)
    assert _column_names(db_path) == before_cols
    assert Path(audit["audit_path"]).is_file()
    payload = json.loads(Path(audit["audit_path"]).read_text(encoding="utf-8"))
    assert AUDIT_EXPECTED_KEYS <= set(payload.keys())


def test_apply_drops_columns_preserves_rows_sets_flag(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    backup_root = tmp_path / "backups"
    audit_root = tmp_path / "audits"
    _create_seeded_db(db_path, n_rows=5)
    row_before = 5

    audit = mig.run(db_path, apply=True, backup_root=backup_root, audit_root=audit_root)

    assert audit["success"] is True
    assert audit["status"] == "applied"
    assert audit["row_count_before"] == row_before
    assert audit["row_count_after"] == row_before
    assert audit["integrity_check"] == "ok"
    cols = _column_names(db_path)
    for c in RETIRED_COLUMNS:
        assert c not in cols
    with _connect(db_path) as conn:
        flag = conn.execute(
            "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
            (mig.FLAG_KEY,),
        ).fetchone()
        assert flag is not None
        assert flag[0] == "1"
    assert Path(audit["backup_db_path"]).is_file()
    with _connect(Path(audit["backup_db_path"])) as bconn:
        assert int(bconn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]) == row_before


def test_second_apply_is_idempotent_already_applied(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    audit_root = tmp_path / "audits"
    _create_seeded_db(db_path)
    first = mig.run(db_path, apply=True, backup_root=tmp_path / "backups", audit_root=audit_root)
    assert first["success"] is True
    cols_after_first = _column_names(db_path)

    second = mig.run(db_path, apply=True, backup_root=tmp_path / "backups2", audit_root=audit_root)

    assert second["success"] is True
    assert second["already_applied"] is True
    assert second["status"] == "already_applied"
    assert _column_names(db_path) == cols_after_first


def test_backup_row_count_matches_source(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_seeded_db(db_path, n_rows=7)
    with _connect(db_path) as conn:
        expected = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])

    audit = mig.run(
        db_path,
        apply=True,
        backup_root=tmp_path / "backups",
        audit_root=tmp_path / "audits",
    )
    assert audit["success"] is True
    with _connect(Path(audit["backup_db_path"])) as bconn:
        assert int(bconn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]) == expected


def test_audit_json_has_required_contract_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    audit_root = tmp_path / "audits"
    _create_seeded_db(db_path)
    audit = mig.run(db_path, apply=False, audit_root=audit_root)
    on_disk = json.loads(Path(audit["audit_path"]).read_text(encoding="utf-8"))
    missing = AUDIT_EXPECTED_KEYS - set(on_disk.keys())
    assert not missing, f"missing audit keys: {sorted(missing)}"
    assert on_disk["mode"] == "dry_run"
    assert isinstance(on_disk["columns_before"], list)
    assert isinstance(on_disk["columns_after"], list)
