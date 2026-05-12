"""score_option_expression must reject Schwab's -999 greek sentinel.

Without sentinel filtering, the deterministic baseline scorer would multiply
``-999.0 * openInterest`` for ``gamma_x_oi`` and treat ``-999`` as the
"max gamma" of the chain, producing nonsense composite scores and a
spurious ``gamma_is_max`` audit flag.
"""

from __future__ import annotations

import pytest

from math_probabilities import score_option_expression


def _row(
    *,
    strike: float,
    side: str,
    delta: float | None,
    gamma: float | None,
    bid: float = 1.20,
    ask: float = 1.30,
    volume: int = 1200,
    open_interest: int = 4300,
) -> dict:
    return {
        "putCall": side,
        "strikePrice": strike,
        "bid": bid,
        "ask": ask,
        "delta": delta,
        "gamma": gamma,
        "totalVolume": volume,
        "openInterest": open_interest,
    }


def test_score_option_expression_treats_minus_999_greeks_as_missing():
    """gamma=-999 and delta=-999 must yield None for greeks and derived ratios."""
    contracts = [_row(strike=500.0, side="CALL", delta=-999.0, gamma=-999.0)]

    result = score_option_expression(contracts, spot=500.0, strike=500.0, side="CALL")

    assert result is not None
    assert result.gamma is None
    assert result.delta is None
    assert result.delta_gamma_ratio is None
    assert result.gamma_x_oi is None
    assert result.gamma_is_max is False
    assert result.max_gamma_strike is None


def test_score_option_expression_does_not_pin_max_gamma_to_sentinel_strike():
    """A real-gamma strike must beat a sentinel strike when finding max gamma."""
    contracts = [
        _row(strike=499.0, side="CALL", delta=-999.0, gamma=-999.0),
        _row(strike=500.0, side="CALL", delta=0.52, gamma=0.08),
        _row(strike=501.0, side="CALL", delta=-999.0, gamma=-999.0),
    ]

    result = score_option_expression(contracts, spot=500.0, strike=500.0, side="CALL")

    assert result is not None
    assert result.gamma == pytest.approx(0.08)
    assert result.max_gamma_strike == pytest.approx(500.0)
    assert result.gamma_is_max is True


def test_score_option_expression_uses_wire_greeks_when_present():
    """Sanity check: clean greeks still flow through unchanged."""
    contracts = [_row(strike=500.0, side="CALL", delta=0.52, gamma=0.08)]

    result = score_option_expression(contracts, spot=500.0, strike=500.0, side="CALL")

    assert result is not None
    assert result.delta == pytest.approx(0.52)
    assert result.gamma == pytest.approx(0.08)
    assert result.gamma_x_oi == pytest.approx(0.08 * 4300)
    assert result.delta_gamma_ratio == pytest.approx(round(0.52 / 0.08, 2))
