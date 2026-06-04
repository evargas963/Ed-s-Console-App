"""Final purity: one MVP truth path — DB adapter, similarity filters, prediction, regime, vol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from features.fusion_model_input import (
    FusionModelInputError,
    similar_setup_filters_from_canonical_features,
    similar_setup_filters_from_db_snapshot_row,
)
from features.inference_snapshot import build_inference_snapshot_v1_from_db_row


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


def test_similarity_filters_db_adapter_matches_inference_snapshot_from_same_row():
    """Replay/production alignment: DB row → canonical → filters == snapshot features → filters."""
    row = _minimal_db_row()
    a = similar_setup_filters_from_db_snapshot_row(row)
    snap = build_inference_snapshot_v1_from_db_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, db_row=row
    )
    b = similar_setup_filters_from_canonical_features(snap["features"])
    assert a == b


def test_compute_prediction_fail_closed_without_inference_snapshot_when_db():
    from prediction_engine import compute_prediction

    inp = SimpleNamespace(ticker="SPY", timeframe="1m")
    db = MagicMock()
    with pytest.raises(FusionModelInputError):
        compute_prediction(inp, db, inference_snapshot_v1=None)


def test_classify_regime_requires_mvp_dict():
    from regime_engine import classify_regime
    from features.regime_mvp_context import RegimeMvpInputError

    inp = SimpleNamespace()
    rules = MagicMock()
    rules.micro = None
    rules.signal = "wait"
    rules.conviction = "low"
    with pytest.raises(RegimeMvpInputError):
        classify_regime(inp, rules, mvp_features=None)  # type: ignore[arg-type]


def test_classify_volatility_regime_requires_positive_canonical_spot():
    from volatility_regime import classify_volatility_regime
    from features.regime_mvp_context import RegimeMvpInputError
    from features.canonical_contract import get_mvp_feature_names

    inp = SimpleNamespace(
        realized_vol=None,
        atr=None,
        iv_level=None,
        vix_level=None,
        vix_vs_prev=None,
        iv_direction=None,
        garch_sigma_bars=None,
    )
    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = None
    with pytest.raises(RegimeMvpInputError):
        classify_volatility_regime(inp, mvp_features=feats)


def test_monte_carlo_resolve_uses_canonical_spot_only():
    from features.monte_carlo_stack_input import resolve_monte_carlo_stack_inputs
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 100.0
    snap = {
        "snapshot_type": "inference_snapshot_v1",
        "feature_contract_version": "v1_1m_mvp",
        "canonical_timeframe": "1m",
        "features": feats,
    }
    inp = SimpleNamespace(spot=100.0, call_gamma_wall=1.0, put_gamma_wall=1.0, em_upper=110.0, em_lower=90.0)
    out = resolve_monte_carlo_stack_inputs(inp, snap)
    assert out["spot"] == 100.0


def test_fusion_model_input_has_single_similarity_filter_chain():
    import inspect
    from features import fusion_model_input as fmi

    src = inspect.getsource(fmi.similar_setup_filters_from_db_snapshot_row)
    assert "build_db_mvp_feature_row" in src
    assert "similar_setup_filters_from_canonical_features" in src
