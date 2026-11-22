"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on REAL captured chains (tests/real_chains.py, captured 2026-10-07), never a hand-built
one, each valued at its own capture instant, so the numbers are whatever the actual data produces.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from calc.terrain_engine import (
    TERRAIN_SCHEMA_VERSION,
    WALL_BREACHED,
    WALL_CONTAINS,
    atm_sigma_by_expiry,
    compute_terrain,
    nearest_position,
    nearest_strike,
    price_relations,
    wall_geometry_state,
)
from option_contract import read_chain, read_contract
from tests.real_chains import MRVL, NFLX, SPY_0DTE, SPY_FULL, spy_0dte_book
from time_et import sessions

NOW = SPY_0DTE.now


def _strike_sigma(chain: list, expiry: str, strike: float) -> float:
    """Return a strike's volatility, worked out from the chain outside the calculator.

    The mean of its call's and its put's Schwab volatility (a percent), as a fraction.
    """
    legs = {c.side: c.volatility for c in chain if c.expiry == expiry and c.strike == strike}
    return (legs["CALL"] + legs["PUT"]) / 200.0


def test_fails_closed_on_every_missing_input() -> None:
    """No ticker, no chain, no spot -> a stand-aside payload, never a partial one."""
    for ticker, chain, spot in (
        ("", None, None),
        ("SPY", None, 743.0),
        ("SPY", [], 743.0),
        ("SPY", [read_contract({"strikePrice": 740})], None),
        ("SPY", [read_contract({"strikePrice": 740})], 0.0),
    ):
        snap = compute_terrain(ticker, chain, spot, now=NOW, sessions=sessions())
        assert snap.regime == "UNAVAILABLE"
        assert snap.headline.startswith("No estimate"), snap.headline
        assert snap.gamma_flip is None
        assert snap.call_wall is None and snap.put_wall is None
        assert snap.error, "a refusal must state its reason"


def test_real_chain_produces_a_complete_payload() -> None:
    chain, spot = spy_0dte_book()
    snap = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions())

    assert snap.ticker == "SPY"
    assert snap.spot == spot
    assert snap.schema_version == TERRAIN_SCHEMA_VERSION
    assert snap.contracts_used > 0
    assert snap.strikes_used > 0
    assert snap.headline, "the operator always gets a sentence"
    assert "lines" not in price_relations(snap.to_dict(), spot).to_dict(), "no page reads them"


def test_levels_are_real_strikes_or_absent() -> None:
    """A level must be a strike that exists in the chain — never interpolated or invented.

    The gamma flip is the one exception: it is interpolated between strikes by design.
    """
    chain, spot = spy_0dte_book()
    snap = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions())
    strikes = {c.strike for c in chain if c.strike is not None}
    served = snap.to_dict() | price_relations(snap.to_dict(), spot).to_dict()

    for name in (
        "call_wall",
        "put_wall",
        "absolute_gamma_strike",
        "pin_candidate",
        "call_charm_wall",
        "put_charm_wall",
    ):
        value = served[name]
        assert value is None or value in strikes, f"{name}={value} is not a chain strike"
    # RC-134: dead total-gamma twin removed — absolute_gamma_strike is the sole terrain
    # total-gamma level.
    assert "hvl" not in snap.to_dict(), (
        "terrain must not ship hvl (it equals absolute_gamma_strike by construction)"
    )


def test_the_regime_is_the_sign_of_gamma_at_the_price_whatever_strikes_the_chain_lists() -> None:
    """The regime is issued from dealer gamma at the price, with no chain-coverage gate.

    Operator 2026-11-19: every chain is asked with every strike, and the 5% and 10%
    coverage spans had no source. Failure this catches: SPY's real 0DTE chain of 2026-10-07 lists
    strikes only 767 to 786 around 776.61, so the old gate called it a narrow chain and withheld
    the regime ("UNAVAILABLE") although Schwab's gamma summed over the book is known and negative.
    """
    chain, spot = spy_0dte_book()
    snap = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions())
    assert snap.net_gex_at_spot is not None and snap.net_gex_at_spot < 0
    assert snap.regime == "SHORT_GAMMA_TREND"
    assert snap.headline.startswith("Dealer gamma is negative"), snap.headline


