"""Layer 5 fusion_model_input chunk-1: FMI1 guard + gap-fill contract locks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _valid_inference_v1():
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row

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
        as_of_ts=1_700_000_000.0,
        features=feats,
    )


def test_validate_fusion_stack_rejects_non_dict_snapshot():
    from features.fusion_model_input import FusionModelInputError, validate_inference_snapshot_for_fusion_stack

    with pytest.raises(FusionModelInputError, match="must be a dict"):
        validate_inference_snapshot_for_fusion_stack("not a dict")  # type: ignore[arg-type]


def test_strip_mvp_keys_from_fusion_overlay():
    from features.fusion_model_input import strip_mvp_keys_from_fusion_overlay

    out = strip_mvp_keys_from_fusion_overlay({"spot": 1.0, "pred_1c_up_prob": 0.5, "et_hour": 10})
    assert out == {"pred_1c_up_prob": 0.5, "et_hour": 10}


def test_similar_setup_filters_db_row_none_raises_fmi1():
    from features.fusion_model_input import FusionModelInputError, similar_setup_filters_from_db_snapshot_row

    with pytest.raises(FusionModelInputError, match="snapshot_row must be a Mapping"):
        similar_setup_filters_from_db_snapshot_row(None)  # type: ignore[arg-type]


def test_similar_setup_filters_db_row_non_dict_raises_fmi1():
    from features.fusion_model_input import FusionModelInputError, similar_setup_filters_from_db_snapshot_row

    with pytest.raises(FusionModelInputError, match="snapshot_row must be a Mapping"):
        similar_setup_filters_from_db_snapshot_row("not a dict")  # type: ignore[arg-type]


def test_similar_setup_filters_db_row_invalid_value_rewraps_mvp_error():
    from features.fusion_model_input import FusionModelInputError, similar_setup_filters_from_db_snapshot_row

    with pytest.raises(FusionModelInputError, match="cannot be coerced"):
        similar_setup_filters_from_db_snapshot_row({"spot": "garbage"})


def test_similar_setup_filters_canonical_both_fallback_flags():
    from features.fusion_model_input import similar_setup_filters_from_canonical_features

    out = similar_setup_filters_from_canonical_features(
        {
            "structure.zone": None,
            "anchor.vwap_side": None,
            "structure.nearest_above_dist": None,
            "structure.nearest_below_dist": None,
        }
    )
    assert out["zone_fallback"] is True
    assert out["vwap_side_fallback"] is True


def test_assert_fusion_overlay_lists_bad_mvp_keys():
    from features.fusion_model_input import FusionModelInputError, assert_fusion_overlay_has_no_mvp_keys

    with pytest.raises(FusionModelInputError, match="spot"):
        assert_fusion_overlay_has_no_mvp_keys({"spot": 1.0, "zone": "pin_bull", "et_hour": 3})
