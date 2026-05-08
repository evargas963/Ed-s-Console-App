"""
Governed BAR_ANCHOR_V1 outcomes must stay consistent when price_bars_1m rows mutate (Issue: stale labels).
"""
from __future__ import annotations

import pytest

from db import EdDB
from horizon_outcomes import forward_bar_start_utc, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME as CF


def test_upsert_1m_bars_recomputes_affected_governed_outcomes(tmp_path):
    """After ON CONFLICT bar update, stored outcomes matching changed bars are refreshed."""
    db = EdDB(tmp_path / "gov.db")
    t0 = 1_020_000.0
    t_snap = t0 + 90.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("SPY", CF, t_snap, "test", 10, 30, "rth", 9999.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
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
    db.upsert_1m_bars("SPY", bars)
    db.fill_outcomes("SPY", CF, t_snap + 5000.0)

    b5 = forward_bar_start_utc(t_snap, 5)
    with db._connect() as conn:
        row = conn.execute(
            "SELECT outcome_5c, outcome_5c_pts FROM snapshots WHERE ticker='SPY' AND timeframe=?",
            (CF,),
        ).fetchone()
        assert row["outcome_5c"] is not None
        correct_5c = row["outcome_5c"]
        bar_row = conn.execute(
            "SELECT open, high, low, close, volume FROM price_bars_1m WHERE ticker='SPY' AND bar_start_ts_utc = ?",
            (b5,),
        ).fetchone()
        assert bar_row is not None
        conn.execute(
            "UPDATE snapshots SET outcome_5c = ?, outcome_5c_pts = 99.99 WHERE ticker='SPY' AND timeframe=?",
            ("up" if correct_5c != "up" else "down", CF),
        )

    db.upsert_1m_bars(
        "SPY",
        [
            {
                "datetime": b5,
                "open": float(bar_row["open"]),
                "high": float(bar_row["high"]),
                "low": float(bar_row["low"]),
                "close": float(bar_row["close"]),
                "volume": float(bar_row["volume"]),
            }
        ],
    )

    with db._connect() as conn:
        row2 = conn.execute(
            "SELECT outcome_5c, outcome_5c_pts FROM snapshots WHERE ticker='SPY' AND timeframe=?",
            (CF,),
        ).fetchone()
    assert row2["outcome_5c"] == correct_5c
    assert row2["outcome_5c_pts"] != 99.99


def test_upsert_1m_bars_can_defer_governed_outcome_refresh_for_bulk_backfill(tmp_path):
    """Bulk backfill can skip per-window refresh, then repair labels with the explicit bulk refresh."""
    db = EdDB(tmp_path / "gov_deferred.db")
    t0 = 1_520_000.0
    t_snap = t0 + 90.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "SPY",
                CF,
                t_snap,
                "test",
                10,
                30,
                "rth",
                100.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    bars = [
        {
            "datetime": t0 + i * 60.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0 + i,
            "volume": 1.0,
        }
        for i in range(80)
    ]

    db.upsert_1m_bars("SPY", bars, refresh_governed_outcomes=False)

    with db._connect() as conn:
        stale = conn.execute(
            "SELECT outcome_5c, outcome_5c_pts FROM snapshots WHERE ticker='SPY' AND timeframe=?",
            (CF,),
        ).fetchone()
    assert stale["outcome_5c"] is None
    assert stale["outcome_5c_pts"] is None

    audit = db.refresh_all_governed_bar_anchor_outcomes_v1()

    assert audit["updates_executed"] >= 1
    with db._connect() as conn:
        refreshed = conn.execute(
            "SELECT outcome_5c, outcome_5c_pts FROM snapshots WHERE ticker='SPY' AND timeframe=?",
            (CF,),
        ).fetchone()
    assert refreshed["outcome_5c"] is not None
    assert refreshed["outcome_5c_pts"] is not None


def test_refresh_all_governed_bar_anchor_outcomes_v1_aligns_with_bars(tmp_path):
    """Bulk repair forces snapshot labels to match current price_bars_1m."""
    db = EdDB(tmp_path / "gov2.db")
    t0 = 2_020_000.0
    t_snap = t0 + 120.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("QQQ", CF, t_snap, "test", 10, 30, "rth", 100.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
    bars = []
    for i in range(80):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 50.0,
                "high": 51.0,
                "low": 49.0,
                "close": 50.0 + i * 0.01,
                "volume": 1.0,
            }
        )
    db.upsert_1m_bars("QQQ", bars)
    db.fill_outcomes("QQQ", CF, t_snap + 4000.0)
    with db._connect() as conn:
        conn.execute(
            "UPDATE snapshots SET outcome_5c = 'flat', outcome_5c_pts = 0.0 WHERE ticker='QQQ'"
        )

    audit = db.refresh_all_governed_bar_anchor_outcomes_v1()
    assert audit["updates_executed"] >= 1

    import bisect

    from horizon_outcomes import OUTCOME_BAR_SPECS
    from math_exposure import classify_direction as cd

    with db._connect() as conn:
        r = conn.execute(
            "SELECT ts_utc, outcome_5c FROM snapshots WHERE ticker='QQQ' AND timeframe=?",
            (CF,),
        ).fetchone()
        tkr = "QQQ"
        t_snap = float(r["ts_utc"])
        bar_end_rows = conn.execute(
            "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker=? ORDER BY bar_end_ts_utc ASC",
            (tkr,),
        ).fetchall()
        bar_ends = [float(x["bar_end_ts_utc"]) for x in bar_end_rows]
        bar_end_closes = [float(x["close"]) for x in bar_end_rows]
        close_by_start = {
            float(x["bar_start_ts_utc"]): float(x["close"])
            for x in conn.execute("SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker=?", (tkr,))
        }
        ai = bisect.bisect_right(bar_ends, t_snap) - 1
        ac = bar_end_closes[ai]
        b5 = forward_bar_start_utc(t_snap, 5)
        fc = close_by_start[float(b5)]
        exp = cd(fc - ac, ac)
    assert r["outcome_5c"] == exp