def test_a_wall_that_holds_the_price_carries_no_dealer_word() -> None:
    """A containing wall's label is None; only a breached wall says where the price is.

    Operator 2026-11-19: "DEALERS SELL" / "DEALERS BUY" and the two-sided "magnet"
    words go; a wall's side of the price is already served (call_wall_state, put_wall_state).
    Failures this catches, on real chains of 2026-10-07 (tests/real_chains.py): MRVL at 283.73,
    a known regime between its put wall 270 and call wall 300, served the dealer words; NFLX at
    68.76, both walls on strike 70, served "TWO-SIDED — magnet, not a barrier" on each.
    """
    for real, put_lean in ((MRVL, None), (NFLX, "BREACHED — spot below")):
        snap = compute_terrain(
            real.ticker, read_chain(real.chain), real.spot, now=real.now, sessions=sessions()
        )
        rel = price_relations(snap.to_dict(), real.spot)
        assert snap.regime != "UNAVAILABLE", real.ticker
        assert rel.call_wall_state == WALL_CONTAINS and rel.call_wall_lean is None, real.ticker
        assert rel.put_wall_lean == put_lean, real.ticker
    assert (snap.put_wall, snap.call_wall) == (70.0, 70.0)  # NFLX: one strike holds both


def test_payload_is_json_serialisable() -> None:
    """It is served over HTTP; a non-serialisable field breaks the tab silently."""
    chain, spot = spy_0dte_book()
    payload = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions()).to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["ticker"] == "SPY"
    assert "spot" in round_tripped and "confidence" not in round_tripped
    assert "flip_note" in round_tripped


def test_the_atm_iv_takes_one_strike_from_each_side_of_the_step_at_the_forward() -> None:
    """The real NFLX chain's 2026-10-16 expiry, nine days out: Schwab's volatility steps there.

    As captured its strikes read 67.5: 29.266, 68: 29.235, 69: 30.936, 70: 31.077. Between 68
    and 69, the pair that holds the forward (68.76 plus nine days' interest at Schwab's 4.037%:
    68.83), it steps up 1.70 where its neighbours move 0.03 and 0.14. The value is the mean of
    those two strikes', one from each side of the step: 30.0855. The strike nearest the price
    alone (69), the value before, is the upper side: 30.936. The terrain serves that value.
    """
    chain = read_chain(NFLX.chain)
    expiry = "2026-10-16"
    below, above = _strike_sigma(chain, expiry, 68.0), _strike_sigma(chain, expiry, 69.0)
    assert above - below > 0.015, "the step, as captured"
    assert abs(below - _strike_sigma(chain, expiry, 67.5)) < 0.001
    assert abs(_strike_sigma(chain, expiry, 70.0) - above) < 0.002
    value = atm_sigma_by_expiry(chain, NFLX.spot)[expiry]
    assert value is not None and math.isclose(value, (below + above) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 30.0855, abs_tol=5e-5)
    assert below < value < above
    snap = compute_terrain("NFLX", chain, NFLX.spot, now=NFLX.now, sessions=sessions())
    assert math.isclose(snap.atm_iv_pct_by_expiry[expiry], 100.0 * value, rel_tol=1e-12)


def test_a_step_one_pair_from_the_forward_is_where_the_atm_iv_is_read() -> None:
    """The real NFLX chain's 2028-01-21 expiry: the step sits in the pair above the forward's.

    As captured: 71: 33.432, 72: 33.253, 73: 33.271, 74: 44.680. The forward (68.76 plus 471
    days' interest: 72.34) is between 72 and 73, where the volatility barely moves; the two
    sides meet between 73 and 74, a step of 11.4. The value is the mean of 73's and 74's,
    38.9755; the forward's own pair would read the lower side twice, 33.26.
    """
    chain = read_chain(NFLX.chain)
    expiry = "2028-01-21"
    lower, upper = _strike_sigma(chain, expiry, 73.0), _strike_sigma(chain, expiry, 74.0)
    assert upper - lower > 0.11, "the step, as captured"
    assert abs(lower - _strike_sigma(chain, expiry, 72.0)) < 0.001
    value = atm_sigma_by_expiry(chain, NFLX.spot)[expiry]
    assert value is not None and math.isclose(value, (lower + upper) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 38.9755, abs_tol=5e-5)


