"""Parallel stack runtime: independent base models, schema, fusion inputs, fail-closed."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_inf_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 450.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    feats["liquidity.absorption_score"] = None
    feats["liquidity.continuation_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_000.0,
        features=feats,
    )


def test_run_base_models_once_invokes_sequence_models_with_parallel_runtime():
    """LSTM/TR must receive parallel_runtime=True and no upstream prob arrays."""
    from ml_predict import run_base_models_once

    snap = {"ticker": "SPY", "et_hour": 10}
    inf = _minimal_inf_v1()
    lstm_kw = {}
    tr_kw = {}

    def cap_lstm(*a, **k):
        lstm_kw.update(k)
        return {"up": 0.34, "down": 0.33, "flat": 0.33}

    def cap_tr(*a, **k):
        tr_kw.update(k)
        return {"up": 0.33, "down": 0.34, "flat": 0.33}

    with patch("ml_predict._predict_xgb", return_value={"up": 0.35, "down": 0.32, "flat": 0.33}), patch(
        "ml_predict._predict_lstm", side_effect=cap_lstm
    ), patch("ml_predict._predict_transformer", side_effect=cap_tr), patch(
        "ml_predict._predict_xgb_movement_heads", return_value={}
    ), patch(
        "ml_predict._load_meta", return_value=False
    ):
        out = run_base_models_once(snap, "SPY", MagicMock(), "wait", inference_snapshot_v1=inf)

    assert lstm_kw.get("parallel_runtime") is True
    assert lstm_kw.get("xgb_probs_arr") is None
    assert tr_kw.get("parallel_runtime") is True
    assert tr_kw.get("xgb_probs_arr") is None
    assert tr_kw.get("lstm_probs_arr") is None
    assert out.get("parallel_runtime") is True
    assert out.get("stack_schema_version") == "1"
    for k in ("xgb", "lstm", "transformer"):
        mo = out["model_outputs"][k]
        assert mo.get("architecture") == "parallel"
        assert mo.get("schema_version") == "1"
        assert "prob_up" in mo and "up" in mo


def test_single_xgb_call_no_nested_xgb_from_sequence_models():
    """Parallel path must not call _predict_xgb from inside LSTM/Transformer."""
    from ml_predict import run_base_models_once

    snap = {"ticker": "SPY"}
    inf = _minimal_inf_v1()
    calls = []

    def xgb(*a, **k):
        calls.append("xgb")
        return {"up": 0.4, "down": 0.3, "flat": 0.3}

    with patch("ml_predict._predict_xgb", side_effect=xgb), patch(
        "ml_predict._predict_lstm", return_value={"up": 0.3, "down": 0.3, "flat": 0.4}
    ), patch("ml_predict._predict_transformer", return_value={"up": 0.3, "down": 0.3, "flat": 0.4}), patch(
        "ml_predict._predict_xgb_movement_heads", return_value={}
    ), patch(
        "ml_predict._load_meta", return_value=False
    ):
        run_base_models_once(snap, "SPY", MagicMock(), "wait", inference_snapshot_v1=inf)

    assert calls.count("xgb") == 1


def test_missing_inference_snapshot_raises():
    from ml_predict import run_base_models_once

    with pytest.raises(ValueError, match="inference_snapshot_v1"):
        run_base_models_once({"ticker": "SPY"}, "SPY", MagicMock(), inference_snapshot_v1=None)


def test_parallel_runtime_artifact_error_is_value_error():
    from ml_predict import ParallelRuntimeArtifactError

    assert issubclass(ParallelRuntimeArtifactError, ValueError)


def test_monte_carlo_receives_resolved_model_probs_for_drift():
    """Monte Carlo simulate receives explicit model_prob_* for path drift (governed stack inputs)."""
    import signals
    from types import SimpleNamespace

    captured = {}

    def fake_simulate(**kwargs):
        captured.update(kwargs)
        from monte_carlo import MonteCarloOutput

        return MonteCarloOutput(available=False)

    inf = SimpleNamespace(
        ticker="SPY",
        timeframe="1m",
        spot=450.0,
        iv_level=0.2,
        call_gamma_wall=450.0,
        put_gamma_wall=448.0,
        em_upper=455.0,
        em_lower=445.0,
        realized_vol=None,
        atr=1.0,
        garch_sigma_bars=None,
    )
    rules = SimpleNamespace(signal="wait", conviction="low")
    regime = SimpleNamespace(primary="unknown", confidence="low")

    with patch(
        "features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
        return_value=_minimal_inf_v1(),
    ), patch(
        "prediction_engine.build_fusion_model_overlay_for_stack",
        return_value={"ticker": "SPY"},
    ), patch("ml_predict.run_base_models_once") as rbm, patch("monte_carlo.simulate", side_effect=fake_simulate):
        rbm.return_value = {
            "fusion": {
                "xgb": {"available": True, "prob_up": 0.4, "prob_down": 0.3, "prob_flat": 0.3},
                "lstm": {"available": True, "prob_up": 0.3, "prob_down": 0.3, "prob_flat": 0.4},
                "transformer": {"available": True, "prob_up": 0.33, "prob_down": 0.33, "prob_flat": 0.34},
            },
            "model_outputs": {},
            "stack_probs_15c": None,
        }
        signals._run_model_stack(inf, rules, regime, db=MagicMock(), inference_snapshot_v1=_minimal_inf_v1())

    assert captured.get("model_prob_up") is not None
    assert captured.get("model_prob_down") is not None
    assert captured.get("model_confidence") is not None


def test_fusion_overlay_rejects_mvp_keys():
    from features.fusion_model_input import FusionModelInputError, assert_fusion_overlay_has_no_mvp_keys

    with pytest.raises(FusionModelInputError):
        assert_fusion_overlay_has_no_mvp_keys({"ticker": "SPY", "spot": 1.0})
