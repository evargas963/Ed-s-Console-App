"""DFR-023: MC fusion skips adjustment when normalized features are missing."""

from __future__ import annotations

from mc_fusion_adjustment import apply_mc_adjustment


def test_apply_mc_adjustment_skips_when_mc_volatility_missing():
    base = (0.55, 0.25, 0.20)
    out = apply_mc_adjustment(base, {"mc_volatility": None, "mc_tail_risk": 0.1, "mc_bias": 0.0})
    assert out == base
