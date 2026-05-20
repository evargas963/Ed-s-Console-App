"""
XGBoost tabular path: InferenceSnapshotV1-only MVP fields + fusion overlay for non-MVP keys.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_valid_inference_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 450.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_bull"
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


def test_engineering_snapshot_maps_only_canonical_features():
    from features.xgb_model_input import inference_snapshot_v1_to_engineering_snapshot

    snap = _minimal_valid_inference_v1()
    tab = inference_snapshot_v1_to_engineering_snapshot(snap)
    assert tab["spot"] == 450.0
    assert tab["zone"] == "pin_bull"
    assert tab["vwap_side"] == "above"
    assert "liquidity_summary" not in tab


def test_merge_overlay_does_not_override_mvp_columns():
    from features.xgb_model_input import (
        inference_snapshot_v1_to_engineering_snapshot,
        merge_xgb_fusion_overlay,
    )

    snap = _minimal_valid_inference_v1()
    base = inference_snapshot_v1_to_engineering_snapshot(snap)
    poisoned = merge_xgb_fusion_overlay(
        base,
        {"spot": 1.0, "zone": "breakdown", "pred_1c_up_prob": 0.4},
    )
    assert poisoned["spot"] == 450.0
    assert poisoned["zone"] == "pin_bull"
    assert poisoned["pred_1c_up_prob"] == 0.4


def test_validate_rejects_wrong_contract_version():
    from features.xgb_model_input import validate_inference_snapshot_v1_for_xgb, XgbInferenceInputError

    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["feature_contract_version"] = "bogus"
    with pytest.raises(XgbInferenceInputError, match="feature_contract_version"):
        validate_inference_snapshot_v1_for_xgb(bad)


def test_validate_rejects_wrong_timeframe():
    from features.xgb_model_input import validate_inference_snapshot_v1_for_xgb, XgbInferenceInputError

    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["canonical_timeframe"] = "5m"
    with pytest.raises(XgbInferenceInputError, match="canonical_timeframe"):
        validate_inference_snapshot_v1_for_xgb(bad)


def test_validate_rejects_missing_spot_for_xgb():
    from features.xgb_model_input import validate_inference_snapshot_v1_for_xgb, XgbInferenceInputError
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spread_pts"] = 0.02
    snap = build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1.0,
        features=feats,
    )
    with pytest.raises(XgbInferenceInputError, match="price.spot"):
        validate_inference_snapshot_v1_for_xgb(snap)


def test_raw_l1_payload_rejected_at_guard():
    from features.xgb_model_input import assert_not_raw_l1_payload, XgbInferenceInputError

    with pytest.raises(XgbInferenceInputError, match="liquidity_summary"):
        assert_not_raw_l1_payload({"liquidity_summary": {"absorption_score": 1.0}})


def test_run_base_models_once_requires_inference_snapshot_v1():
    from ml_predict import run_base_models_once

    with pytest.raises(ValueError, match="inference_snapshot_v1"):
        run_base_models_once({"ticker": "SPY"}, "SPY", None, "wait")


def test_build_xgb_pre_engineering_snapshot_matches_manual_pipeline():
    from features.xgb_model_input import (
        inference_snapshot_v1_to_engineering_snapshot,
        merge_xgb_fusion_overlay,
    )
    from ml_data_common import snapshot_with_m5_additive
    from ml_train import DB_PATH as _ML_DB
    from ml_predict import build_xgb_pre_engineering_snapshot_for_tick

    snap = _minimal_valid_inference_v1()
    overlay = {"et_hour": 10, "et_minute": 30}
    built = build_xgb_pre_engineering_snapshot_for_tick(snap, overlay)
    base = inference_snapshot_v1_to_engineering_snapshot(snap)
    merged = merge_xgb_fusion_overlay(base, overlay)
    manual = snapshot_with_m5_additive(merged, _ML_DB)
    assert built == manual


def test_predict_xgb_pre_engineering_snapshot_matches_inline(monkeypatch):
    """Optional pre-snapshot must yield identical probs when model loads."""
    import ml_predict as mp
    from ml_predict import _predict_xgb, build_xgb_pre_engineering_snapshot_for_tick

    snap = _minimal_valid_inference_v1()
    overlay = {"ticker": "SPY", "et_hour": 10}
    pre = build_xgb_pre_engineering_snapshot_for_tick(snap, overlay)

    monkeypatch.setattr(mp, "_load_xgb", lambda t: True)
    monkeypatch.setattr(
        mp,
        "_xgb_registry",
        {
            mp._model_registry_key("SPY"): {
                "model": type(
                    "M",
                    (),
                    {
                        "predict_proba": lambda self, x: [[0.2, 0.3, 0.5]],
                        "n_features_in_": 1,
                    },
                )(),
                "meta": {"impute_medians": {}, "features": ["f0"]},
                "feature_names": ["f0"],
                "category_maps": {},
                "vol_medians": {},
            }
        },
    )

    def fake_eng_single(**kwargs):
        import pandas as pd

        return pd.DataFrame([[1.0]], columns=["f0"])

    monkeypatch.setattr("ml_train.engineer_single_snapshot", fake_eng_single)

    a = _predict_xgb(snap, "SPY", fusion_feature_overlay=overlay)
    b = _predict_xgb(
        snap,
        "SPY",
        fusion_feature_overlay=overlay,
        xgb_pre_engineering_snapshot=pre,
    )
    assert a == b


def test_xgb_path_accepts_valid_inference_snapshot_v1(monkeypatch):
    """Model load is skipped; we only assert the input contract is accepted before registry check."""
    from ml_predict import _predict_xgb
    import ml_predict as mp

    monkeypatch.setattr(mp, "_load_xgb", lambda t: False)

    snap = _minimal_valid_inference_v1()
    assert _predict_xgb(snap, "SPY", fusion_feature_overlay={"et_hour": 10, "et_minute": 30}) is None


def test_build_inference_snapshot_v1_from_signal_input_uses_adapter_only():
    from types import SimpleNamespace

    from features.inference_snapshot import build_inference_snapshot_v1_from_signal_input

    inp = SimpleNamespace(
        ticker="SPY",
        expiry=None,
        spot=400.0,
        spread=0.02,
        zone="pin_bull",
        nearest_above_dist=1.0,
        nearest_below_dist=-1.0,
        net_gamma=0.0,
        vwap_side="above",
        vwap_dist_pts=0.5,
    )
    snap = build_inference_snapshot_v1_from_signal_input(inp, as_of_ts=1_700_000_000.0)
    assert snap["snapshot_type"] == "InferenceSnapshotV1"
    assert snap["features"]["price.spot"] == 400.0
    assert snap["features"]["price.spread_pts"] == 0.02


def test_build_inference_snapshot_v1_from_signal_input_does_not_fabricate_as_of_ts():
    from types import SimpleNamespace

    from features.inference_snapshot import build_inference_snapshot_v1_from_signal_input

    inp = SimpleNamespace(
        ticker="SPY",
        expiry=None,
        refresh_ts_utc=None,
        spot=400.0,
        spread=0.01,
        zone="pin_neutral",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        net_gamma=100.0,
        vwap_side="above",
        vwap_dist_pts=0.5,
    )

    snap = build_inference_snapshot_v1_from_signal_input(inp)

    assert snap["as_of_ts"] is None