def test_a_price_that_crossed_a_strike_since_the_contracts_were_solved_reads_the_same_step() -> (
    None
):
    """INDUCED: the real NFLX chain valued at a price a strike lower and a strike higher.

    Schwab solves a contract's volatility at the price of that moment and sends a contract's
    Greeks about every fifteen seconds, so the price can cross a strike before the step moves
    with it. With the forward in the pair below the step (a price of 67.90) or in the pair above
    it (69.30), the value is still the mean of the step's own two strikes, 68 and 69.
    """
    chain = read_chain(NFLX.chain)
    expiry = "2026-10-16"
    as_captured = atm_sigma_by_expiry(chain, NFLX.spot)[expiry]
    assert as_captured is not None
    for moved in (67.90, 69.30):
        assert atm_sigma_by_expiry(chain, moved)[expiry] == as_captured, moved


def test_with_no_step_near_the_forward_the_atm_iv_is_its_own_pairs() -> None:
    """The real SPY chain's same-day expiry (2026-11-09, 11:06 ET): no interest left, no step.

    As captured: 749: 21.626, 750: 20.670, 751: 20.219, 752: 19.810, falling at every strike
    around the forward (no day of interest to a same-day expiry: the price, 750.36). The value
    is the mean of the forward's own two strikes, 750 and 751: 20.444.
    """
    chain = read_chain(SPY_FULL.chain)
    expiry = "2026-11-09"
    sigma = {k: _strike_sigma(chain, expiry, k) for k in (749.0, 750.0, 751.0, 752.0)}
    assert sigma[749.0] > sigma[750.0] > sigma[751.0] > sigma[752.0], "no rise, as captured"
    value = atm_sigma_by_expiry(chain, SPY_FULL.spot)[expiry]
    assert value is not None
    assert math.isclose(value, (sigma[750.0] + sigma[751.0]) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 20.444, abs_tol=5e-4)


def test_the_atm_iv_is_the_same_whichever_way_the_chain_is_ordered() -> None:
    """The real MRVL full chain, 20 expiries, read forwards and backwards.

    Once the first contract met won, so the answer followed the chain's order.
    """
    chain = read_chain(MRVL.chain)
    forwards = atm_sigma_by_expiry(chain, MRVL.spot)
    assert forwards == atm_sigma_by_expiry(list(reversed(chain)), MRVL.spot)
    assert sum(v is not None for v in forwards.values()) > 10


def test_the_atm_iv_is_unknown_without_a_rate_or_a_strike_on_each_side_of_the_forward() -> None:
    """INDUCED on the real NFLX chain: no rate sent; no days sent; a price off the listing.

    The forward needs Schwab's rate and its days to the expiry, and the value a listed strike
    at or below the forward and one above it. Without them it is unknown, never the nearest
    strike's.
    """
    chain = read_chain(NFLX.chain)
    expiry = "2026-10-16"
    assert atm_sigma_by_expiry(chain, NFLX.spot)[expiry] is not None
    no_rate = [replace(c, interest_rate=None) if c.expiry == expiry else c for c in chain]
    assert atm_sigma_by_expiry(no_rate, NFLX.spot)[expiry] is None
    no_days = [replace(c, days_to_expiry=None) if c.expiry == expiry else c for c in chain]
    assert atm_sigma_by_expiry(no_days, NFLX.spot)[expiry] is None
    strikes = [c.strike for c in chain if c.expiry == expiry]
    assert atm_sigma_by_expiry(chain, max(strikes) + 1.0)[expiry] is None
    assert atm_sigma_by_expiry(chain, min(strikes) / 2.0)[expiry] is None


