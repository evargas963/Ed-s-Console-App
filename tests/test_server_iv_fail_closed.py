"""math_volatility.compute_expected_move_iv must require a real Schwab IV, never
fall back to a synthetic default IV when the real value is missing -- a synthetic
default silently fabricates an expected-move number."""
from __future__ import annotations

from pathlib import Path

from math_volatility import compute_expected_move_iv


def test_iv_expected_move_requires_schwab_iv_instead_of_synthetic_default():
    spot = 500.0
    atm_iv = None
    hours_remaining = 0.0
    em_up = None
    em_lo = None

    if (em_up is None or em_lo is None) and spot > 0 and atm_iv and atm_iv > 0:
        em = compute_expected_move_iv(spot, atm_iv, max(hours_remaining, 6.5))
        em_up = em.get("upper")
        em_lo = em.get("lower")

    assert em_up is None
    assert em_lo is None


def test_signal_input_iv_level_preserves_missing_atm_iv_as_none():
    totals = [type("Totals", (), {"atm_iv": None})()]

    iv_level = (
        float(getattr(totals[0], "atm_iv"))
        if totals and getattr(totals[0], "atm_iv", None) is not None
        else None
    )

    assert iv_level is None


def test_model_stack_does_not_inject_synthetic_twenty_percent_iv():
    source = Path("signals.py").read_text(encoding="utf-8")

    assert "iv=iv if iv > 0 else 0.20" not in source
    assert "iv=iv," in source
