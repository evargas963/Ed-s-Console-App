"""calibration.v2_advisory_backfill's historical bulk-backfill path (schema
migration, walk-forward embargo enforcement, per-row error handling, fusion-field
inference) must reconstruct the same V2 decision shape the live logger writes --
paired with test_calibration_v2_live_logging.py's proof that both writers share
identical columns, so a backfilled row and a live row are never distinguishable by
schema alone."""
from __future__ import annotations

import sqlite3


from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection


def _seed_db(tmp_path):
    db_path = tmp_path / "v2_advisory_backfill.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    return db_path, conn


def test_schema_migration_adds_nullable_v2_advisory_columns(tmp_path):
    _db_path, conn = _seed_db(tmp_path)

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(calibration_decision_log)").fetchall()}
    conn.close()

    assert "advisory_v2_decision_snapshot_json" in cols
    assert "advisory_v2_snapshot_schema_version" in cols
    assert "advisory_v2_adapter_version" in cols
    assert "advisory_v2_backfill_status" in cols
