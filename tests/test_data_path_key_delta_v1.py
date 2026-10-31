"""The Key Delta Strike through the terrain, every captured chain: a strike with one side's delta
not known has no total, as total_gex_dollars_at_strike leaves one with a side's gamma not known."""

from __future__ import annotations

import pytest

from math_exposure_core import bucket_metric_abs, compute_exposures_by_strike
from terrain_engine import compute_terrain
from tests.real_chains import CRWD, MRVL, NFLX, SPY_0DTE, SPY_CLOSE, TSLA


@pytest.mark.parametrize(
    "held", [CRWD, MRVL, NFLX, SPY_0DTE, SPY_CLOSE, TSLA], ids=lambda h: h.ticker
)
def test_a_strike_with_one_sides_delta_not_known_is_not_the_key_delta_strike(held):
    """Induced test condition: Schwab's no-value code on the delta of the smaller side at the
    chain's key strike, its gamma and volatility as sent. No captured chain holds that alone."""
    key = compute_terrain(held.ticker, held.chain, held.spot, now=held.now).key_delta_strike
    book, _ = compute_exposures_by_strike(held.chain, spot=held.spot, now=held.now)
    calls = bucket_metric_abs(book[key], "call_dex_dollars")
    side = "CALL" if calls < bucket_metric_abs(book[key], "put_dex_dollars") else "PUT"
    chain = [
        dict(c, delta=-999.0) if c["strikePrice"] == key and c["putCall"] == side else c
        for c in held.chain
    ]
    after = compute_terrain(held.ticker, chain, held.spot, now=held.now).key_delta_strike
    assert after is not None and after != key
