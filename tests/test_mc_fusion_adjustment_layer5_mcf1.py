"""Layer 5 FIND-MCF1: degenerate _triplet fail-closed (no silent 1/3 fabrication)."""

from __future__ import annotations

import math

from mc_fusion_adjustment import _triplet, apply_mc_adjustment, fuse_payload_apply_mc_adjustment, normalize_mc


def test_triplet_none_on_all_zero():
    assert _triplet((0.0, 0.0, 0.0)) is None


def test_triplet_none_on_nan_component():
    assert _triplet((float("nan"), 0.5, 0.5)) is None


def test_triplet_none_on_negative_sum():
    assert _triplet((-0.5, -0.3, -0.2)) is None


def test_triplet_valid_renormalize():
    tri = _triplet((0.55, 0.25, 0.20))
    assert tri is not None
    u, d, f = tri
    assert math.isclose(u, 0.55)
    assert math.isclose(d, 0.25)
    assert math.isclose(f, 0.20)


def test_apply_mc_adjustment_passthrough_on_degenerate_input():
    base = (0.0, 0.0, 0.0)
    mc = normalize_mc(
        {
            "expected_move": 2.0,
            "volatility": 8.0,
            "skew": 0.5,
            "tail_risk": 0.3,
            "directional_bias": 0.02,
        },
        100.0,
    )
    assert mc is not None
    out = apply_mc_adjustment(base, mc)
    assert out == base


def test_apply_mc_adjustment_proceeds_on_valid_triplet():
    base = (0.55, 0.25, 0.20)
    mc = normalize_mc(
        {
            "expected_move": 2.0,
            "volatility": 8.0,
            "skew": 0.5,
            "tail_risk": 0.3,
            "directional_bias": 0.02,
        },
        100.0,
    )
    assert mc is not None
    out = apply_mc_adjustment(base, mc)
    assert math.isclose(sum(out), 1.0, rel_tol=1e-5)
    assert max(out) == out[0]  # argmax preserved (up)


def test_fuse_payload_skips_non_finite_triplet():
    from types import SimpleNamespace

    fusion = SimpleNamespace(available=True, prob_up=float("nan"), prob_down=0.3, prob_flat=0.2)
    mc = SimpleNamespace(
        available=True,
        mc_feature_dict=lambda: {
            "expected_move": 1.0,
            "volatility": 2.0,
            "skew": 0.0,
            "tail_risk": 0.1,
            "directional_bias": 0.0,
        },
    )
    out = fuse_payload_apply_mc_adjustment(fusion, mc, 100.0)
    assert math.isnan(out.prob_up)