def test_the_nearest_strike_is_one_rule_for_a_list_in_order_and_a_list_that_is_not() -> None:
    """The real SPY chain's strikes, at prices below, on, between, midway and above them.

    nearest_position (the daemon's recorded window and streamed-contract order) and
    nearest_strike (every panel's spot row) agree with the nearest by distance, lower on a tie.
    """
    chain, spot = spy_0dte_book()
    strikes = sorted({c.strike for c in chain})
    lower = max(k for k in strikes if k <= spot)
    upper = min(k for k in strikes if k > lower)
    cases = (
        strikes[0] - 5,
        strikes[0],
        lower,
        (lower + upper) / 2.0,
        (lower + upper) / 2.0 + 0.01,
        spot,
        strikes[-1],
        strikes[-1] + 5,
    )
    for price in cases:
        want = min(strikes, key=lambda k: (abs(k - price), k))
        assert strikes[nearest_position(strikes, price)] == want, price
        assert nearest_strike(list(reversed(strikes)), price) == want, price
    assert strikes[nearest_position(strikes, (lower + upper) / 2.0)] == lower
    assert nearest_position([], spot) == -1 and nearest_strike([], spot) is None


def test_an_atm_contract_with_no_iv_is_never_replaced_by_the_next_strikes() -> None:
    """The ATM call's IV is Schwab's -999 (no value): that leg has no IV.

    The expiry's ATM IV is None -- the 705 call's IV used to stand in for it, labelled ATM
    (operator 2026-10-01: "we use what schwab gives us and we display it"). INDUCED: the same
    chain with that call's IV sent has one, the mean of the 700 and 705 strikes'.
    """
    # the rule needs a known ATM contract with no IV beside priced ones: the two strikes around
    # the forward (700 plus a day's interest), each with its call and its put
    day = {"daysToExpiration": 1, "expirationDate": "2026-10-02", "interestRate": 4.0}
    legs = (
        ("CALL", 700.0, -999.0),
        ("CALL", 705.0, 30.0),
        ("PUT", 700.0, 24.0),
        ("PUT", 705.0, 30.0),
    )
    chain = read_chain(
        [{"putCall": side, "strikePrice": k, "volatility": iv, **day} for side, k, iv in legs]
    )
    assert atm_sigma_by_expiry(chain, 700.0) == {"2026-10-02": None}
    sent = [replace(chain[0], volatility=26.0), *chain[1:]]
    assert atm_sigma_by_expiry(sent, 700.0) == {"2026-10-02": pytest.approx((0.25 + 0.30) / 2.0)}


def test_every_expiry_carries_its_atm_iv_by_the_one_rule() -> None:
    """The Trade Desk's Volatility card draws ATM IV by expiry (2026-09-28).

    One function for every expiry. Real MRVL full chain, 20 expiries, valued at its capture
    (tests/real_chains.py).
    """
    chain = read_chain(MRVL.chain)
    snap = compute_terrain("MRVL", chain, MRVL.spot, now=MRVL.now, sessions=sessions())
    by_exp = snap.atm_iv_pct_by_expiry
    assert list(by_exp) == sorted({c.expiry for c in chain})
    assert list(snap.pcr_by_expiry) == list(by_exp), "both card lines run nearest expiry first"
    assert all(v is None or 0 < v < 1000 for v in by_exp.values())


def test_an_expiry_whose_contracts_carry_two_dtes_is_one_expiry() -> None:
    """One expiry's contracts sent with two daysToExpiration values are read as one expiry.

    INDUCED: the real MRVL chain with the last contract of one expiry carrying no
    daysToExpiration (Schwab's -999, read as None); no capture holds one (every expiry of every
    captured chain carries one value). The expiry's put/call ratio is over all its contracts, its
    ATM IV is the expiry's as sent, and its DTE, two values sent, is unknown: a book of the one
    contract used to overwrite the expiry's.
    """
    chain = read_chain(MRVL.chain)
    expiry = sorted({c.expiry for c in chain})[2]
    last = max(i for i, c in enumerate(chain) if c.expiry == expiry)
    induced = [*chain[:last], replace(chain[last], days_to_expiry=None), *chain[last + 1 :]]
    snap = compute_terrain("MRVL", induced, MRVL.spot, now=MRVL.now, sessions=sessions())
    as_sent = compute_terrain("MRVL", chain, MRVL.spot, now=MRVL.now, sessions=sessions())
    legs = [c for c in chain if c.expiry == expiry]
    puts = sum(c.open_interest for c in legs if c.side == "PUT")
    calls = sum(c.open_interest for c in legs if c.side == "CALL")
    assert calls > 0 and math.isclose(snap.pcr_by_expiry[expiry], puts / calls, rel_tol=1e-12)
    assert snap.atm_iv_pct_by_expiry[expiry] == as_sent.atm_iv_pct_by_expiry[expiry] is not None
    assert snap.expiry_dte[expiry] is None
    assert snap.expiries == as_sent.expiries


