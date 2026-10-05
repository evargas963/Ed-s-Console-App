"""AGENTS.md rule 2 on the -999 Schwab actually sent: a -999 is not a number, and everything else is
taken as sent. Real chain sweeps in which Schwab sent gamma -999
(tests/fixtures/real_chain_gamma_minus_999_*.json, captured read-only from complete_chain_captures)
through the reader every exposure is built from (math_exposure_core.compute_exposures_by_strike).
Schwab has sent -999 for gamma, delta, theta, vega and volatility, never for open interest.

Not asserted, an open question for the operator: the reader also voids a contract's Greeks when only
its volatility is -999 (math_exposure_core.vendor_greeks_unavailable), although Schwab sent the Greeks
as numbers; no Schwab source for that rule is cited."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_exposure_core import bucket_metric, compute_exposures_by_strike

_FX = Path(__file__).resolve().parent / "fixtures"
_CAPTURES = {p.name: json.loads(p.read_text(encoding="utf-8"))["rows"][0]
             for p in sorted(_FX.glob("real_chain_gamma_minus_999_*.json"))}


def _legs(row):
    """(strike, side, contracts, the strike's exposure bucket) for every listed leg."""
    books = compute_exposures_by_strike(row["chain"], spot=row["spot"])[0]
    for k, b in books.items():
        for side in ("CALL", "PUT"):
            leg = [c for c in row["chain"] if c["strikePrice"] == k and c["putCall"] == side]
            if leg:
                yield k, side, leg, b


def _case(leg) -> str:
    if any(c["gamma"] == -999 and c["openInterest"] > 0 for c in leg):
        return "absent"
    if any(c["volatility"] == -999 and c["gamma"] != -999 and c["openInterest"] > 0 for c in leg):
        return "open_question"
    return "known_beside_minus_999" if any(c["gamma"] == -999 for c in leg) else "known"


def test_the_captures_hold_minus_999_on_two_or_more_tickers():
    assert len({row["ticker"] for row in _CAPTURES.values()}) >= 2
    assert all(any(c["gamma"] == -999 for c in row["chain"]) for row in _CAPTURES.values())


@pytest.mark.parametrize("name", sorted(_CAPTURES))
def test_open_interest_is_taken_as_sent_beside_minus_999_greeks(name):
    """Every leg's open interest is the sum of Schwab's openInterest as sent; a contract's -999
    Greeks never make its open interest unreported."""
    row = _CAPTURES[name]
    for k, side, leg, b in _legs(row):
        assert b["oi_unreported"] == 0, k
        assert b[f"{side.lower()}_oi"] == float(sum(c["openInterest"] for c in leg)), (k, side)


@pytest.mark.parametrize("name", sorted(_CAPTURES))
def test_a_leg_with_gamma_minus_999_on_open_interest_has_no_gamma_and_otherwise_its_sum(name):
    """A leg holding a contract with open interest whose gamma Schwab sent as -999 has no gamma
    exposure (absent, never 0: rule 2). A -999 contract with open interest 0 adds a known 0. Every
    other leg's gamma exposure is the sum of gamma x openInterest x multiplier as sent (the reader's
    definition, compute_exposures_by_strike; its source is NOT_PROVEN)."""
    row = _CAPTURES[name]
    for k, side, leg, b in _legs(row):
        case = _case(leg)
        got = bucket_metric(b, f"{side.lower()}_gamma")
        if case == "absent":
            assert got is None, (k, side)
        elif case.startswith("known"):
            want = sum(c["gamma"] * c["openInterest"] * c["multiplier"] for c in leg if c["gamma"] != -999)
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (k, side)


def test_each_case_is_exercised_on_the_tickers_schwab_sent_it_for():
    """Which ticker exercises which case, from the captures: "known beside -999" (gamma -999 on open
    interest 0) on two or more tickers. "absent" (gamma -999 on open interest) on $SPX only: a read-only scan
    of every capture since 2026-09-28 (complete_chain_captures) found gamma -999 on open interest for
    no other ticker."""
    seen: dict = {}
    for row in _CAPTURES.values():
        for _k, _side, leg, _b in _legs(row):
            seen.setdefault(_case(leg), set()).add(row["ticker"])
    assert len(seen.get("known_beside_minus_999", ())) >= 2, seen
    assert seen.get("absent") == {"$SPX"}, seen
