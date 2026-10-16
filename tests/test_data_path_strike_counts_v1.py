"""Schwab -> the strike rows. Volume and open interest keep every digit; the screen rounds."""
from __future__ import annotations

from terrain_engine import _per_strike_measure_rows, _per_strike_rows


def test_a_strike_keeps_every_digit_of_volume_and_open_interest():
    """A count Schwab sent as a fraction of a contract is the count on the row. Cutting it to a
    whole number happens on the screen, not in the calculation."""
    volume = _per_strike_rows({
        500.0: {
            "dollarized": True,
            "net_gex_1pct": 12.5,
            "volume_unreported": 0,
            "call_volume": 10.4,
            "put_volume": 0.2,
        },
    })
    assert volume == [[500.0, 12.5, 10.6]]
    oi = _per_strike_measure_rows({
        500.0: {
            "oi_unreported": 0,
            "call_oi": 3.4,
            "put_oi": 0.2,
        },
    })["oi"]
    assert oi == [[500.0, 3.6]]
