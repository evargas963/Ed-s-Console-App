"""Issue 16 — snapshots_1m_normalized must carry outcome_15c/outcome_60c after materialize."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db import EdDB, get_snapshot_sql
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, forward_bar_start_utc
from snapshot_normalizer import materialize_normalized_table
from timeframe_config import CANONICAL_TIMEFRAME as CF


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t16.db")


def test_normalized_table_has_horizon_schema_column(tmp_db: EdDB):
    with tmp_db._connect() as conn:
        names = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)").fetchall()}
    assert "horizon_outcome_schema_version" in names
    assert "outcome_15c" in names
    assert "outcome_60c" in names


def test_materialize_copies_outcome_15c_60c_from_snapshots(tmp_db: EdDB):
    """Same bar contract as test_horizon_bar_outcomes: fill snapshots then materialize; normalized matches."""
    t0 = 1_020_000.0
    t_snap = t0 + 90.0
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SPY",
                CF,
                t_snap,
                "test",
                10,
                30,
                "rth",
                9999.0,
                100.0,
                101.0,
                99.0,
                100.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                0,
            ),
        )
    bars = []
    for i in range(100):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + 0.1 * i,
                "volume": 1.0,
            }
        )
    tmp_db.upsert_1m_bars("SPY", bars)
    tmp_db.fill_outcomes("SPY", CF, t_snap + 5000.0)

    with tmp_db._connect() as conn:
        s = conn.execute(
            get_snapshot_sql("tests/test_issue16_normalized_outcome_materialize.py:snapshot_outcomes"),
            (CF,),
        ).fetchone()
    assert s["outcome_15c"] is not None
    assert s["outcome_60c"] is not None

    mat = materialize_normalized_table(Path(tmp_db.db_path), clear_first=True)
    assert not mat.get("errors"), mat["errors"]
    assert mat["normalized_rows"] == 1

    with tmp_db._connect() as conn:
        n = conn.execute(
            "SELECT outcome_1c, outcome_15c, outcome_60c, outcome_15c_pts, outcome_60c_pts "
            "FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()
    assert n["outcome_15c"] == s["outcome_15c"]
    assert n["outcome_60c"] == s["outcome_60c"]
    assert abs(float(n["outcome_15c_pts"]) - float(s["outcome_15c_pts"])) < 1e-5
    assert abs(float(n["outcome_60c_pts"]) - float(s["outcome_60c_pts"])) < 1e-5

    # Semantic: 15c pts matches bar math (anchor = bar 0 close at t0 when ts inside bar 1)
    anchor_close = 100.0 + 0.1 * 0.0
    b15 = forward_bar_start_utc(t_snap, 15)
    i15 = int(round((b15 - t0) / 60.0))
    forward_close_15 = 100.0 + 0.1 * float(i15)
    pts15 = forward_close_15 - anchor_close
    assert abs(float(s["outcome_15c_pts"]) - pts15) < 1e-5

