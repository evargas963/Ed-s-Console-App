"""Schwab -> the strike rows. Open interest is the count Schwab sent, summed per strike.

Real data: a captured Schwab SPY chain (tests/real_chains.py: 2026-10-07 12:32 ET), through
compute_terrain as the console prices it. The expected rows are read straight off the chain;
the same chain's volume rows are tests/test_option_volume_is_live_v1.py's.
"""

from __future__ import annotations

from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from tests.real_chains import SPY_0DTE
from time_et import sessions


def _sum_by_strike(field: str) -> dict[float, int]:
    out: dict[float, int] = {}
    for c in SPY_0DTE.chain:
        k = float(c["strikePrice"])
        out[k] = out.get(k, 0) + int(c[field])
    return out


def test_a_strike_row_holds_the_open_interest_schwab_sent():
    """Each strike's open interest is its contracts' counts as sent, call + put.

    Cutting a count to a whole number happens on the screen, not in the calculation.
    """
    snap = compute_terrain(
        SPY_0DTE.ticker,
        read_chain(SPY_0DTE.chain),
        SPY_0DTE.spot,
        now=SPY_0DTE.now,
        sessions=sessions(),
    )
    oi = {r.strike: r.value for r in snap.per_strike["oi"]}
    assert oi == _sum_by_strike("openInterest")
