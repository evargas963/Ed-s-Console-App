"""Post-fusion MC adjustment: argmax preservation and simple invariants."""
from __future__ import annotations

import math
from types import SimpleNamespace

from bayesian_fusion import FusionPayload
from mc_fusion_adjustment import apply_mc_adjustment, fuse_payload_apply_mc_adjustment, normalize_mc


from numeric_contract import direction_from_normalized_triplet


def _argmax3(u: float, d: float, f: float) -> str:
    return direction_from_normalized_triplet(u, d, f)


def test_normalize_mc_clips():
    n = normalize_mc(
        {"expected_move": 10, "volatility": 5, "skew": 5, "tail_risk": 2, "directional_bias": 2},
        spot_price=100.0,
    )
    assert n["mc_skew"] == 3.0
    assert n["mc_tail_risk"] == 1.0
    assert n["mc_bias"] == 1.0
    assert math.isclose(n["mc_expected_move"], 0.1)
    assert math.isclose(n["mc_volatility"], 0.05)


def test_apply_mc_adjustment_preserves_argmax_up():
    base = (0.55, 0.25, 0.20)
    mc = normalize_mc(
        {"expected_move": 2, "volatility": 8, "skew": 0.5, "tail_risk": 0.3, "directional_bias": 0.02},
        100.0,
    )
    u, d, f = apply_mc_adjustment(base, mc)
    assert _argmax3(u, d, f) == _argmax3(*base)
    assert abs(u + d + f - 1.0) < 1e-5
    assert min(u, d, f) >= -1e-9
    assert max(u, d, f) <= 1.0 + 1e-9


def test_fuse_payload_mc_audit_carries_mc_feature_source_from_bundle():
    fus = FusionPayload(available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    mc = SimpleNamespace(
        available=True,
        mc_feature_dict=lambda: {
            "expected_move": 1.0,
            "volatility": 2.0,
            "skew": 0.0,
            "tail_risk": 0.1,
            "directional_bias": 0.0,
            "source": "derived_mc_normalized",
        },
    )
    out = fuse_payload_apply_mc_adjustment(fus, mc, 100.0)
    assert out is not None and out.mc_post_fusion_audit is not None
    assert out.mc_post_fusion_audit.get("mc_feature_source") == "derived_mc_normalized"


def test_apply_mc_adjustment_preserves_argmax_flat():
    base = (0.2, 0.2, 0.6)
    mc = normalize_mc(
        {"expected_move": 1, "volatility": 20, "skew": -1, "tail_risk": 0.8, "directional_bias": -0.02},
        100.0,
    )
    u, d, f = apply_mc_adjustment(base, mc)
    assert _argmax3(u, d, f) == _argmax3(*base)
