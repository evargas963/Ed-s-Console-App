"""
Anchor stability: trusted calibration rows — full audit JSON + phase3/4 exclusion of unanchored rows.
"""

from __future__ import annotations

import sqlite3

from calibration.anchor_audit import run_anchor_audit
from calibration.analyze_phase3 import analyze as analyze_phase3
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_TRUSTED
from db import EdDB, configure_sqlite_connection


def test_unanchored_trusted_row_excluded_from_phase3_labeled_sample(tmp_path):
    db_path = tmp_path / "anchor1.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            outcome_5c, outcome_1c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
            canonical_json)
        VALUES (2000.0, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                0, 0, 0, 0,
                '{"probability_up":0.34,"probability_down":0.33,"probability_flat":0.33,"confidence":"low"}')
        """,
        (CALIBRATION_TRUST_TRUSTED,),
    )
    conn.commit()
    conn.close()

    rep = run_anchor_audit(db_path, sample_limit=1, seed_sample=True)
    assert "calibration_trusted_anchor_audit" in rep
    ca = rep["calibration_trusted_anchor_audit"]
    assert ca["trusted_rows_total"] == 1
    assert ca["trusted_rows_without_anchor"] == 1
    assert ca["trusted_rows_with_anchor"] == 0
    assert ca["root_cause_miss_sum_check"] is True

    p3 = analyze_phase3(db_path)
    assert p3.get("calibration_rows", 0) == 0
    ex = (p3.get("provenance") or {}).get("excluded_by_reason") or {}
    assert ex.get("rows_without_bar_anchor_BAR_ANCHOR_V1", 0) >= 1


def test_anchored_trusted_row_passes_anchor_audit_and_enters_phase3_sample(tmp_path):
    db_path = tmp_path / "anchor2.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close, source)
        VALUES ('SPY', 1900.0, 1990.0, 100.0, 'test')
        """
    )
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            outcome_5c, outcome_1c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
            canonical_json)
        VALUES (2000.0, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                0, 0, 0, 0,
                '{"probability_up":0.34,"probability_down":0.33,"probability_flat":0.33,"confidence":"low"}')
        """,
        (CALIBRATION_TRUST_TRUSTED,),
    )
    conn.commit()
    conn.close()

    rep = run_anchor_audit(db_path, sample_limit=1, seed_sample=True)
    ca = rep["calibration_trusted_anchor_audit"]
    assert ca["trusted_rows_total"] == 1
    assert ca["trusted_rows_with_anchor"] == 1
    assert ca["trusted_rows_without_anchor"] == 0

    p3 = analyze_phase3(db_path)
    assert p3.get("calibration_rows", 0) == 1
    assert (p3.get("provenance") or {}).get("labeled_sample_count") == 1
