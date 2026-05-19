"""Layer 5 xgb_model_input chunk-1: lock strict-validation + overlay + guardrail contracts."""

from __future__ import annotations

import copy

import pytest

from features.canonical_contract import (
    CANONICAL_FEATURE_CONTRACT_VERSION,
    CANONICAL_FEATURE_TIMEFRAME,
    INFERENCE_SNAPSHOT_TYPE,
)
from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
from features.canonical_contract import get_mvp_feature_names
from features.xgb_model_input import (
    XgbInferenceInputError,
    assert_not_raw_l1_payload,
    inference_snapshot_v1_to_engineering_snapshot,
    merge_xgb_fusion_overlay,
    validate_inference_snapshot_v1_envelope,
    validate_inference_snapshot_v1_for_xgb,
)


def _minimal_valid_inference_v1(*, as_of_ts: float | None = 1_700_000_000.0):
    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 450.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_bull"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=as_of_ts,
        features=feats,
    )


def test_envelope_rejects_non_dict():
    with pytest.raises(XgbInferenceInputError, match="must be a dict"):
        validate_inference_snapshot_v1_envelope("not a dict")


def test_envelope_rejects_wrong_snapshot_type():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["snapshot_type"] = "WrongType"
    with pytest.raises(XgbInferenceInputError, match="snapshot_type"):
        validate_inference_snapshot_v1_envelope(bad)


def test_envelope_rejects_wrong_contract_version():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["feature_contract_version"] = "bogus"
    with pytest.raises(XgbInferenceInputError, match="feature_contract_version"):
        validate_inference_snapshot_v1_envelope(bad)


def test_envelope_rejects_wrong_timeframe():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["canonical_timeframe"] = "5m"
    with pytest.raises(XgbInferenceInputError, match="canonical_timeframe"):
        validate_inference_snapshot_v1_envelope(bad)


def test_envelope_rejects_missing_features_dict():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["features"] = None
    with pytest.raises(XgbInferenceInputError, match="missing features dict"):
        validate_inference_snapshot_v1_envelope(bad)


def test_envelope_rejects_invalid_feature_row():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["features"] = dict(bad["features"])
    bad["features"]["price.spot"] = True
    with pytest.raises(XgbInferenceInputError, match="invalid canonical feature row"):
        validate_inference_snapshot_v1_envelope(bad)


def test_for_xgb_rejects_missing_spot():
    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spread_pts"] = 0.02
    snap = build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, features=feats
    )
    with pytest.raises(XgbInferenceInputError, match="price.spot"):
        validate_inference_snapshot_v1_for_xgb(snap)


def test_for_xgb_rejects_non_numeric_spot():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["features"] = dict(bad["features"])
    bad["features"]["price.spot"] = "garbage"
    with pytest.raises(XgbInferenceInputError, match="price.spot"):
        validate_inference_snapshot_v1_for_xgb(bad)


def test_for_xgb_rejects_non_positive_spot():
    snap = _minimal_valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["features"] = dict(bad["features"])
    bad["features"]["price.spot"] = 0.0
    with pytest.raises(XgbInferenceInputError, match="> 0"):
        validate_inference_snapshot_v1_for_xgb(bad)


def test_engineering_snapshot_maps_canonical_to_legacy():
    tab = inference_snapshot_v1_to_engineering_snapshot(_minimal_valid_inference_v1())
    assert tab["spot"] == 450.0
    assert tab["zone"] == "pin_bull"
    assert tab["vwap_side"] == "above"
    assert tab["ticker"] == "SPY"


def test_engineering_snapshot_includes_time_keys_when_as_of_ts_present():
    tab = inference_snapshot_v1_to_engineering_snapshot(_minimal_valid_inference_v1())
    assert "ts_utc" in tab
    assert "et_hour" in tab
    assert "et_minute" in tab


def test_engineering_snapshot_omits_time_keys_when_as_of_ts_missing():
    snap = _minimal_valid_inference_v1(as_of_ts=None)
    tab = inference_snapshot_v1_to_engineering_snapshot(snap)
    assert "ts_utc" not in tab
    assert "et_hour" not in tab
    assert "et_minute" not in tab


def test_merge_overlay_empty_returns_base():
    base = {"spot": 450.0}
    assert merge_xgb_fusion_overlay(base, None) == base
    assert merge_xgb_fusion_overlay(base, {}) == base


def test_merge_overlay_skips_mvp_legacy_keys():
    base = inference_snapshot_v1_to_engineering_snapshot(_minimal_valid_inference_v1())
    merged = merge_xgb_fusion_overlay(base, {"spot": 1.0, "zone": "breakdown"})
    assert merged["spot"] == 450.0
    assert merged["zone"] == "pin_bull"


def test_merge_overlay_copies_non_mvp_keys():
    base = inference_snapshot_v1_to_engineering_snapshot(_minimal_valid_inference_v1())
    merged = merge_xgb_fusion_overlay(base, {"pred_1c_up_prob": 0.4})
    assert merged["pred_1c_up_prob"] == 0.4


def test_assert_not_raw_l1_rejects_liquidity_summary_without_features():
    with pytest.raises(XgbInferenceInputError, match="liquidity_summary"):
        assert_not_raw_l1_payload({"liquidity_summary": {"absorption_score": 1.0}})


def test_assert_not_raw_l1_rejects_spot_anchors_without_snapshot_type():
    with pytest.raises(XgbInferenceInputError, match="spot_anchors"):
        assert_not_raw_l1_payload({"spot_anchors": []})


def test_assert_not_raw_l1_passes_valid_inference_snapshot_v1():
    snap = _minimal_valid_inference_v1()
    assert_not_raw_l1_payload(snap)
    assert snap["snapshot_type"] == INFERENCE_SNAPSHOT_TYPE
    assert snap["feature_contract_version"] == CANONICAL_FEATURE_CONTRACT_VERSION
    assert snap["canonical_timeframe"] == CANONICAL_FEATURE_TIMEFRAME
