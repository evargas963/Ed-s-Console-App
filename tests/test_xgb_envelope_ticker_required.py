"""FIND-XGB1/XGB2: InferenceSnapshotV1 envelope requires ticker + as_of_ts."""

from __future__ import annotations

import copy

import pytest

from features.canonical_contract import get_mvp_feature_names
from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
from features.xgb_model_input import (
    XgbInferenceInputError,
    inference_snapshot_v1_to_engineering_snapshot,
    validate_inference_snapshot_v1_envelope,
)


def _valid_snap(*, ticker="SPY", as_of_ts=1_700_000_000.0):
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
        ticker=ticker,
        expiry=None,
        as_of_ts=as_of_ts,
        features=feats,
    )


def test_envelope_rejects_missing_ticker():
    snap = _valid_snap()
    bad = copy.deepcopy(snap)
    del bad["ticker"]
    with pytest.raises(XgbInferenceInputError, match="non-empty ticker"):
        validate_inference_snapshot_v1_envelope(bad)


def test_envelope_rejects_empty_ticker():
    snap = _valid_snap(ticker="   ")
    with pytest.raises(XgbInferenceInputError, match="non-empty ticker"):
        validate_inference_snapshot_v1_envelope(snap)


def test_envelope_rejects_missing_as_of_ts():
    snap = _valid_snap(as_of_ts=None)
    with pytest.raises(XgbInferenceInputError, match="missing as_of_ts"):
        validate_inference_snapshot_v1_envelope(snap)


def test_envelope_rejects_non_numeric_as_of_ts():
    snap = _valid_snap()
    bad = copy.deepcopy(snap)
    bad["as_of_ts"] = "not-a-ts"
    with pytest.raises(XgbInferenceInputError, match="as_of_ts not numeric"):
        validate_inference_snapshot_v1_envelope(bad)


def test_engineering_snapshot_always_emits_time_keys():
    tab = inference_snapshot_v1_to_engineering_snapshot(_valid_snap())
    assert tab["ticker"] == "SPY"
    assert "ts_utc" in tab
    assert "et_hour" in tab
    assert "et_minute" in tab
