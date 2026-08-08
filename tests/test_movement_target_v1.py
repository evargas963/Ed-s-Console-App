"""Movement-target v1 threshold + outcome columns from fill_outcomes."""
from __future__ import annotations

from db import EdDB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from movement_target_threshold import (
    directional_and_move_labels_v1,
    movement_threshold_pts_v1,
)
from timeframe_config import CANONICAL_TIMEFRAME as CF

from tests.conftest import in_window_ts


def test_threshold_and_labels():
    thr = movement_threshold_pts_v1(100.0, 1.0, {"atr_multiplier": 0.5, "min_fraction_of_anchor": 0.001})
    assert thr >= 0.1
    assert directional_and_move_labels_v1(0.05, thr) == (None, "no_move")
    assert directional_and_move_labels_v1(thr * 2, thr) == ("up", "move")
    assert directional_and_move_labels_v1(-thr * 2, thr) == ("down", "move")


def test_fill_outcomes_writes_movement_columns(tmp_path):
    db = EdDB(tmp_path / "mt.db")
    # RC-306: t0 was 3_020_000.0 — epoch 1970-02-04. RC-214's collect-window law refuses
    # bars outside RTH on a trading day, so `upsert_1m_bars` wrote nothing and every
    # outcome_* column came back None: a true statement about the calendar, not about
    # fill_outcomes. 120 one-minute bars from 09:20 ET land inside the window.
    t0 = in_window_ts(9, 20, span_minutes=120)
    t_snap = t0 + 90.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                atr, horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("SPY", CF, t_snap, "test", 10, 30, "rth", 100.0, 0.5, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
    bars = []
    for i in range(120):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + 0.2 * i,
                "volume": 1.0,
            }
        )
    db.upsert_1m_bars("SPY", bars)
    db.fill_outcomes("SPY", CF, t_snap + 8000.0)
    with db._connect() as conn:
        row = conn.execute(
            "SELECT outcome_5c, outcome_move_5c, outcome_dir_5c, valid_dir_5c, threshold_move_5c "
            "FROM snapshots WHERE ticker='SPY'"
        ).fetchone()
    assert row["outcome_5c"] is not None
    assert row["outcome_move_5c"] in ("move", "no_move")
    assert row["threshold_move_5c"] is not None and float(row["threshold_move_5c"]) > 0
    assert row["valid_dir_5c"] in (0, 1)
    if row["outcome_move_5c"] == "move":
        assert row["outcome_dir_5c"] in ("up", "down")
        assert row["valid_dir_5c"] == 1
    else:
        assert row["outcome_dir_5c"] is None
        assert row["valid_dir_5c"] == 0
