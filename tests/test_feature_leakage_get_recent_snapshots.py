"""Causal cutoff for EdDB.get_recent_snapshots (replay / ML sequence paths)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_row(conn, *, ts_utc: float) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot,
            zone, vwap_side, outcome_1c,
            nearest_above_dist, nearest_below_dist,
            outcome_1c_pts, outcome_3c_pts,
            horizon_outcome_schema_version, outcome_filled
        )
        VALUES (?, ?, ?, 'et', 100.0, 'pin_bull', 'above', 'up', 1.0, 1.0, 0.1, 0.2, ?, 0)
        """,
        ("SPY", CANONICAL_TIMEFRAME, ts_utc, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
    )


def test_get_recent_snapshots_excludes_row_equal_to_as_of_bar_boundary(tmp_path: Path) -> None:
    """Strict upper bound: rows with ts_utc == as_of_ts_utc are excluded (no >= sneak)."""
    from db import EdDB

    dbp = tmp_path / "boundary.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        _insert_row(conn, ts_utc=99.0)
        _insert_row(conn, ts_utc=100.0)
    rows = db.get_recent_snapshots("SPY", CANONICAL_TIMEFRAME, n=10, as_of_ts_utc=100.0)
    tss = [float(r["ts_utc"]) for r in rows]
    assert tss == [99.0]
    assert 100.0 not in tss


def test_get_recent_snapshots_respects_as_of_ts_utc(tmp_path: Path) -> None:
    from db import EdDB

    dbp = tmp_path / "t.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for ts in (100.0, 200.0, 300.0, 400.0):
            _insert_row(conn, ts_utc=ts)
    rows = db.get_recent_snapshots(
        "SPY", CANONICAL_TIMEFRAME, n=10, as_of_ts_utc=250.0
    )
    tss = sorted([float(r["ts_utc"]) for r in rows])
    assert tss == [100.0, 200.0]
    assert all(float(r["ts_utc"]) < 250.0 for r in rows)


def test_predict_lstm_requires_as_of_ts_in_inference(monkeypatch) -> None:
    import ml_predict as mp
    from features.lstm_sequence_input import LstmSequenceInputError

    monkeypatch.setattr(mp, "_load_lstm", lambda t: True)
    monkeypatch.setattr(
        mp,
        "_lstm_registry",
        {mp._model_registry_key("SPY", "1c"): (None, {"mask_5m": [], "mask_1m": [], "mask_conf": []})},
    )
    db = object()
    with pytest.raises(LstmSequenceInputError, match="as_of_ts"):
        mp._predict_lstm("SPY", db, inference_snapshot_v1={"features": {}})


def test_predict_transformer_requires_as_of_ts_in_inference(monkeypatch) -> None:
    import ml_predict as mp
    from features.lstm_sequence_input import TransformerSequenceInputError

    monkeypatch.setattr(mp, "_load_transformer", lambda t: True)
    monkeypatch.setattr(
        mp,
        "_trans_registry",
        {mp._model_registry_key("SPY", "1c"): (None, {"seq_len": 20, "feature_mask": []})},
    )
    db = object()
    with pytest.raises(TransformerSequenceInputError, match="as_of_ts"):
        mp._predict_transformer("SPY", db, inference_snapshot_v1=None)
