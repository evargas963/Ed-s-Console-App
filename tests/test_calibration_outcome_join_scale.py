"""
Scale proof for calibration ↔ snapshots outcome join (exact match, tol=0, resync).

Uses real `calibration_decision_log` and `snapshots` rows (EdDB schema), deterministic data,
`backfill_outcomes.backfill(tol=0)`, and `validate_outcome_join.analyze()`.
"""

from __future__ import annotations

import sqlite3

import pytest

from calibration.backfill_outcomes import backfill
from calibration.schema import ensure_calibration_schema
from calibration.validate_outcome_join import analyze
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key

N_MATCH = 2200
N_UNMATCHED = 120
BASE_TS = 1_850_000_000.0
_TICKERS = [ticker_storage_key(t) for t in ("SPY", "QQQ", "IWM", "DIA", "XLF", "XLE")]


def _outcomes_for_idx(i: int) -> tuple[str, str, str, str, float, float, float, float]:
    dirs = ("up", "down", "flat")
    return (
        dirs[i % 3],
        dirs[(i + 1) % 3],
        dirs[(i + 2) % 3],
        dirs[(i + 3) % 3],
        float(i) * 0.01,
        float(i + 1) * 0.01,
        float(i + 2) * 0.01,
        float(i + 3) * 0.01,
    )


@pytest.fixture
def scale_join_db(tmp_path):
    db_path = tmp_path / "outcome_join_scale.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)

    n_total = N_MATCH + N_UNMATCHED
    for i in range(n_total):
        ts = BASE_TS + float(i) * 60.0
        tkr = _TICKERS[i % len(_TICKERS)]
        conn.execute(
            """
            INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust)
            VALUES (?, ?, '1m', 'trusted')
            """,
            (ts, tkr),
        )
        if i >= N_MATCH:
            continue
        o1, o5, o15, o60, p1, p5, p15, p60 = _outcomes_for_idx(i)
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled,
                outcome_1c, outcome_5c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
            )
            VALUES (?, '1m', ?, 'scale', 10, 30, 'rth', 100.0, 3, 1,
                    ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tkr, ts, o1, o5, o15, o60, p1, p5, p15, p60),
        )
    conn.commit()
    conn.close()
    return db_path


def test_scale_exact_join_no_ambiguity_validate_passes(scale_join_db):
    stats = backfill(scale_join_db, tol_sec=0.0)
    assert stats["updated"] == N_MATCH
    assert stats.get("skipped_no_exact_match", 0) == N_UNMATCHED
    assert stats.get("ambiguous_duplicate_snapshots", 0) == 0
    assert stats.get("ambiguous_nearest_tie", 0) == 0

    conn = sqlite3.connect(str(scale_join_db))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    n_nearest = conn.execute(
        """
        SELECT COUNT(*) FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL AND IFNULL(outcome_join_method,'') != 'exact'
        """
    ).fetchone()[0]
    conn.close()
    assert n_nearest == 0

    rep = analyze(scale_join_db)
    assert rep["calibration_row_count"] == N_MATCH + N_UNMATCHED
    assert rep["rows_with_outcomes"] == N_MATCH
    assert rep["rows_pending_outcomes"] == N_UNMATCHED
    assert rep["ambiguous_exact_ts_duplicate_snapshots"] == 0
    assert rep["verification_fail"] == 0
    assert rep["verification_pass"] == N_MATCH
    assert rep["binary_pass"] is True


def test_resync_clears_intentional_outcome_drift(scale_join_db):
    backfill(scale_join_db, tol_sec=0.0)

    conn = sqlite3.connect(str(scale_join_db))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM calibration_decision_log WHERE outcome_5c IS NOT NULL ORDER BY id LIMIT 80"
        ).fetchall()
    ]
    for rid in ids:
        conn.execute(
            "UPDATE calibration_decision_log SET outcome_15c = 'drift_wrong' WHERE id=?",
            (rid,),
        )
    conn.commit()
    conn.close()

    bad = analyze(scale_join_db)
    assert bad["verification_fail"] == len(ids)
    assert bad["binary_pass"] is False

    backfill(scale_join_db, tol_sec=0.0)

    good = analyze(scale_join_db)
    assert good["verification_fail"] == 0
    assert good["verification_pass"] == N_MATCH
    assert good["binary_pass"] is True
