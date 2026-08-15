"""DATA-PIPELINE-INTEGRITY slice A — lstm_model.InsufficientLstmSamplesError.

The 2026-05-25 incident had 9 tuple-index-out-of-range failures in the
scheduler. Diagnosis: low-data tickers (12-19 RTH days, ~460 rows each)
hit `build_lstm_dataset` -> 0 samples -> X_5m has degenerate shape (0,) ->
compute_feature_masks calls X_5m.shape[2] and raises IndexError.

Fix landed in lstm_model.py:
  - Added InsufficientLstmSamplesError
  - Added _validate_lstm_dataset_shape(dataset, ticker)
  - train_lstm calls the validator immediately after build_lstm_dataset

These tests lock the validator contract on synthetic LSTMDataset-shaped
inputs so the scheduler's clean error path can't regress to the
IndexError silently.

Per AGENTS No-new-files: new test file is allowed (new topic — existing
tests/test_lstm_*.py own sequence-input shape and MVP merge; none owns
the train_lstm dataset-shape validator).
"""

from __future__ import annotations

import numpy as np
import pytest

from lstm_model import (
    InsufficientLstmSamplesError,
    _validate_lstm_dataset_shape,
)


class _MiniDataset:
    """Minimal LSTMDataset-shaped object for the validator (the real
    LSTMDataset has many fields; we only test the ones the validator reads)."""

    def __init__(self, *, X_5m=None, y=None, n_samples=None, n_days=0):
        self.X_5m = X_5m
        self.y = y if y is not None else np.array([])
        self.n_samples = (
            n_samples if n_samples is not None else (len(y) if y is not None else 0)
        )
        self.n_days = n_days


def test_validator_passes_on_valid_3d_dataset() -> None:
    """Real-shape dataset (small but valid) passes the gate."""
    ds = _MiniDataset(
        X_5m=np.zeros((10, 60, 23), dtype=np.float32),
        y=np.array([0, 1, 2, 0, 1, 2, 0, 1, 2, 0]),
        n_days=5,
    )
    # Valid shape -> returns None (raises on bad shape).
    assert _validate_lstm_dataset_shape(ds, ticker="SPY") is None


def test_validator_raises_on_zero_samples() -> None:
    """n_samples == 0 (the AEIS-class case): clean exception with row/day info."""
    ds = _MiniDataset(X_5m=np.zeros((0, 60, 23)), y=np.array([]), n_samples=0, n_days=16)
    with pytest.raises(InsufficientLstmSamplesError) as ei:
        _validate_lstm_dataset_shape(ds, ticker="AEIS")
    msg = str(ei.value)
    assert "AEIS" in msg
    assert "0 samples" in msg
    assert "n_days=16" in msg


def test_validator_raises_on_degenerate_x5m_shape() -> None:
    """X_5m with ndim<3 (the actual incident shape): clean exception names
    the shape so the operator can see why."""
    ds = _MiniDataset(
        X_5m=np.array([], dtype=np.float32),  # ndim=1, shape=(0,)
        y=np.array([0, 1]),  # nonzero so the n_samples branch doesn't fire first
        n_samples=2,
        n_days=12,
    )
    with pytest.raises(InsufficientLstmSamplesError) as ei:
        _validate_lstm_dataset_shape(ds, ticker="CRWD")
    msg = str(ei.value)
    assert "CRWD" in msg
    assert "degenerate" in msg.lower() or "shape" in msg.lower()
    assert "ndim=1" in msg


def test_validator_raises_on_missing_x5m_attribute() -> None:
    """If dataset has no X_5m at all (catastrophic build failure), still
    raise InsufficientLstmSamplesError — never let the downstream
    AttributeError leak past the gate."""

    class _NoX5m:
        n_samples = 5
        n_days = 16
        y = np.array([0, 1, 2, 0, 1])
        X_5m = None

    with pytest.raises(InsufficientLstmSamplesError) as ei:
        _validate_lstm_dataset_shape(_NoX5m(), ticker="PSCI")
    assert "PSCI" in str(ei.value)


def test_validator_message_omits_ticker_when_not_passed() -> None:
    """Optional ticker kwarg: error message stays clean when ticker is None."""
    ds = _MiniDataset(X_5m=np.zeros((0, 60, 23)), n_samples=0, n_days=0)
    with pytest.raises(InsufficientLstmSamplesError) as ei:
        _validate_lstm_dataset_shape(ds)
    # No ticker name in the message
    assert "for ticker" not in str(ei.value)


def test_validator_is_called_from_train_lstm_source() -> None:
    """Source lock: train_lstm must call _validate_lstm_dataset_shape after
    build_lstm_dataset and BEFORE compute_feature_masks. A future refactor
    that drops the validator would re-introduce the IndexError class of
    failure silently."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "lstm_model.py").read_text(encoding="utf-8")
    # Find train_lstm function body and assert validator call is inside it.
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "train_lstm":
            body_text = ast.unparse(node)
            assert "_validate_lstm_dataset_shape(" in body_text, (
                "train_lstm must call _validate_lstm_dataset_shape() to prevent "
                "the tuple-index regression class"
            )
            return
    raise AssertionError("train_lstm function not found in lstm_model.py")
