"""Action 11.9: call_engine.py fail-closed on missing index quotes + fusion posteriors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace



ROOT = Path(__file__).resolve().parent.parent
CALL_ENGINE = (ROOT / "call_engine.py").read_text(encoding="utf-8")

_FORBIDDEN_CALL_ENGINE_PATTERNS = (
    '(exp or 0) >= (cont or 0)',
    'float(etf_chg_pct or 0.0)',
    'inp.spy_chg_pct or 0.0',
    'inp.qqq_chg_pct or 0.0',
    'inp.iwm_chg_pct or 0.0',
    "return \"neutral\"  # not enough movement",
    "getattr(fusion, 'reversal_posterior', 0.0)",
    "getattr(fusion, 'continuation_posterior', 0.0)",
    "getattr(fusion, 'breakout_posterior', 0.0)",
    'inp.net_delta or 0.0',
    "getattr(fusion, 'model_agreement', 0.5)",
)

_DEFERRED_11_9B_PATTERNS: tuple[str, ...] = ()








def test_call_engine_file_has_no_fail_open_high_priority_patterns():
    for pattern in _FORBIDDEN_CALL_ENGINE_PATTERNS:
        assert pattern not in CALL_ENGINE, f"fail-open pattern still present: {pattern}"


def test_the_call_has_no_index_etf_votes():
    """Operator 2026-09-23: "remove the benchmark votes" -- no SPY/QQQ/IWM tape votes and no
    index-divergence downgrade; each ticker is read on its own data."""
    import call_engine
    for gone in ("_index_basket_vote", "_cross_instrument_signal", "_cross_instrument_notes"):
        assert not hasattr(call_engine, gone), gone
    assert "spy_basket" not in CALL_ENGINE and "cross_sig" not in CALL_ENGINE










def _fusion_for_call(**overrides):
    base = dict(
        available=True,
        dominant_direction="up",
        fusion_dominant_direction="up",
        model_agreement=0.72,
        n_sources_active=2,
        fusion_confidence="medium",
        reversal_posterior=0.25,
        continuation_posterior=0.2,
        breakout_posterior=0.2,
        mc_available=True,
        mc_containment=0.45,
        mc_expansion=0.4,
        mc_eae=0.8,
        mc_efe=1.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


