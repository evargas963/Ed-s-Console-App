"""
No-fallback lock repair (2026-09-17, FB-00122/FB-00124): calibration/phase6_edge_discovery_governed_v1.py's
load_rows() governed-population query used to SQL-default a NULL horizon_outcome_schema_version
to 3 (== HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1). Identical shape and identical genuine-nullable
root cause already repaired across db.py and calibration/canonical_1m_grid_scan.py: db.py adds
the column via a bare ALTER TABLE ADD COLUMN with no DEFAULT for databases that pre-date it, so
a real NULL row is reachable and must not be silently counted as schema version 3.
calibration/phase65_edge_isolation_v1.py's FROZEN["governed_predicate"] docstring-style constant
quoted the same COALESCE as prose describing this exact query; reworded to match.
"""
from __future__ import annotations

import sqlite3

from calibration.phase6_edge_discovery_governed_v1 import load_rows
from calibration.phase65_edge_isolation_v1 import FROZEN
from db import EdDB, configure_sqlite_connection


def _insert_full_outcome_snapshot(conn, ticker, ts_utc, schema_version):
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot, horizon_outcome_schema_version,
            outcome_1c, outcome_1c_pts, outcome_5c, outcome_5c_pts,
            outcome_15c, outcome_15c_pts, outcome_60c, outcome_60c_pts
        )
        VALUES (?, '1m', ?, 'et', 100.0, ?,
                'up', 0.1, 'up', 0.2, 'up', 0.3, 'up', 0.4)
        """,
        (ticker, ts_utc, schema_version),
    )


def test_bar_anchor_v1_row_with_anchor_and_full_outcomes_is_loaded(tmp_path):
    db_path = tmp_path / "p6.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ts = 1_900_000_100.0
    conn.execute(
        """
        INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close, source)
        VALUES ('SPY', ?, ?, 100.0, 'test')
        """,
        (ts - 90.0, ts - 30.0),
    )
    _insert_full_outcome_snapshot(conn, "SPY", ts, 3)
    conn.commit()
    conn.close()

    rows, meta = load_rows(db_path)
    assert meta["snapshots_after_anchor"] == 1
    assert len(rows) == 1


def test_no_fallback_lock_repair_2026_09_17_no_coalesce_in_phase6_load_rows_source():
    import inspect

    from calibration import phase6_edge_discovery_governed_v1 as mod

    src = inspect.getsource(mod.load_rows)
    assert "COALESCE" not in src
    assert "horizon_outcome_schema_version = 3" in src


def test_frozen_governed_predicate_doc_matches_repaired_query():
    assert "COALESCE" not in FROZEN["governed_predicate"]
    assert "horizon_outcome_schema_version=3" in FROZEN["governed_predicate"]
