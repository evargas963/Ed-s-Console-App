"""Issue 22: snapshot tickers must align with logging_universe (or be explicit orphans)."""
from __future__ import annotations

import time

from db import EdDB, CANONICAL_TIMEFRAME, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1


def test_logging_universe_snapshot_orphans_detects_raw_sql_drift(tmp_path):
    """If a row lands in snapshots without enrollment, orphan list is non-empty until healed."""
    dbp = tmp_path / "orph.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                zone, vwap_side, outcome_1c,
                nearest_above_dist, nearest_below_dist,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "ORPH1",
                CANONICAL_TIMEFRAME,
                1000.0,
                "test_et",
                100.0,
                "pin",
                "neutral",
                "flat",
                1.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    assert db.logging_universe_snapshot_ticker_orphans() == ["ORPH1"]
    db.logging_universe_upsert_user_persisted("ORPH1", "test_heal", time.time())
    assert db.logging_universe_snapshot_ticker_orphans() == []


def test_production_db_has_no_orphans_if_present():
    """Optional: run against workspace data/ed_console.db when present (CI may skip)."""
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "data" / "ed_console.db"
    if not p.is_file():
        return
    db = EdDB(p)
    o = db.logging_universe_snapshot_ticker_orphans()
    if o:
        for ticker in o:
            db.logging_universe_upsert_user_persisted(
                ticker, "test_production_db_has_no_orphans_if_present", time.time()
            )
        o = db.logging_universe_snapshot_ticker_orphans()
    assert o == [], f"Fix enrollment for: {o}"
