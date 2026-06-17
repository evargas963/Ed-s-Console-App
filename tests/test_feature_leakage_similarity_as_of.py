"""Similarity pool must exclude snapshots at or after the decision as_of_ts (no lookahead)."""
from __future__ import annotations

from pathlib import Path

from db import EdDB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_row(
    conn,
    *,
    ts_utc: float,
    outcome_1c_pts: float = 0.1,
    outcome_5c_pts: float = 0.2,
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot,
            zone, vwap_side, outcome_1c,
            nearest_above_dist, nearest_below_dist,
            outcome_1c_pts, outcome_5c_pts,
            horizon_outcome_schema_version, outcome_filled
        )
        VALUES (?, ?, ?, 'et', 100.0, 'pin_bull', 'above', 'up', 1.0, 1.0, ?, ?, ?, 0)
        """,
        (
            "SPY",
            CANONICAL_TIMEFRAME,
            ts_utc,
            outcome_1c_pts,
            outcome_5c_pts,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    )


def test_get_similar_setups_respects_as_of_ts_utc(tmp_path: Path) -> None:
    dbp = tmp_path / "sim_asof.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for ts in (1000.0, 2000.0, 3000.0):
            _insert_row(conn, ts_utc=ts)
    similar = db.get_similar_setups(
        ticker="SPY",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=50,
        as_of_ts_utc=2500.0,
    )
    ts_vals = [float(r["ts_utc"]) for r in similar]
    assert all(t < 2500.0 for t in ts_vals)
    assert 3000.0 not in ts_vals


def test_get_avg_move_respects_as_of_ts_utc(tmp_path: Path) -> None:
    dbp = tmp_path / "avg_asof.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        _insert_row(conn, ts_utc=1000.0, outcome_1c_pts=1.0)
        _insert_row(conn, ts_utc=2000.0, outcome_1c_pts=2.0)
        _insert_row(conn, ts_utc=3000.0, outcome_1c_pts=99.0)
    out = db.get_avg_move(
        "SPY",
        CANONICAL_TIMEFRAME,
        "pin_bull",
        "above",
        1.0,
        1.0,
        as_of_ts_utc=2500.0,
    )
    assert out["n"] >= 1
    assert out["avg_1c_pts"] is not None
    assert float(out["avg_1c_pts"]) < 50.0


def test_as_of_ts_utc_for_similarity_reads_inference_snapshot() -> None:
    from types import SimpleNamespace

    from prediction_engine import _as_of_ts_utc_for_similarity

    inp = SimpleNamespace(ticker="SPY", timeframe="1m", refresh_ts_utc=None)
    assert _as_of_ts_utc_for_similarity(inp, {"as_of_ts": 42.5}) == 42.5
    inp2 = SimpleNamespace(ticker="SPY", timeframe="1m", refresh_ts_utc=99.0)
    assert _as_of_ts_utc_for_similarity(inp2, {}) == 99.0
