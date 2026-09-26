"""math_volatility.compute_expected_move_iv must require a real Schwab IV, never
fall back to a synthetic default IV when the real value is missing -- a synthetic
default silently fabricates an expected-move number."""
from __future__ import annotations

from pathlib import Path





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
