"""Action 10: fail-closed defaults — one regression per fix (must fail on b81fd3d)."""

from __future__ import annotations

from types import SimpleNamespace

from market_context import MarketContext, proximity_alerts
from market_state import MarketState, derive_zone


# Fix 1 — derive_zone expansion without net_delta
def test_fix1_derive_zone_expansion_unknown_without_net_delta():
    assert derive_zone("expansion", None) == "expansion_unknown"
    assert derive_zone("expansion", 0.0) == "breakout"
    assert derive_zone("expansion", -1.0) == "breakdown"


# Fix 2 — validation_* dataclass defaults
def test_fix2_market_state_validation_defaults_none():
    ms = MarketState()
    assert ms.validation_passed is None
    assert ms.structure_valid is None
    assert ms.probability_valid is None
    assert ms.risk_valid is None


# Fix 3 — forward_prob_* dataclass defaults
def test_fix3_market_state_forward_prob_defaults_none():
    ms = MarketState()
    assert ms.forward_prob_up is None
    assert ms.forward_prob_down is None
    assert ms.forward_prob_flat is None


# Fix 4 — vol_regime_*_mult dataclass defaults
def test_fix4_market_state_vol_regime_mult_defaults_none():
    ms = MarketState()
    assert ms.vol_regime_conviction_mult is None
    assert ms.vol_regime_risk_mult is None


# Fix 5 — fusion posteriors dataclass defaults
def test_fix5_market_state_fusion_posterior_defaults_none():
    ms = MarketState()
    assert ms.fusion_dominant_prob is None
    assert ms.fusion_confidence_score is None
    assert ms.fusion_breakout is None
    assert ms.fusion_pinning is None
    assert ms.fusion_continuation is None
    assert ms.fusion_reversal is None
    assert ms.fusion_vol_expansion is None
    assert ms.fusion_mean_reversion is None
    assert ms.fusion_model_agreement is None


# Fix 6 — fusion_prob_* dataclass defaults
def test_fix6_market_state_fusion_prob_defaults_none():
    ms = MarketState()
    assert ms.fusion_prob_up is None
    assert ms.fusion_prob_down is None
    assert ms.fusion_prob_flat is None


# Fix 7 — MarketContext.bond_signal default
def test_fix7_market_context_bond_signal_default_none():
    ctx = MarketContext()
    assert ctx.bond_signal is None


# Fix 8 — MarketContext.session_label default
def test_fix8_market_context_session_label_default_none():
    ctx = MarketContext()
    assert ctx.session_label is None


# Fix 9 — proximity_alerts spot guard
def test_fix9_proximity_alerts_rejects_invalid_spot():
    wall = SimpleNamespace(level=100.0, role="Wall", label="test")
    assert proximity_alerts(None, [wall], []) == []
    assert proximity_alerts(0.0, [wall], []) == []
    assert proximity_alerts(-5.0, [wall], []) == []
    out = proximity_alerts(100.0, [wall], [])
    assert len(out) == 1
