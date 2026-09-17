"""
No-fallback lock repair (2026-09-17, FB-00091/FB-00093): calibration/canonical_1m_grid_scan.py's
two snapshots-scoping queries used to SQL-default a NULL horizon_outcome_schema_version to
HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1. That column is genuinely nullable -- db.py adds it via a
bare `ALTER TABLE ADD COLUMN horizon_outcome_schema_version INTEGER` (no DEFAULT) for databases
that pre-date the column, so a real NULL row is reachable. Assuming a NULL means "the current
BAR_ANCHOR_V1 schema" would silently count a row of unknown/legacy schema as if it were
verified BAR_ANCHOR_V1. Dropping the COALESCE lets SQL NULL propagation exclude such rows from
the scan instead (same fix already applied to the identical shape in db.py).
"""
from __future__ import annotations

import sqlite3

from calibration.canonical_1m_grid_scan import scan_db
from db import EdDB, configure_sqlite_connection
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_snapshot(conn, ticker, ts_utc, schema_version):
    conn.execute(
        """
        INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, horizon_outcome_schema_version)
        VALUES (?, ?, ?, 'et', 100.0, ?)
        """,
        (ticker, CANONICAL_TIMEFRAME, ts_utc, schema_version),
    )


def test_bar_anchor_v1_snapshot_is_counted(tmp_path):
    db_path = tmp_path / "grid1.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    _insert_snapshot(conn, "SPY", 1_900_000_000.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)
    conn.commit()
    conn.close()

    result = scan_db(db_path, tz_now_utc=2_000_000_000.0)
    assert result.snapshots_bar_anchor_total == 1


def test_no_fallback_lock_repair_2026_09_17_null_schema_version_never_defaulted():
    """
    horizon_outcome_schema_version is NOT NULL DEFAULT 3 on a freshly created snapshots
    table (db.py's base CREATE TABLE), so a real NULL row can only occur on a database
    that pre-dates the column (added via a bare ALTER TABLE ADD COLUMN with no DEFAULT) --
    not constructible through the ORM in a fresh test DB. This is a structural proof
    (matching db.py's own test_fill_outcomes_unfilled_row_query_never_defaults_a_null_schema_version
    precedent for the identical shape) that the two scan queries compare
    horizon_outcome_schema_version directly rather than defaulting a NULL to
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1.
    """
    import inspect

    from calibration import canonical_1m_grid_scan as mod

    src = inspect.getsource(mod)
    code_only = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "COALESCE" not in code_only
    assert code_only.count("horizon_outcome_schema_version = ?") == 2
