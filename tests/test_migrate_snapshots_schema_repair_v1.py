from __future__ import annotations

import sqlite3
from pathlib import Path

from tools import migrate_snapshots_schema_repair_v1 as mig


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_drifted_db(path: Path, *, include_normalized: bool = True) -> None:
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (
                snapshot_id INT,
                ticker TEXT,
                timeframe TEXT,
                ts_utc REAL NOT NULL,
                ts_et TEXT,
                spot REAL,
                candle_open REAL,
                candle_high REAL,
                candle_low REAL,
                candle_close REAL,
                candle_volume REAL,
                horizon_outcome_schema_version INTEGER,
                outcome_filled INTEGER,
                created_at TEXT,
                production_only_metric REAL DEFAULT 7.5
            );
            CREATE INDEX idx_snap_ticker_tf_ts ON snapshots(ticker, timeframe, ts_utc);
            CREATE INDEX idx_snap_outcome_unfilled ON snapshots(ticker, timeframe, outcome_filled)
                WHERE outcome_filled = 0;
            CREATE INDEX idx_snap_ts ON snapshots(ts_utc);
            """
        )
        if include_normalized:
            conn.execute(
                """
                CREATE TABLE snapshots_1m_normalized (
                    snapshot_id INT,
                    ticker TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    ts_utc REAL NOT NULL,
                    ts_et TEXT NOT NULL,
                    spot REAL NOT NULL,
                    normalized_from_subminute INTEGER DEFAULT 0
                )
                """
            )
        rows = [
            (1, "SPY", "1m", 1_800.0, "2026-01-02 09:30:00", 100.0, 100.0, 101.0, 99.0, 100.5, 10.0, 3, 0, 7.5),
            (2, "SPY", "1m", 1_830.0, "2026-01-02 09:30:30", 101.0, 101.0, 102.0, 100.0, 101.5, 20.0, 3, 0, 7.5),
            (None, "SPY", "1m", 1_860.0, "2026-01-02 09:31:00", 102.0, 102.0, 103.0, 101.0, 102.5, 30.0, 3, 0, 7.5),
            (None, "QQQ", "5m", 1_920.0, "2026-01-02 09:32:00", 200.0, 200.0, 201.0, 199.0, 200.5, 40.0, 3, 0, 7.5),
        ]
        conn.executemany(
            """
            INSERT INTO snapshots (
                snapshot_id, ticker, timeframe, ts_utc, ts_et, spot, candle_open,
                candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled, production_only_metric
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()


def _schema_probe(path: Path, table: str = "snapshots") -> sqlite3.Row:
    with _connect(path) as conn:
        return conn.execute(f"PRAGMA table_info({table})").fetchone()


def _column_by_name(path: Path, table: str = "snapshots") -> dict[str, sqlite3.Row]:
    with _connect(path) as conn:
        return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_dry_run_default_does_not_mutate_and_reports_projection(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    audit = mig.run(db_path)

    assert audit["success"] is True
    assert audit["status"] == "dry_run"
    assert audit["would_apply"] is True
    assert audit["id_assignment_preview"]["first_new_snapshot_id"] == 3
    first = _schema_probe(db_path)
    assert first["type"].upper() == "INT"
    assert first["pk"] == 0


def test_apply_repairs_snapshots_schema_and_assigns_fresh_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is True
    assert audit["status"] == "applied"
    first = _schema_probe(db_path)
    assert first["name"] == "snapshot_id"
    assert first["type"].upper() == "INTEGER"
    assert first["pk"] == 1
    with _connect(db_path) as conn:
        ids = [r[0] for r in conn.execute("SELECT snapshot_id FROM snapshots ORDER BY ts_utc").fetchall()]
        assert ids == [1, 2, 3, 4]
        assert conn.execute("SELECT COUNT(*) FROM snapshots WHERE snapshot_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(DISTINCT snapshot_id) FROM snapshots").fetchone()[0] == 4


def test_apply_restores_db_py_declared_constraints_defaults_and_keeps_live_extras(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    before = _column_by_name(db_path)
    assert before["ticker"]["notnull"] == 0
    assert before["outcome_filled"]["dflt_value"] is None
    assert before["horizon_outcome_schema_version"]["notnull"] == 0
    assert before["horizon_outcome_schema_version"]["dflt_value"] is None
    assert "production_only_metric" in before

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is True
    after = _column_by_name(db_path)
    assert after["ticker"]["notnull"] == 1
    assert after["timeframe"]["notnull"] == 1
    assert after["ts_utc"]["notnull"] == 1
    assert after["ts_et"]["notnull"] == 1
    assert after["spot"]["notnull"] == 1
    assert after["outcome_filled"]["dflt_value"] == "0"
    assert after["horizon_outcome_schema_version"]["notnull"] == 1
    assert after["horizon_outcome_schema_version"]["dflt_value"] == "3"
    assert after["created_at"]["dflt_value"] in {"datetime('now')", "(datetime('now'))"}
    assert after["production_only_metric"]["type"].upper() == "REAL"
    assert after["production_only_metric"]["dflt_value"] == "7.5"
    assert "production_only_metric" in audit["target_extra_live_columns"]


def test_apply_creates_fresh_backup_using_configured_backup_root(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    backup_root = tmp_path / "backups"
    _create_drifted_db(db_path)

    audit = mig.run(db_path, apply=True, backup_root=backup_root)

    backup_path = Path(audit["backup_path"])
    assert backup_path.is_file()
    assert backup_path.parent == backup_root
    with _connect(backup_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 4
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
        assert cols["snapshot_id"]["type"].upper() == "INT"
        assert cols["outcome_filled"]["dflt_value"] is None


def test_apply_rebuilds_normalized_table_with_explicit_schema_and_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is True
    assert audit["normalized_rebuild"]["errors"] == []
    assert audit["normalized_validation"]["ok"] is True
    first = _schema_probe(db_path, "snapshots_1m_normalized")
    assert first["type"].upper() == "INTEGER"
    assert first["pk"] == 1
    with _connect(db_path) as conn:
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)").fetchall()}
        assert cols["ticker"]["notnull"] == 1
        assert cols["horizon_outcome_schema_version"]["notnull"] == 1
        assert cols["horizon_outcome_schema_version"]["dflt_value"] == "3"
        assert cols["normalized_from_subminute"]["notnull"] == 1
        assert cols["normalized_from_subminute"]["dflt_value"] == "0"
        assert "production_only_metric" in cols
        assert conn.execute("SELECT COUNT(*) FROM snapshots_1m_normalized").fetchone()[0] == 3


def test_second_run_is_schema_metadata_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)
    first = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")
    assert first["success"] is True

    second = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert second["success"] is True
    assert second["status"] == "noop_already_repaired"
    assert second["idempotence"] == "already_repaired"


def test_collision_rows_get_new_ids_above_max_not_rowid(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE snapshots SET snapshot_id = 3 WHERE rowid = 1")
        conn.execute("UPDATE snapshots SET snapshot_id = 4 WHERE rowid = 2")
        conn.commit()

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["collision_count"] == 2
    with _connect(db_path) as conn:
        qqq = conn.execute("SELECT snapshot_id FROM snapshots WHERE ticker = 'QQQ'").fetchone()[0]
        assert qqq == 6


def test_existing_non_null_duplicate_ids_refuse_without_mutating(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE snapshots SET snapshot_id = 2 WHERE rowid = 1")
        conn.commit()

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is False
    assert audit["status"] == "duplicate_existing_snapshot_id"
    first = _schema_probe(db_path)
    assert first["type"].upper() == "INT"


def test_source_empty_refuses(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM snapshots")
        conn.commit()

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is False
    assert audit["status"] == "source_empty"


def test_missing_db_refuses(tmp_path: Path) -> None:
    audit = mig.run(tmp_path / "missing.db", apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is False
    assert audit["status"] == "db_missing"


def test_identity_repaired_but_schema_partial_still_applies_full_repair(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                ts_utc REAL NOT NULL,
                ts_et TEXT NOT NULL,
                spot REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO snapshots(snapshot_id, ticker, timeframe, ts_utc, ts_et, spot) VALUES (NULL, 'SPY', '1m', 1, 'x', 1)"
        )
        conn.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'snapshots'")
        conn.commit()

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is True
    assert audit["status"] == "applied"
    after = _column_by_name(db_path)
    assert after["outcome_filled"]["dflt_value"] == "0"
    assert after["horizon_outcome_schema_version"]["notnull"] == 1


def test_post_apply_indexes_and_analyze_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is True
    with _connect(db_path) as conn:
        index_names = {r["name"] for r in conn.execute("PRAGMA index_list(snapshots)").fetchall()}
        assert {"idx_snap_ticker_tf_ts", "idx_snap_outcome_unfilled", "idx_snap_ts"} <= index_names
        assert conn.execute("SELECT COUNT(*) FROM sqlite_stat1 WHERE tbl = 'snapshots'").fetchone()[0] >= 1


def test_forced_apply_failure_preserves_source_table(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "ed_console.db"
    _create_drifted_db(db_path)

    def _boom(_db_path, *, tickers, clear_first):
        raise RuntimeError("forced materialize failure")

    monkeypatch.setattr(mig, "materialize_normalized_table", _boom)

    audit = mig.run(db_path, apply=True, backup_root=tmp_path / "backups")

    assert audit["success"] is False
    assert audit["status"] == "normalized_rebuild_failed"
    backup_path = Path(audit["backup_path"])
    assert backup_path.is_file()
    with _connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 4
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with _connect(backup_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
        assert cols["snapshot_id"]["type"].upper() == "INT"
        assert cols["outcome_filled"]["dflt_value"] is None
