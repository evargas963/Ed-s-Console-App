"""Fusion overlay: InferenceSnapshotV1-only MVP path; no legacy MVP keys on overlay dict."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _valid_inference_v1():
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
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_000.0,
        features=feats,
    )




def test_validate_fusion_rejects_wrong_contract_version():
    from features.fusion_model_input import (
        validate_inference_snapshot_for_fusion_stack,
        FusionModelInputError,
    )

    snap = _valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["feature_contract_version"] = "bogus"
    with pytest.raises(FusionModelInputError, match="feature_contract_version"):
        validate_inference_snapshot_for_fusion_stack(bad)


def test_validate_fusion_rejects_wrong_timeframe():
    from features.fusion_model_input import (
        validate_inference_snapshot_for_fusion_stack,
        FusionModelInputError,
    )

    snap = _valid_inference_v1()
    bad = copy.deepcopy(snap)
    bad["canonical_timeframe"] = "5m"
    with pytest.raises(FusionModelInputError, match="canonical_timeframe"):
        validate_inference_snapshot_for_fusion_stack(bad)

