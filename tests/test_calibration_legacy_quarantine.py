"""
Prove calibration legacy quarantine: trusted writer rows vs migrated legacy; study paths exclude legacy.
"""

from __future__ import annotations

import sqlite3


from calibration.analyze_phase3 import analyze as analyze_phase3
from calibration.legacy_report import analyze as legacy_analyze
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_LEGACY, CALIBRATION_TRUST_TRUSTED
from calibration.validate_outcome_join import analyze as analyze_join
from db import EdDB, configure_sqlite_connection


def test_migration_marks_existing_rows_legacy_new_column_trusted(tmp_path):
    db_path = tmp_path / "q.db"
    db_path.touch()
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe)
        VALUES (1.0, 'SPY', '1m')
        """
    )
    conn.commit()
    conn.close()

    rep = legacy_analyze(db_path)
    assert rep["counts"]["total_rows"] == 1
    assert rep["counts"]["legacy_rows"] == 1
    assert rep["counts"]["trusted_rows"] == 0
    assert rep["counts"]["legacy_subcategory_sum_equals_legacy_rows"] is True

    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust)
        VALUES (2.0, 'SPY', '1m', ?)
        """,
        (CALIBRATION_TRUST_TRUSTED,),
    )
    conn.commit()
    conn.close()

    rep2 = legacy_analyze(db_path)
    assert rep2["counts"]["total_rows"] == 2
    assert rep2["counts"]["legacy_rows"] == 1
    assert rep2["counts"]["trusted_rows"] == 1


def test_phase3_excludes_legacy_from_labeled_sample(tmp_path):
    db_path = tmp_path / "p3.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    # Legacy: would pollute if included
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            outcome_5c, outcome_1c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
            canonical_json
        )
        VALUES (100.0, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                0, 0, 0, 0, '{"probability_up":0.4,"probability_down":0.3,"probability_flat":0.3,"confidence":"low"}')
        """,
        (CALIBRATION_TRUST_LEGACY,),
    )
    conn.commit()
    conn.close()

    out = analyze_phase3(db_path)
    prov = out.get("provenance") or {}
    assert prov.get("excluded_by_reason", {}).get("legacy_rows_excluded_from_study_dataset", 0) >= 1
    assert out.get("calibration_rows", 0) == 0


def test_join_validate_counts_trusted_only_by_default(tmp_path):
    db_path = tmp_path / "j.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
          decision_ts_utc, ticker, canonical_timeframe, calibration_trust, outcome_5c
        )
        VALUES (1.0, 'SPY', '1m', ?, 'flat')
        """,
        (CALIBRATION_TRUST_LEGACY,),
    )
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
          decision_ts_utc, ticker, canonical_timeframe, calibration_trust
        )
        VALUES (2.0, 'SPY', '1m', ?)
        """,
        (CALIBRATION_TRUST_TRUSTED,),
    )
    conn.commit()
    conn.close()

    r = analyze_join(db_path, trusted_only=True)
    assert r["calibration_row_count"] == 2
    assert r["calibration_legacy_row_count"] == 1
    assert r["rows_with_outcomes"] == 0
    assert r["rows_pending_outcomes"] == 1
    r_all = analyze_join(db_path, trusted_only=False)
    assert r_all["rows_with_outcomes"] == 1
