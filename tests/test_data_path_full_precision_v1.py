"""Every producer keeps the full number.

Operator 2026-10-07: no rounding of a calculated result; only the screen formats a number for
display. Each test runs the producer on a real captured
Schwab chain, valued at the chain's own capture time (passed in, never a patched clock), and
asserts the result is the computation's full value, not one cut to a few decimals.

Real data (tests/real_chains.py): SPY's 0DTE chain of 2026-10-07 12:32 ET (20 strikes, 767-786).
"""

from __future__ import annotations

from math_levels import GAMMA_FLIP_NARROW
from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.real_chains import SPY_0DTE


def test_the_flip_is_the_profiles_full_zero_crossing():
    """SPY's 20-strike 0DTE chain: the flip is the gamma profile's full zero crossing.

    The flip is the interpolated zero crossing of the gamma profile in full, inside the
    delivered strikes (767 to 786); the verdict is NARROW because 20 strikes span only
    ~+/-1.3% of spot. Every contract is priced, and the curve's gamma at spot has the sign of
    Schwab's own gamma summed over the book: both negative.
    """
    chain, spot = read_chain(SPY_0DTE.chain), SPY_0DTE.spot
    snap = compute_terrain(SPY_0DTE.ticker, chain, spot, now=SPY_0DTE.now)
    flip, confidence = snap.gamma_flip, snap.confidence
    assert confidence == GAMMA_FLIP_NARROW
    assert flip == 779.015982542143
    assert 767.0 < flip < 786.0
    assert snap.net_gex_at_spot < 0 and snap.flip_note is None
