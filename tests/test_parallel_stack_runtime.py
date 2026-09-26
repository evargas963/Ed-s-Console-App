"""Parallel stack runtime: independent ML stack layers, schema, fusion inputs, fail-closed."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


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








def test_parallel_runtime_artifact_error_is_value_error():
    from ml_predict import ParallelRuntimeArtifactError

    assert issubclass(ParallelRuntimeArtifactError, ValueError)


def _drift_priors_captured_for_composition(composition):
    """Run the live stack once; return the kwargs Monte Carlo's simulate() actually received.

    ``composition`` is the ``stack_probs_composition`` record the ML bundle carries (None means the
    producer reported none). Directional conditioning is authorized on COMPOSITION, so that record
    is the ONLY input varied between the two cases below — identical legs, identical stack_probs
    triplet, keyed at the live bundle key.
    """
    import signals
    from types import SimpleNamespace
    from ml_predict import stack_probs_bundle_key

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

    # RC-REHAB-1 (2026-09-22): LIVE_MODEL_STACK_ENABLED now defaults to False (operator
    # directive, legacy live ML/MC stack off by default) -- this helper proves the
    # stack's OWN drift-prior wiring when genuinely running, so it explicitly re-enables
    # it for this call; that behavior is still correct code, just no longer the default.
    with patch.object(signals, "LIVE_MODEL_STACK_ENABLED", True), patch(
        "features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
        return_value=_minimal_inf_v1(),
    ), patch(
        "prediction_engine.build_fusion_model_overlay_for_stack",
        return_value={"ticker": "SPY"},
    ), patch("ml_predict.run_unified_stack_ml_once") as rbm, patch("monte_carlo.simulate", side_effect=fake_simulate):
        rbm.return_value = {
            "fusion": {
                "xgb": {"available": True, "prob_up": 0.4, "prob_down": 0.3, "prob_flat": 0.3},
                "lstm": {"available": True, "prob_up": 0.3, "prob_down": 0.3, "prob_flat": 0.4},
                "transformer": {"available": True, "prob_up": 0.33, "prob_down": 0.33, "prob_flat": 0.34},
            },
            "model_outputs": {},
            # Key at the LIVE bundle key. The former hardcoded "stack_probs_15c" never matched it,
            # so stack_probs was always None here — invisible while the gate authorized on leg shape.
            stack_probs_bundle_key(): {"up": 0.4, "down": 0.35, "flat": 0.25},
            "stack_probs_composition": composition,
        }
        signals._run_model_stack(inf, rules, regime, db=MagicMock(), inference_snapshot_v1=_minimal_inf_v1())

    return captured






