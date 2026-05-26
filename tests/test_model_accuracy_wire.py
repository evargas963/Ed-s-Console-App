"""Pass 5a — model_accuracy writer + throttled wire + reader round-trip.

EdDB.log_model_accuracy is the writer; maybe_log_model_accuracy throttles
by accuracy_pct delta (MODEL_ACCURACY_DEDUP_EPSILON) so the snapshot only
persists when the value meaningfully changes; get_latest_model_accuracy and
get_model_accuracy_history are the readers (consumed by /api/accuracy and
the ops.html model-accuracy panel in Pass 5b).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db import EdDB


def _new_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "model_accuracy.db")


def test_log_model_accuracy_inserts_row(tmp_path: Path) -> None:
    edb = _new_db(tmp_path)
    row_id = edb.log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0, avg_confidence=0.62, ts_utc=1_800_000_000.0,
    )
    assert isinstance(row_id, int) and row_id > 0
    latest = edb.get_latest_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1", horizon="5c",
    )
    assert latest is not None
    assert latest["accuracy_pct"] == 58.0
    assert latest["total_predictions"] == 100
    assert latest["correct_direction"] == 58
    assert latest["avg_confidence"] == 0.62


def test_maybe_log_skips_when_value_unchanged(tmp_path: Path) -> None:
    """Second call with same accuracy_pct (within epsilon) must skip."""
    edb = _new_db(tmp_path)
    edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0, ts_utc=1_800_000_000.0,
    )
    second = edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0, ts_utc=1_800_000_600.0,
    )
    assert second is None
    history = edb.get_model_accuracy_history(
        ticker="SPY", timeframe="1m", model_version="statistical_v1", horizon="5c",
    )
    assert len(history) == 1


def test_maybe_log_writes_when_value_changes(tmp_path: Path) -> None:
    """Accuracy changes (delta >= epsilon) -> new row persisted."""
    edb = _new_db(tmp_path)
    edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0, ts_utc=1_800_000_000.0,
    )
    new_id = edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=110, correct_direction=66,
        accuracy_pct=60.0, ts_utc=1_800_000_600.0,
    )
    assert new_id is not None and new_id > 0
    history = edb.get_model_accuracy_history(
        ticker="SPY", timeframe="1m", model_version="statistical_v1", horizon="5c",
    )
    assert len(history) == 2
    # ordered DESC by ts_utc => newest first
    assert history[0]["accuracy_pct"] == 60.0
    assert history[1]["accuracy_pct"] == 58.0


def test_maybe_log_skips_when_accuracy_is_none(tmp_path: Path) -> None:
    edb = _new_db(tmp_path)
    rid = edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=0, correct_direction=None,
        accuracy_pct=None,
    )
    assert rid is None


def test_maybe_log_epsilon_below_threshold_skips(tmp_path: Path) -> None:
    """Two values within MODEL_ACCURACY_DEDUP_EPSILON => skip the second."""
    edb = _new_db(tmp_path)
    eps = edb.MODEL_ACCURACY_DEDUP_EPSILON
    edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0, ts_utc=1.0,
    )
    rid = edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=101, correct_direction=58,
        accuracy_pct=58.0 + eps / 2,  # below threshold
        ts_utc=2.0,
    )
    assert rid is None


def test_grain_per_horizon_independent(tmp_path: Path) -> None:
    """Each (ticker, timeframe, model_version, horizon) tuple has its own latest row."""
    edb = _new_db(tmp_path)
    edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="1c", total_predictions=100, correct_direction=55,
        accuracy_pct=55.0,
    )
    edb.maybe_log_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", total_predictions=100, correct_direction=58,
        accuracy_pct=58.0,
    )
    h1 = edb.get_latest_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1", horizon="1c",
    )
    h5 = edb.get_latest_model_accuracy(
        ticker="SPY", timeframe="1m", model_version="statistical_v1", horizon="5c",
    )
    assert h1["accuracy_pct"] == 55.0
    assert h5["accuracy_pct"] == 58.0


def test_history_limit_respected(tmp_path: Path) -> None:
    edb = _new_db(tmp_path)
    for i in range(10):
        edb.log_model_accuracy(
            ticker="SPY", timeframe="1m", model_version="statistical_v1",
            horizon="5c", total_predictions=100 + i, correct_direction=58 + i,
            accuracy_pct=58.0 + i * 0.1, ts_utc=1_800_000_000.0 + i,
        )
    history = edb.get_model_accuracy_history(
        ticker="SPY", timeframe="1m", model_version="statistical_v1",
        horizon="5c", limit=3,
    )
    assert len(history) == 3
    # Latest first
    assert history[0]["accuracy_pct"] > history[1]["accuracy_pct"]
