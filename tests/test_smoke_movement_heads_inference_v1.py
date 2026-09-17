"""
No-fallback lock repair (2026-09-17, FB-01135): tools/smoke_movement_heads_inference_v1.py's
GOV governed-population predicate used to SQL-default a NULL horizon_outcome_schema_version
to 3 -- the identical shape and identical genuine-nullable root cause repaired repeatedly
across this branch (db.py, calibration/canonical_1m_grid_scan.py,
calibration/phase6_edge_discovery_governed_v1.py). Simplified to a bare equality.
"""
from __future__ import annotations

import sqlite3

from db import EdDB, configure_sqlite_connection
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from tools.smoke_movement_heads_inference_v1 import GOV


def test_no_coalesce_in_gov_predicate():
    assert "COALESCE" not in GOV
    assert "horizon_outcome_schema_version=3" in GOV


def test_gov_predicate_selects_bar_anchor_v1_row_and_excludes_other_schema_version(tmp_path):
    db_path = tmp_path / "smoke.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot,
            horizon_outcome_schema_version, outcome_1c, outcome_60c
        )
        VALUES ('SPY', '1m', 1_900_000_000.0, 'et', 100.0, ?, 'up', 'up')
        """,
        (HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,),
    )
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot,
            horizon_outcome_schema_version, outcome_1c, outcome_60c
        )
        VALUES ('QQQ', '1m', 1_900_000_001.0, 'et', 100.0, 2, 'up', 'up')
        """
    )
    conn.commit()

    tickers = sorted({r[0] for r in conn.execute(f"SELECT DISTINCT ticker FROM snapshots WHERE {GOV}")})
    conn.close()
    assert tickers == ["SPY"]
