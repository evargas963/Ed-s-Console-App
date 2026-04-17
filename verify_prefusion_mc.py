#!/usr/bin/env python3
"""
Verification: Monte Carlo runs independently of base-model outputs (parallel runtime).

Proves that monte_carlo.simulate() receives model_prob_up/down/confidence as None —
MC drift/regime/IV path does not depend on XGB/LSTM/Transformer probabilities.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _minimal_inf_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 570.0
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


def main():
    from types import SimpleNamespace
    from unittest.mock import patch, MagicMock

    captured_mc_kwargs = {}
    import monte_carlo

    _real_simulate = monte_carlo.simulate

    def capture_simulate(*args, **kwargs):
        captured_mc_kwargs.clear()
        captured_mc_kwargs.update(kwargs)
        return _real_simulate(*args, **kwargs)

    mock_fusion_output = {
        "xgb": {
            "available": True,
            "prob_up": 0.50,
            "prob_down": 0.25,
            "prob_flat": 0.25,
            "dominant_class": "up",
            "confidence_label": "high",
            "continuation_support": 0.5,
            "reversal_support": 0.25,
        },
        "lstm": {
            "available": True,
            "prob_up": 0.40,
            "prob_down": 0.30,
            "prob_flat": 0.30,
            "dominant_class": "up",
            "confidence_label": "medium",
            "continuation_support": 0.4,
            "reversal_support": 0.30,
        },
        "transformer": {
            "available": True,
            "prob_up": 0.35,
            "prob_down": 0.35,
            "prob_flat": 0.30,
            "dominant_class": "flat",
            "confidence_label": "low",
            "continuation_support": 0.35,
            "reversal_support": 0.35,
        },
    }

    inp = SimpleNamespace(
        ticker="SPY",
        spot=570.0,
        iv_level=0.18,
        call_gamma_wall=575.0,
        put_gamma_wall=565.0,
        em_upper=573.0,
        em_lower=567.0,
    )
    rules = SimpleNamespace(signal="flat")
    regime = SimpleNamespace(primary="unknown", confidence="low")

    from ml_predict import stack_probs_bundle_key

    with patch("ml_predict.run_base_models_once") as mock_rbm:
        mock_rbm.return_value = {
            "fusion": mock_fusion_output,
            "model_outputs": {},
            stack_probs_bundle_key(): None,
            "parallel_runtime": True,
            "stack_schema_version": "1",
        }
        with patch("prediction_engine.build_fusion_model_overlay_for_stack") as mock_snap:
            mock_snap.return_value = {"ticker": "SPY"}
            with patch(
                "features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
                return_value=_minimal_inf_v1(),
            ):
                with patch("monte_carlo.simulate", side_effect=capture_simulate):
                    from signals import _run_model_stack

                    _run_model_stack(inp, rules, regime, db=None, inference_snapshot_v1=_minimal_inf_v1())

    prob_up = captured_mc_kwargs.get("model_prob_up")
    prob_down = captured_mc_kwargs.get("model_prob_down")
    conf = captured_mc_kwargs.get("model_confidence")
    fusion_dom = captured_mc_kwargs.get("fusion_dominant")

    print("=" * 60)
    print("PARALLEL MC INDEPENDENCE VERIFICATION")
    print("=" * 60)
    print(f"model_prob_up     = {prob_up}")
    print(f"model_prob_down   = {prob_down}")
    print(f"model_confidence  = {conf}")
    print(f"fusion_dominant   = {fusion_dom}")
    print("=" * 60)

    assert prob_up is None, "parallel runtime: MC must not receive blended model_prob_up"
    assert prob_down is None, "parallel runtime: MC must not receive blended model_prob_down"
    assert conf is None, "parallel runtime: MC must not receive model_confidence"
    assert fusion_dom is None, "fusion_dominant must be None (Fusion has not run yet)"

    print("\nVERIFIED: Monte Carlo independent of base-model probability blend.")


if __name__ == "__main__":
    main()
