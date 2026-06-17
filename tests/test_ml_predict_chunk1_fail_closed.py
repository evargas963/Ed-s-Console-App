"""ml_predict chunk-1: I-01 contracts for triplet withholding and inference_snapshot gate."""

from __future__ import annotations

import pytest

from ml_predict import (
    _model_probs_to_fusion_out,
    _require_direction_probability_triplet,
    run_unified_stack_ml_once,
)


def test_require_direction_probability_triplet_withholds_incomplete():
    assert _require_direction_probability_triplet(None) is None
    assert _require_direction_probability_triplet({"up": 0.5, "down": 0.3}) is None
    tri = _require_direction_probability_triplet({"up": 0.5, "down": 0.3, "flat": 0.2})
    assert tri == (0.5, 0.3, 0.2)


def test_model_probs_to_fusion_out_none_when_triplet_incomplete():
    assert _model_probs_to_fusion_out({"up": 0.6}, "long") is None


def test_run_unified_stack_ml_once_requires_inference_snapshot_v1():
    with pytest.raises(ValueError, match="inference_snapshot_v1"):
        run_unified_stack_ml_once({"ticker": "SPY"}, "SPY", None, "wait")
