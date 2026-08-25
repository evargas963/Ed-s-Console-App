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


def test_production_db_orphan_report_is_read_only():
    """AUDIT ROUND 2 (2026-08-25): the previous form of this test UPSERTED user_persisted
    rows into the LIVE production DB for every snapshot orphan — measured: 13
    logging_universe rows carried this test's name as enrollment_source, including every
    recent "user" enrollment, silently defeating the operator's 2026-05-31
    TICKER-PREVIEW-NO-ENROLL decision and destroying enrollment provenance.

    A test NEVER mutates the production database. This variant reports orphans and
    skips: the enroll-or-stop call on an orphan is the operator's (ledger RC row), not a
    test's. The tmp-path variant above still executes the orphan-detection behavior."""
    from pathlib import Path

    import pytest

    p = Path(__file__).resolve().parents[1] / "data" / "ed_console.db"
    if not p.is_file():
        return
    db = EdDB(p)
    o = db.logging_universe_snapshot_ticker_orphans()
    if o:
        pytest.skip(
            f"production DB carries {len(o)} snapshot-ticker orphan(s) awaiting the "
            f"operator's enroll-or-stop decision (never healed by a test): {o}")
    assert o == [], "unreachable: a non-empty orphan list skips above"


def test_reupsert_does_not_overwrite_enrollment_provenance(tmp_path):
    """Write-once provenance: a second upsert moves last_seen only, never the source."""
    dbp = tmp_path / "prov.db"
    db = EdDB(dbp)
    db.logging_universe_upsert_user_persisted("PROV1", "original_operator_add", 1000.0)
    db.logging_universe_upsert_user_persisted("PROV1", "later_touch", 2000.0)
    with db._connect() as conn:
        src, last = conn.execute(
            "SELECT enrollment_source, last_seen_ts_utc FROM logging_universe "
            "WHERE ticker='PROV1'").fetchone()
    assert src == "original_operator_add"
    assert last == 2000.0