# ── RC-130: wall geometry state — the support/resistance claim is CONDITIONAL ────────────────
# Live SPY 2026-07-29: put wall 740.0 sat ABOVE spot 735.13 while every surface said
# "dealer support". Institutional standard (SpotGamma stats, GEXBoard): the picker stays at
# the concentration max — unconstrained by spot — and a breach is a DISTINCT reported state,
# not a moved strike. These tests pin the state function and its carriage.


def test_wall_geometry_state_truth_table() -> None:
    # the live defect, exactly: put wall above spot is NOT support
    assert wall_geometry_state(735.13, 740.0, "put") == "breached"
    assert wall_geometry_state(735.13, 730.0, "put") == "contains"
    assert wall_geometry_state(735.13, 750.0, "call") == "contains"
    assert wall_geometry_state(735.13, 730.0, "call") == "breached"
    # equality: a wall AT spot contains nothing
    assert wall_geometry_state(740.0, 740.0, "put") == "breached"
    assert wall_geometry_state(740.0, 740.0, "call") == "breached"
    # absence stays absence — never a guessed state
    assert wall_geometry_state(None, 740.0, "put") is None
    assert wall_geometry_state(735.0, None, "call") is None


def test_wall_geometry_state_rejects_unknown_side() -> None:
    with pytest.raises(ValueError):
        wall_geometry_state(735.0, 740.0, "steel")


def test_real_chain_wall_states_agree_with_the_geometry() -> None:
    """The states qualify the walls at the price given, and agree with the geometry."""
    chain, spot = spy_0dte_book()
    snap = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions())
    d = price_relations(snap.to_dict(), spot)
    assert d.call_wall_state == wall_geometry_state(spot, snap.call_wall, "call")
    assert d.put_wall_state == wall_geometry_state(spot, snap.put_wall, "put")
    assert d.call_wall_state in (WALL_CONTAINS, WALL_BREACHED)
    assert d.put_wall_state in (WALL_CONTAINS, WALL_BREACHED)


def test_the_prices_side_of_the_flip_is_served_in_the_strips_words() -> None:
    """SPY's 0DTE book and its flip: the price's side of it, in the Desk strip's words.

    The price is INDUCED above, at and below the flip the real chain publishes; with no price
    there is no side and no words. The page draws the words and picks none.
    """
    chain, spot = spy_0dte_book()
    published = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions()).to_dict()
    flip = published["gamma_flip"]
    assert flip is not None

    def said(price: float | None) -> tuple[str | None, str | None]:
        relations = price_relations(published, price)
        return relations.flip_relation, relations.flip_relation_text

    assert said(flip + 1) == ("ABOVE", "Above Γ flip")
    assert said(flip) == ("AT", "At Γ flip")
    assert said(flip - 1) == ("BELOW", "Below Γ flip")
    assert said(None) == (None, None)


def test_unavailable_terrain_does_not_fabricate_pin_score_stamps() -> None:
    snap = compute_terrain("SPY", None, SPY_0DTE.spot, now=NOW, sessions=sessions())
    assert snap.absolute_gamma_strike is None
    assert snap.pin_expected_moves is None
    assert snap.pin_strike_widths is None
    assert snap.pin_minutes_to_close is None
    assert snap.pin_candidate is None, "no chain must never yield a pin claim"
