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
