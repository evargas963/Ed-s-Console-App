"""Deterministic terrain read — the regime rule, its sourced headline, fail-closed behaviour.

The rule tests give the read a price and a gamma at spot; the last test reads real Schwab
chains through the levels producer.
"""

from __future__ import annotations

from calc.terrain_engine import compute_terrain
from calc.terrain_read import (
    REGIME_LONG_GAMMA,
    REGIME_SHORT_GAMMA,
    REGIME_UNAVAILABLE,
    build_terrain_read,
)
from option_contract import read_chain
from tests.real_chains import CRWD, SPY_0DTE
from time_et import sessions

#: trade instructions no published study supports (gamma_regime_research.md): never in a headline
INSTRUCTIONS = ("fade", "chase", "follow breaks", "stand aside", "chop", "trend regime")


def test_positive_gamma_reads_as_an_estimate_of_smaller_swings_not_a_trade() -> None:
    r = build_terrain_read(spot=750.0, gamma_at_spot=2.5e8)
    assert r.regime == REGIME_LONG_GAMMA
    assert r.headline.startswith("Dealer gamma is positive")
    assert "long calls, short puts" in r.headline_source, "the model's assumption, on hover"
    assert "smaller price swings" in r.headline and "not to a trade direction" in r.headline
    assert not any(w in r.headline.lower() for w in INSTRUCTIONS), r.headline


def test_negative_gamma_reads_as_an_estimate_of_larger_swings_not_a_trade() -> None:
    r = build_terrain_read(spot=743.29, gamma_at_spot=-1.1e8)
    assert r.regime == REGIME_SHORT_GAMMA
    assert r.headline.startswith("Dealer gamma is negative")
    assert "Baltussen" in r.headline_source, "the late-day continuation's source, on hover"
    assert "larger price swings" in r.headline and "not to a trade direction" in r.headline
    assert not any(w in r.headline.lower() for w in INSTRUCTIONS), r.headline


def test_regime_is_the_signed_gamma_at_spot_only() -> None:
    """T-07 (2026-09-24): no spot-vs-flip fallback.

    No signed gamma, or exactly zero (spot AT the flip), is no regime -- not a side picked from
    the flip.
    """
    for g in (None, 0.0):
        r = build_terrain_read(spot=750.0, gamma_at_spot=g)
        assert r.regime not in (REGIME_LONG_GAMMA, REGIME_SHORT_GAMMA), g


def test_missing_inputs_fail_closed() -> None:
    for spot in (None, 0.0):
        r = build_terrain_read(spot=spot, gamma_at_spot=2.5e8)
        assert r.regime == REGIME_UNAVAILABLE
        assert r.headline.startswith("No estimate"), r.headline


def test_the_regime_is_read_by_one_rule_for_every_instrument():
    """All tickers (operator 2026-09-23, "show for all tickers"): one rule reads the regime.

    The regime is the sign of Schwab's gamma at spot wherever it is known, for an ETF and a
    single name alike; a single name's regime was once withheld (SIGN-DEMOTION) and the argument
    that carried the ticker in stayed behind, dead. Real Schwab chains (tests/real_chains.py),
    each valued at its own capture: SPY's 0DTE chain (20 strikes) and CRWD's complete chain are
    both issued.
    """
    got = {}
    for real in (SPY_0DTE, CRWD):
        tk = real.ticker
        snap = compute_terrain(
            tk, read_chain(real.chain), real.spot, now=real.now, sessions=sessions()
        )
        g = snap.net_gex_at_spot
        got[tk] = (g, snap.regime)
        if not g:
            assert snap.regime == REGIME_UNAVAILABLE, tk
        else:
            assert snap.regime == (REGIME_LONG_GAMMA if g > 0 else REGIME_SHORT_GAMMA), tk
    assert got["CRWD"][1] != REGIME_UNAVAILABLE, "a single name's regime is issued"
    assert got["SPY"][1] != REGIME_UNAVAILABLE, "a chain of 20 strikes has its regime issued"
