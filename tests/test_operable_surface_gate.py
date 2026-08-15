"""Unit tests for durable operable-surface G1–G4 gate (all-ticker scope)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from calibration.schema import ensure_calibration_schema
from tools.operable_surface_gate import (
    evaluate_operable_surface,
    quarantine_old_unattached,
)


def _seed(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            ticker TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            outcome_5c TEXT,
            PRIMARY KEY (ticker, ts_utc)
        )
        """
    )
    now = 1_800_000_000.0
    # Sentinels: old attached exact
    for i, tk in enumerate(("SPY", "QQQ", "IWM")):
        ts = now - 7200 - i
        conn.execute(
            "INSERT INTO snapshots(ticker, ts_utc, outcome_5c) VALUES (?,?,?)",
            (tk, ts, "up"),
        )
        conn.execute(
            """
            INSERT INTO calibration_decision_log(
              decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
              matched_snapshot_ts_utc, outcome_join_method, outcome_5c,
              research_excluded
            ) VALUES (?,?,'1m','trusted',?,'exact','up',0)
            """,
            (ts, tk, ts),
        )
    # Non-sentinel old unattached → fails all-ticker G1
    conn.execute(
        """
        INSERT INTO calibration_decision_log(
          decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
          research_excluded
        ) VALUES (?,'NVDA','1m','trusted',0)
        """,
        (now - 7200,),
    )
    # Live colocated
    live_ts = now - 60
    conn.execute(
        "INSERT INTO snapshots(ticker, ts_utc, outcome_5c) VALUES (?,?,?)",
        ("SPY", live_ts, "up"),
    )
    conn.execute(
        """
        INSERT INTO calibration_decision_log(
          decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
          matched_snapshot_ts_utc, outcome_join_method, outcome_5c,
          research_excluded
        ) VALUES (?,'SPY','1m','trusted',?,'exact','up',0)
        """,
        (live_ts, live_ts),
    )
    conn.commit()
    conn.close()


def test_sentinel_clean_is_not_operable_clean(tmp_path: Path) -> None:
    db = tmp_path / "g.db"
    _seed(db)
    now = 1_800_000_000.0
    report = evaluate_operable_surface(db, now_utc=now)
    assert report["gates"]["sentinel_old_missing_zero"] is True
    assert report["gates"]["G1_operable_old_missing_zero_all_ticker"] is False
    assert report["counts"]["old_missing_all_ticker"] == 1
    assert report["verdict"] == "SENTINEL_SURFACE_CLEAN"


def test_quarantine_drives_operable_clean(tmp_path: Path) -> None:
    db = tmp_path / "g.db"
    _seed(db)
    now = 1_800_000_000.0
    q = quarantine_old_unattached(db, now_utc=now)
    assert q["quarantined"] == 1
    report = evaluate_operable_surface(db, now_utc=now)
    assert report["gates"]["G1_operable_old_missing_zero_all_ticker"] is True
    assert report["verdict"] == "OPERABLE_SURFACE_CLEAN"


def test_attach_gap_gt59_fails_g3(tmp_path: Path) -> None:
    db = tmp_path / "g.db"
    _seed(db)
    now = 1_800_000_000.0
    conn = sqlite3.connect(str(db))
    # Attach the NVDA row with a 90s gap → G3 fail after quarantine of others? keep it.
    conn.execute(
        """
        UPDATE calibration_decision_log
        SET matched_snapshot_ts_utc = decision_ts_utc + 90,
            outcome_join_method='nearest_within_tol',
            outcome_5c='up'
        WHERE ticker='NVDA'
        """
    )
    conn.commit()
    conn.close()
    report = evaluate_operable_surface(db, now_utc=now)
    assert report["gates"]["G3_no_attach_gap_gt_59"] is False
    assert report["verdict"] == "OPERABLE_SURFACE_NOT_CLEAN"
