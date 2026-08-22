"""backfill_outcomes joins snapshots via ticker_storage_key (writer contract)."""

from __future__ import annotations

import sqlite3

from calibration.backfill_outcomes import backfill, resolve_snapshot_for_backfill
from calibration.schema import ensure_calibration_schema
from db import EdDB, SnapshotRow, configure_sqlite_connection


def test_resolve_snapshot_exact_join_normalizes_calibration_ticker(tmp_path) -> None:
    db_path = tmp_path / "bo_ticker_key.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    ts = 1_900_000_000.0
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust)
        VALUES (?, 'spy', '1m', 'trusted')
        """,
        (ts,),
    )
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
            horizon_outcome_schema_version, outcome_filled,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
        )
        VALUES ('SPY', '1m', ?, 'et', 10, 0, 'rth', 100.0, 3, 1,
                'up', 'up', 'up', 'up', 0.1, 0.2, 0.3, 0.4)
        """,
        (ts,),
    )
    conn.commit()

    snap, reason, method = resolve_snapshot_for_backfill(conn, "spy", ts, 0.0)
    conn.close()

    assert reason == "ok"
    assert method == "exact"
    assert snap is not None
    assert snap["outcome_5c"] == "up"


def test_backfill_attaches_when_calibration_ticker_not_canonical_cased(tmp_path) -> None:
    db_path = tmp_path / "bo_backfill_ticker.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    ensure_calibration_schema(conn)
    ts = 1_900_000_100.0
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust)
        VALUES (?, 'spy', '1m', 'trusted')
        """,
        (ts,),
    )
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
            horizon_outcome_schema_version, outcome_filled,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
        )
        VALUES ('SPY', '1m', ?, 'et', 10, 0, 'rth', 100.0, 3, 1,
                'up', 'down', 'flat', 'up', 0.1, 0.2, 0.3, 0.4)
        """,
        (ts,),
    )
    conn.commit()
    conn.close()

    stats = backfill(db_path, tol_sec=0.0)
    assert stats["updated"] == 1

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT outcome_5c, outcome_join_method FROM calibration_decision_log"
    ).fetchone()
    conn.close()
    assert row[0] == "down"
    assert row[1] == "exact"


def test_resolve_snapshot_bar_start_join_when_observation_seconds_differ(tmp_path) -> None:
    """Same UTC minute, different poll seconds → bar_start join, not 29s tol."""
    from horizon_outcomes import snapshot_bar_start_ts_utc

    db_path = tmp_path / "bo_bar_start.db"
    db = EdDB(db_path)
    bar = 1_900_000_020.0
    obs = bar + 17.0
    decision = bar + 40.0
    assert snapshot_bar_start_ts_utc(obs) == bar
    assert snapshot_bar_start_ts_utc(decision) == bar
    db.insert_snapshot(
        SnapshotRow(
            ticker="SPY",
            timeframe="1m",
            ts_utc=obs,
            ts_et="et",
            et_hour=10,
            et_minute=0,
            market_session="rth",
            spot=100.0,
            outcome_1c="up",
            outcome_5c="down",
            outcome_15c="up",
            outcome_60c="flat",
            outcome_1c_pts=0.1,
            outcome_5c_pts=0.2,
            outcome_15c_pts=0.3,
            outcome_60c_pts=0.4,
            outcome_filled=1,
        )
    )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    snap, reason, method = resolve_snapshot_for_backfill(conn, "SPY", decision, 0.0)
    conn.close()
    assert reason == "ok"
    assert method == "bar_start"
    assert snap is not None
    assert snap["outcome_5c"] == "down"
