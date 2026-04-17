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


def test_fusion_overlay_from_stack_has_no_mvp_keys():
    from prediction_engine import build_fusion_model_overlay_for_stack
    from features.xgb_model_input import MVP_LEGACY_KEYS

    class Ctx(dict):
        def __getattr__(self, k):
            return self.get(k)

    inp = Ctx(
        ticker="SPY",
        timeframe="1m",
        spot=999.0,
        et_hour=10,
        et_minute=30,
        zone="should_not_appear",
        vwap_side="below",
        nearest_above_dist=99.0,
        nearest_below_dist=-99.0,
        candle_body_pts=0.1,
        candle_range_pts=0.2,
        zone_since_bars=1,
        dist_call_gamma_wall=1.0,
        dist_put_gamma_wall=-1.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        pin_width_pts=1.0,
        net_delta=0.0,
        net_vanna=None,
        charm_net=None,
        iv_level=0.2,
        put_call_oi_ratio=1.0,
        spy_chg_pct=0.0,
        qqq_chg_pct=0.0,
        iwm_chg_pct=0.0,
        spy_weighted_push=None,
        iwm_weighted_push=None,
        vix_level=18.0,
        vix_vs_prev=None,
        prev_zone=None,
        candle_direction=None,
        session_bucket=None,
        vix_bucket=None,
        charm_direction=None,
        charm_magnitude=None,
        iv_direction=None,
        qqq_vs_spy=None,
        iwm_risk_signal=None,
        candle_volume=None,
        bid_ask_imbalance=None,
        combined_signal=None,
        combined_conviction=None,
        atr=None,
        iv_rank=None,
        smart_money_score=None,
        breakout_score=None,
        pin_score=None,
    )

    inf = _valid_inference_v1()
    out = build_fusion_model_overlay_for_stack(inp, None, None, inference_snapshot_v1=inf)
    for k in MVP_LEGACY_KEYS:
        assert k not in out, k


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


def test_assert_blocks_mvp_injection():
    from features.fusion_model_input import assert_fusion_overlay_has_no_mvp_keys, FusionModelInputError

    with pytest.raises(FusionModelInputError, match="spot"):
        assert_fusion_overlay_has_no_mvp_keys({"ticker": "SPY", "spot": 1.0})