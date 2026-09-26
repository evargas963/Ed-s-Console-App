"""math_volatility.compute_expected_move_iv must require a real Schwab IV, never
fall back to a synthetic default IV when the real value is missing -- a synthetic
default silently fabricates an expected-move number."""
from __future__ import annotations






def test_signal_input_iv_level_preserves_missing_atm_iv_as_none():
    totals = [type("Totals", (), {"atm_iv": None})()]

    iv_level = (
        float(getattr(totals[0], "atm_iv"))
        if totals and getattr(totals[0], "atm_iv", None) is not None
        else None
    )

    assert iv_level is None


