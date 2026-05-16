"""OP-008: Schwab theta only unless governed BS fallback enabled."""

from __future__ import annotations

from v2_decision import a2_option_expression as a2oe


def test_theta_returns_not_implemented_without_schwab_or_governed_bs():
    theta, source, detail = a2oe._theta(
        chain_row={"theta": None},
        ms_dict={"spot": 500.0},
        strike=500.0,
        option_right="CALL",
    )
    assert theta is None
    assert source == "not_implemented"
    assert detail == "schwab_theta_missing"


def test_theta_uses_schwab_chain_leaf_when_present():
    theta, source, detail = a2oe._theta(
        chain_row={"theta": -0.12},
        ms_dict={"spot": 500.0},
        strike=500.0,
        option_right="CALL",
    )
    assert theta == -0.12
    assert source == "v2_compliant"
    assert detail == "schwab_chain_theta"
