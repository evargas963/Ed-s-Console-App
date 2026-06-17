"""mc_fusion_adjustment chunk-1: I-01 fail-closed normalize + no-op when MC incomplete."""

from __future__ import annotations

from types import SimpleNamespace

from mc_fusion_adjustment import apply_mc_adjustment, fuse_payload_apply_mc_adjustment, normalize_mc


def test_normalize_mc_requires_all_five_features():
    full = {
        "expected_move": 2.0,
        "volatility": 1.0,
        "skew": 0.1,
        "tail_risk": 0.2,
        "directional_bias": 0.01,
    }
    assert normalize_mc(full, 100.0) is not None
    assert normalize_mc({"expected_move": 1.0, "volatility": 0.5}, 100.0) is None


def test_apply_mc_adjustment_reverts_when_features_missing():
    base = (0.55, 0.25, 0.20)
    out = apply_mc_adjustment(base, {"mc_volatility": 0.01, "mc_tail_risk": None, "mc_bias": 0.0})
    assert out == base


def test_fuse_payload_skips_when_mc_unavailable():
    fusion = SimpleNamespace(available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    mc = SimpleNamespace(available=False)
    out = fuse_payload_apply_mc_adjustment(fusion, mc, 450.0)
    assert out.prob_up == 0.5
