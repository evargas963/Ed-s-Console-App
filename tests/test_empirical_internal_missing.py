"""Issue 6 — insufficient empirical horizons: internal pred_* must be None, not synthetic neutral."""
from __future__ import annotations

import prediction_engine as pe
from prediction_engine import build_fusion_model_overlay_for_stack
from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
from features.canonical_contract import get_mvp_feature_names


def test_eff_probs_helper_removed():
    assert not hasattr(pe, "_eff_probs")


def test_tri_probs_none_triple():
    assert pe._tri_probs(None) == (None, None, None)


def test_build_ml_snapshot_null_pred_when_similar_set_too_small():
    """Few labeled rows ⇒ _literal returns None ⇒ snapshot pred_* are None (not 0.33)."""

    class Ctx(dict):
        def __getattr__(self, k):
            return self.get(k)

        def __setattr__(self, k, v):
            self[k] = v

    tiny_similar = [
        {
            "outcome_1c": "up",
            "outcome_3c": "up",
            "outcome_5c": "flat",
            "outcome_8c": "up",
            "outcome_13c": "up",
            "outcome_15c": "down",
            "outcome_60c": "flat",
            "ts_utc": 1_700_000_000.0 + float(i),
        }
        for i in range(5)
    ]

    class FakeDB:
        def get_similar_setups(self, **kwargs):
            return tiny_similar

    inp = Ctx(
        ticker="SPY",
        timeframe="1m",
        spot=450.0,
        et_hour=10,
        et_minute=30,
        zone="pin_neutral",
        vwap_side="above",
        candle_body_pts=0.1,
        candle_range_pts=0.2,
        vwap_dist_pts=0.0,
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
    )

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 450.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = 1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.0
    inf = build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_000.0,
        features=feats,
    )
    snap = build_fusion_model_overlay_for_stack(
        inp, FakeDB(), rules=None, inference_snapshot_v1=inf
    )  # type: ignore[arg-type]
    assert snap["pred_5c_up_prob"] is None
    assert snap["pred_5c_down_prob"] is None
    assert snap["pred_5c_flat_prob"] is None
    for k in (
        "pred_1c_up_prob",
        "pred_3c_up_prob",
        "pred_8c_up_prob",
        "pred_13c_up_prob",
        "pred_15c_up_prob",
        "pred_60c_up_prob",
    ):
        assert snap[k] is None, k
