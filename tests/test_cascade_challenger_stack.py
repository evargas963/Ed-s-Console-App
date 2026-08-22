"""Cascade challenger path: staged upstream features, lineage, parallel default unchanged."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
    feats["liquidity.range_imbalance_stall_score"] = None
    feats["liquidity.range_imbalance_push_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_000.0,
        features=feats,
    )


def test_infer_architecture_default_is_parallel():
    import ml_predict as mp

    assert mp._INFER_ARCHITECTURE.get() == "parallel"


def test_cascade_scope_restores_parallel():
    import ml_predict as mp

    with mp._cascade_challenger_inference_scope():
        assert mp._INFER_ARCHITECTURE.get() == "cascade"
    assert mp._INFER_ARCHITECTURE.get() == "parallel"


def test_run_cascade_models_once_stage_order_and_upstream_tensors():
    import ml_predict as mp
    from features.cascade_stack_contract import CASCADE_UPSTREAM_BUNDLE_VERSION

    snap = {"ticker": "SPY", "et_hour": 10}
    inf = _minimal_inf_v1()
    lstm_calls = {}
    tr_calls = {}

    def lstm(*a, **k):
        lstm_calls.update(k)
        return {"up": 0.34, "down": 0.33, "flat": 0.33}

    def tr(*a, **k):
        tr_calls.update(k)
        return {"up": 0.33, "down": 0.34, "flat": 0.33}

    with patch.object(mp, "_predict_xgb", return_value={"up": 0.35, "down": 0.32, "flat": 0.33}), patch.object(
        mp, "_predict_lstm", side_effect=lstm
    ), patch.object(mp, "_predict_transformer", side_effect=tr), patch.object(mp, "_load_meta", return_value=False), patch.object(
        mp, "_weighted_average", return_value={"up": 0.34, "down": 0.33, "flat": 0.33}
    ):
        out = mp.run_cascade_models_once(snap, "SPY", None, "wait", inference_snapshot_v1=inf)

    assert out["architecture"] == "cascade"
    assert out["schema_version"] == "1"
    assert out["upstream_bundle_version"] == CASCADE_UPSTREAM_BUNDLE_VERSION
    assert out["parallel_runtime"] is False
    assert lstm_calls.get("parallel_runtime") is False
    xg = lstm_calls.get("xgb_probs_arr")
    assert xg is not None and len(xg) == 3
    assert tr_calls.get("parallel_runtime") is False
    assert tr_calls.get("xgb_probs_arr") is not None
    assert tr_calls.get("lstm_probs_arr") is not None
    assert "1_xgb" in out["stages"] and "2_lstm" in out["stages"] and "3_transformer" in out["stages"]
    assert len(out["stages"]["2_lstm"]["cascade_inputs_from_xgb_probs"]) == 3
    assert len(out["stages"]["3_transformer"]["cascade_inputs_from_xgb_probs"]) == 3
    assert len(out["stages"]["3_transformer"]["cascade_inputs_from_lstm_probs"]) == 3


def test_run_unified_stack_ml_once_stays_parallel_and_does_not_set_cascade_arch():
    import ml_predict as mp

    with patch.object(mp, "_predict_xgb", return_value={"up": 0.3, "down": 0.3, "flat": 0.4}), patch.object(
        mp, "_predict_lstm", return_value={"up": 0.3, "down": 0.3, "flat": 0.4}
    ), patch.object(mp, "_predict_transformer", return_value={"up": 0.3, "down": 0.3, "flat": 0.4}), patch.object(
        mp, "_predict_xgb_movement_heads", return_value={}
    ), patch.object(
        mp, "_load_meta", return_value=False
    ):
        o = mp.run_unified_stack_ml_once({"ticker": "SPY"}, "SPY", None, inference_snapshot_v1=_minimal_inf_v1())
    assert o.get("parallel_runtime") is True
    assert mp._INFER_ARCHITECTURE.get() == "parallel"


def test_lineage_fingerprint_mismatch_fails():
    from features.cascade_stack_contract import CascadeLineageError

    with pytest.raises(CascadeLineageError, match="data_fingerprint"):
        from ml_predict import run_cascade_models_once

        run_cascade_models_once(
            {"ticker": "SPY"},
            "SPY",
            None,
            inference_snapshot_v1=_minimal_inf_v1(),
            expected_data_fingerprint="abc",
            actual_data_fingerprint="xyz",
        )


def test_fusion_overlay_mvp_rejected():
    from features.cascade_stack_contract import CascadeChallengerError

    with pytest.raises(CascadeChallengerError, match="legacy MVP"):
        from ml_predict import run_cascade_models_once

        run_cascade_models_once(
            {"ticker": "SPY", "spot": 1.0},
            "SPY",
            None,
            inference_snapshot_v1=_minimal_inf_v1(),
        )


def test_scheduler_train_cascade_uses_same_feature_cache_key_family():
    """train_cascade_candidate uses compute_feature_cache_key / feature_cache_dir like parallel."""
    text = (ROOT / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "def train_cascade_candidate" in text
    assert "compute_feature_cache_key" in text and "feature_cache_dir" in text
