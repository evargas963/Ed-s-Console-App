"""FIND-CHARM-BY-STRIKE-V1 — per-strike dealer charm exposure and charm walls.

Charm-by-strike is standard institutional practice (SpotGamma / Unusual Whales /
VannaCharm publish it alongside GEX) and charm pressure is the mechanism attributed to
the end-of-day pin. We previously computed only a chain-level charm aggregate.

The analytic charm is verified against a FINITE-DIFFERENCE derivative of Black-Scholes
delta — an independent derivation, not a restatement of the same formula. That check
caught a sign inversion in the first draft before it shipped, which is exactly why the
verification is a test and not a one-off script.
"""

from __future__ import annotations

import math

from math_levels import compute_charm_by_strike, pick_charm_wall_strikes
from tests.one_contract_greeks import charm
from tests.real_chains import SPY_0DTE, spy_0dte_book
from tests.shared_helpers import norm_cdf

#: a REAL same-day-expiry SPY chain captured 2026-10-07 12:32 ET, valued at its own capture time
NOW = SPY_0DTE.now


def _bs_delta_call(s: float, k: float, t: float, sig: float, r: float = 0.0) -> float:
    d1 = (math.log(s / k) + (r + 0.5 * sig * sig) * t) / (sig * math.sqrt(t))
    return norm_cdf(d1)


def test_bs_charm_matches_finite_difference_of_delta() -> None:
    """Independent check: charm IS dDelta/dt, so it must equal the numerical derivative."""
    cases = [
        (743.29, 745.0, 1 / 365, 0.15),
        (743.29, 740.0, 7 / 365, 0.18),
        (100.0, 100.0, 0.25, 0.20),
        (100.0, 110.0, 0.50, 0.25),
        (50.0, 45.0, 2 / 365, 0.35),
        (400.0, 420.0, 90 / 365, 0.22),
    ]
    for s, k, t, sig in cases:
        analytic = charm(s, k, t, sig)
        assert analytic is not None
        h = t * 1e-5
        finite = (_bs_delta_call(s, k, t - h, sig) - _bs_delta_call(s, k, t + h, sig)) / (2 * h)
        assert abs(analytic - finite) / max(abs(finite), 1e-12) < 1e-4, (
            f"charm != dDelta/dt at S={s} K={k} T={t}: {analytic} vs {finite}"
        )


def test_bs_charm_refuses_degenerate_inputs() -> None:
    assert charm(100.0, 100.0, 0.0, 0.20) is None  # expired
    assert charm(100.0, 100.0, 0.02, 0.0) is None  # no vol
    assert charm(0.0, 100.0, 0.02, 0.20) is None  # no spot


def test_charm_by_strike_on_real_chain_uses_dealer_convention() -> None:
    """net_charm must be call - put, matching the net-GEX dealer convention."""
    chain, spot = spy_0dte_book()
    cbs = compute_charm_by_strike(chain, spot, now=NOW)
    assert cbs, "real chain must produce per-strike charm"
    for b in cbs.values():
        assert math.isfinite(b["call_charm"])
        assert math.isfinite(b["put_charm"])
        assert abs(b["net_charm"] - (b["call_charm"] - b["put_charm"])) < 1e-6


def test_charm_walls_are_real_strikes_from_the_chain() -> None:
    chain, spot = spy_0dte_book()
    cbs = compute_charm_by_strike(chain, spot, now=NOW)
    assert cbs, "real chain must produce per-strike charm"
    call_wall, put_wall = pick_charm_wall_strikes(cbs)
    strikes = set(cbs)
    assert call_wall is None or call_wall in strikes
    assert put_wall is None or put_wall in strikes


def test_two_strikes_with_the_same_charm_give_the_lower_strike_whatever_their_order() -> None:
    """The real chain's charm map with its largest call charm put on a second, higher strike.

    The wall is the lower of the two in either order of the map, as every other level picks.
    """
    chain, spot = spy_0dte_book()
    cbs = compute_charm_by_strike(chain, spot, now=NOW)
    call_wall, put_wall = pick_charm_wall_strikes(cbs)
    assert call_wall is not None
    higher = max(k for k in cbs if k > call_wall)
    tied = {k: dict(b) for k, b in cbs.items()}
    tied[higher]["call_charm"] = cbs[call_wall]["call_charm"]
    for order in (sorted(tied), sorted(tied, reverse=True)):
        assert pick_charm_wall_strikes({k: tied[k] for k in order}) == (call_wall, put_wall)


def test_charm_by_strike_fails_closed() -> None:
    assert compute_charm_by_strike([], 100.0, now=NOW) == {}
    assert compute_charm_by_strike(None, 100.0, now=NOW) == {}
    chain, _ = spy_0dte_book()
    assert compute_charm_by_strike(chain, 0.0, now=NOW) == {}
    assert pick_charm_wall_strikes({}) == (None, None)
