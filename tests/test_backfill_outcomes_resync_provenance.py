"""
No-fallback lock repair (2026-09-17, FB-00088): backfill_outcomes' re-sync join key
used to fall back from a missing matched_snapshot_ts_utc to decision_ts_utc unconditionally
-- an unproven guess for a legacy row whose original match provenance was never recorded
(it could have been matched via nearest-tolerance to a *different* snapshot ts). The repair
only treats decision_ts_utc as the join key when outcome_join_method='exact' PROVES the two
are equal (see resolve_snapshot_for_backfill); otherwise it skips the row rather than guess.
"""
from __future__ import annotations

import sqlite3

from calibration.backfill_outcomes import _resync_existing_outcomes_from_snapshots
from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection


def _make_db(tmp_path, name):
    db_path = tmp_path / name
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    return conn


def _insert_snapshot(conn, ticker, ts, outcome_5c="up"):
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
            horizon_outcome_schema_version, outcome_filled,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
        )
        VALUES (?, '1m', ?, 'et', 10, 0, 'rth', 100.0, 3, 1,
                'up', ?, 'up', 'up', 0.1, 0.2, 0.3, 0.4)
        """,
        (ticker, ts, outcome_5c),
    )


def test_resync_uses_recorded_matched_snapshot_ts_when_present(tmp_path):
    conn = _make_db(tmp_path, "resync1.db")
    dec_ts = 1_900_000_000.0
    match_ts = 1_900_000_050.0
    _insert_snapshot(conn, "SPY", match_ts, outcome_5c="down")
    conn.execute(
        """
        INSERT INTO calibration_decision_log
            (decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
             outcome_5c, matched_snapshot_ts_utc, outcome_join_method)
        VALUES (?, 'SPY', '1m', 'trusted', 'up', ?, 'nearest_within_tol')
        """,
        (dec_ts, match_ts),
    )
    conn.commit()

    stats = _resync_existing_outcomes_from_snapshots(conn, outcomes_attached_ts_utc=2.0)
    assert stats["resynced"] == 1
    assert stats["resync_skipped_match_provenance_unrecorded"] == 0
    row = conn.execute("SELECT outcome_5c FROM calibration_decision_log").fetchone()
    conn.close()
    assert row["outcome_5c"] == "down"


def test_resync_uses_decision_ts_when_exact_method_proves_equality(tmp_path):
    conn = _make_db(tmp_path, "resync2.db")
    dec_ts = 1_900_000_100.0
    _insert_snapshot(conn, "SPY", dec_ts, outcome_5c="flat")
    conn.execute(
        """
        INSERT INTO calibration_decision_log
            (decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
             outcome_5c, matched_snapshot_ts_utc, outcome_join_method)
        VALUES (?, 'SPY', '1m', 'trusted', 'up', NULL, 'exact')
        """,
        (dec_ts,),
    )
    conn.commit()

    stats = _resync_existing_outcomes_from_snapshots(conn, outcomes_attached_ts_utc=2.0)
    assert stats["resynced"] == 1
    assert stats["resync_skipped_match_provenance_unrecorded"] == 0
    row = conn.execute("SELECT outcome_5c FROM calibration_decision_log").fetchone()
    conn.close()
    assert row["outcome_5c"] == "flat"


def test_resync_skips_legacy_row_with_unrecorded_match_provenance(tmp_path):
    conn = _make_db(tmp_path, "resync3.db")
    dec_ts = 1_900_000_200.0
    match_ts = 1_900_000_250.0
    # A snapshot DOES exist at decision_ts_utc, but since outcome_join_method is
    # NULL (pre-migration legacy row), the original match is not provably 'exact' --
    # guessing decision_ts_utc could silently attach the wrong snapshot for a row
    # that was actually nearest-tolerance-matched to `match_ts` originally.
    _insert_snapshot(conn, "SPY", dec_ts, outcome_5c="wrong_guess")
    _insert_snapshot(conn, "SPY", match_ts, outcome_5c="unreachable_without_provenance")
    conn.execute(
        """
        INSERT INTO calibration_decision_log
            (decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
             outcome_5c, matched_snapshot_ts_utc, outcome_join_method)
        VALUES (?, 'SPY', '1m', 'trusted', 'up', NULL, NULL)
        """,
        (dec_ts,),
    )
    conn.commit()

    stats = _resync_existing_outcomes_from_snapshots(conn, outcomes_attached_ts_utc=2.0)
    assert stats["resynced"] == 0
    assert stats["resync_skipped_match_provenance_unrecorded"] == 1
    row = conn.execute("SELECT outcome_5c FROM calibration_decision_log").fetchone()
    conn.close()
    # Untouched -- no guessed value written over the original.
    assert row["outcome_5c"] == "up"


def test_no_coalesce_left_in_backfill_outcomes_source():
    import inspect

    from calibration import backfill_outcomes as mod

    src = inspect.getsource(mod)
    code_only = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "COALESCE" not in code_only
