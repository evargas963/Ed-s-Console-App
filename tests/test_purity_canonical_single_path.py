"""Final purity: one MVP truth path — DB adapter, similarity filters, prediction, regime, vol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from features.fusion_model_input import (
    FusionModelInputError,
)


def _minimal_db_row() -> dict:
    return {
        "spot": 450.0,
        "spread": 0.02,
        "zone": "pin_neutral",
        "nearest_above_dist": 1.2,
        "nearest_below_dist": 0.8,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "vwap_dist_pts": 0.1,
        "absorption_score": None,
        "continuation_score": None,
    }




def test_compute_prediction_fail_closed_without_inference_snapshot_when_db():
    from prediction_engine import compute_prediction

    inp = SimpleNamespace(ticker="SPY", timeframe="1m")
    db = MagicMock()
    with pytest.raises(FusionModelInputError):
        compute_prediction(inp, db, inference_snapshot_v1=None)








def test_fusion_model_input_has_single_similarity_filter_chain():
    import inspect
    from features import fusion_model_input as fmi

    src = inspect.getsource(fmi.similar_setup_filters_from_db_snapshot_row)
    assert "build_db_mvp_feature_row" in src
    assert "similar_setup_filters_from_canonical_features" in src
