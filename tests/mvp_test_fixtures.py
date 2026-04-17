"""Minimal valid canonical MVP feature rows for unit tests (matches canonical_contract)."""

from __future__ import annotations

from features.canonical_contract import get_mvp_feature_names


def minimal_mvp_features(
    *,
    zone: str = "pin_neutral",
    vwap_side: str = "above",
    spot: float = 450.0,
) -> dict:
    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    feats["price.spread_pts"] = 0.01
    feats["structure.zone"] = zone
    feats["structure.nearest_above_dist"] = 2.0
    feats["structure.nearest_below_dist"] = 2.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = vwap_side
    feats["anchor.vwap_dist_pts"] = 0.0
    feats["liquidity.absorption_score"] = None
    feats["liquidity.continuation_score"] = None
    return feats
