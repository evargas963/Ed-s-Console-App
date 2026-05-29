"""O-55 lock: training sample weighting is EQUAL / UNIFORM ONLY — canonical, no toggle.

Operator decision 2026-05-27: every training row counts equally so models learn across the
full history. There is intentionally NO recency/time-decay weighting and NO runtime switch
(env var or mode arg) to turn it on. These tests are an anti-revert guard — if a future change
reintroduces a decay path or a weighting toggle, this fails.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_equal_sample_weights_are_all_ones():
    from ml_data_common import equal_sample_weights

    w = np.asarray(equal_sample_weights(50))
    assert w.shape == (50,)
    assert np.allclose(w, 1.0)


def test_no_decay_or_toggle_machinery_in_ml_data_common():
    import ml_data_common as m

    # The recency-decay utility and the toggle/resolver must not exist (removed, not dormant).
    for banned in (
        "compute_exponential_weights",
        "resolve_train_sample_weight_mode",
        "training_sample_weights",
        "TRAIN_SAMPLE_WEIGHT_MODE_ENV",
        "CANONICAL_TRAIN_SAMPLE_WEIGHT_MODE",
    ):
        assert not hasattr(m, banned), f"{banned} should be gone (no decay path / no toggle)"
    assert m.TRAIN_SAMPLE_WEIGHT_MODE == "equal"


def test_no_weight_mode_env_override_exists(monkeypatch):
    # Even if a stale env var is set, there is no code path that reads it.
    monkeypatch.setenv("ED_TRAIN_SAMPLE_WEIGHT_MODE", "exp")
    from ml_data_common import equal_sample_weights

    assert np.allclose(np.asarray(equal_sample_weights(20)), 1.0)


def test_trainers_have_no_weight_mode_parameter():
    import lstm_model
    import ml_train
    import transformer_train

    assert "weight_mode" not in inspect.signature(ml_train.train_ticker).parameters
    assert "weight_mode" not in inspect.signature(lstm_model.train_lstm).parameters
    assert "weight_mode" not in inspect.signature(transformer_train.train_transformer).parameters


def test_xgb_compute_sample_weights_removed():
    import ml_train

    # The mode-selecting weight builder (which had the 'exp' branch) is gone.
    assert not hasattr(ml_train, "compute_sample_weights")
