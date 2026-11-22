"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on REAL captured chains (tests/real_chains.py, captured 2026-10-07 and, each contract
with its quote, 2026-11-12), never a hand-built one, each valued at its own capture instant, so
the numbers are whatever the actual data produces.
"""

from __future__ import annotations

import functools
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
from option_contract import OptionContract, read_chain, read_contract
from tests.real_chains import MRVL, NFLX, SPY_0DTE, quoted, spy_0dte_book
from time_et import sessions

NOW = SPY_0DTE.now


@functools.cache
def _quoted(name: str) -> tuple[list[OptionContract], float]:
    """A quoted real chain's contracts as the one reader reads them, and its price."""
    real = quoted(name)
    return read_chain(real.chain), real.spot


def _strike_sigma(chain: list, expiry: str, strike: float) -> float:
    """Return a strike's volatility, worked out from the chain outside the calculator.

    The mean of its call's and its put's Schwab volatility (a percent), as a fraction.
    """
    legs = {c.side: c.volatility for c in chain if c.expiry == expiry and c.strike == strike}
    return (legs["CALL"] + legs["PUT"]) / 200.0


def _mid_gap(chain: list, expiry: str, strike: float) -> float:
    """Return a strike's call mid price less its put's, worked out outside the calculator.

    Each mid the midpoint of the contract's bid and ask as its quote sent them.
    """
    mids = {
        c.side: (c.bid + c.ask) / 2.0 for c in chain if c.expiry == expiry and c.strike == strike
    }
    return mids["CALL"] - mids["PUT"]


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
    """The real AMZN chain's 2027-12-17 expiry, 400 days out: Schwab's volatility steps there.

    As captured its strikes read 275: 31.020, 280: 30.744, 285: 41.191, 290: 40.859: between 280
    and 285 it steps up 10.4 where its neighbours fall 0.3. That pair holds the forward the
    expiry's own options imply: the call's and the put's mid prices are nearest at 285, the put
    the dearer by 1.375, so the forward is just below 285. The value is the mean of those two
    strikes', one from each side of the step: 35.9677. The strike nearest the price alone (270),
    the value before, is on the lower side: 31.380. The terrain serves that value.
    """
    chain, spot = _quoted("amzn")
    expiry = "2027-12-17"
    below, above = _strike_sigma(chain, expiry, 280.0), _strike_sigma(chain, expiry, 285.0)
    assert above - below > 0.10, "the step, as captured"
    assert abs(below - _strike_sigma(chain, expiry, 275.0)) < 0.005
    assert abs(_strike_sigma(chain, expiry, 290.0) - above) < 0.005
    gaps = {k: _mid_gap(chain, expiry, k) for k in (275.0, 280.0, 285.0, 290.0)}
    assert min(gaps, key=lambda k: abs(gaps[k])) == 285.0 and gaps[285.0] < 0, gaps
    value = atm_sigma_by_expiry(chain, spot)[expiry]
    assert value is not None and math.isclose(value, (below + above) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 35.9677, abs_tol=5e-5)
    assert _strike_sigma(chain, expiry, 270.0) < value and below < value < above
    snap = compute_terrain("AMZN", chain, spot, now=quoted("amzn").now, sessions=sessions())
    assert math.isclose(snap.atm_iv_pct_by_expiry[expiry], 100.0 * value, rel_tol=1e-12)


def test_a_step_beside_the_options_own_forward_is_where_the_atm_iv_is_read() -> None:
    """The real SPY chain's 2026-11-30 expiry: the step sits in the pair below the forward's.

    As captured: 757: 12.426, 758: 12.251, 759: 14.333, 760: 14.161. The mid prices are nearest
    at 759, the call the dearer by a cent, so the options' own forward is just above 759, in the
    pair 759 and 760, where the volatility falls; the two sides meet between 758 and 759, a
    step of 2.08 with a fall on each side of it. The value is the mean of 758's and 759's,
    13.2919; the forward's own pair would read the upper side twice, 14.25.
    """
    chain, spot = _quoted("spy")
    expiry = "2026-11-30"
    lower, upper = _strike_sigma(chain, expiry, 758.0), _strike_sigma(chain, expiry, 759.0)
    assert upper - lower > 0.02, "the step, as captured"
    assert _strike_sigma(chain, expiry, 757.0) > lower
    assert upper > _strike_sigma(chain, expiry, 760.0)
    gaps = {k: _mid_gap(chain, expiry, k) for k in (757.0, 758.0, 759.0, 760.0)}
    assert min(gaps, key=lambda k: abs(gaps[k])) == 759.0 and gaps[759.0] > 0, gaps
    value = atm_sigma_by_expiry(chain, spot)[expiry]
    assert value is not None and math.isclose(value, (lower + upper) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 13.2919, abs_tol=5e-5)


def test_a_step_past_the_options_own_forward_is_found_up_to_the_price_plus_interest() -> None:
    """The real SPY chain's 2028-12-15 expiry, 764 days out: the step is two pairs above.

    As captured: 810: 10.300, 815: 10.018, 820: 9.726, 825: 23.995. The mid prices are nearest
    at 815, the put the dearer by 0.505, so the options' own forward is in the pair 810 and 815;
    the price plus 764 days' interest at the chain's rate is in the pair 820 and 825, where the
    volatility steps up 14.3. The pairs from one below the first to one above the second are
    searched, and the value is the mean of 820's and 825's, 16.8608; the options' own pair
    would read the lower side twice, 10.16.
    """
    chain, spot = _quoted("spy")
    expiry = "2028-12-15"
    lower, upper = _strike_sigma(chain, expiry, 820.0), _strike_sigma(chain, expiry, 825.0)
    assert upper - lower > 0.14, "the step, as captured"
    gaps = {k: _mid_gap(chain, expiry, k) for k in (805.0, 810.0, 815.0, 820.0, 825.0)}
    assert min(gaps, key=lambda k: abs(gaps[k])) == 815.0 and gaps[815.0] < 0, gaps
    terms = next(c for c in chain if c.expiry == expiry)
    by_interest = spot * (1.0 + terms.interest_rate / 100.0 * terms.days_to_expiry / 365.0)
    assert 820.0 <= by_interest < 825.0
    value = atm_sigma_by_expiry(chain, spot)[expiry]
    assert value is not None and math.isclose(value, (lower + upper) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 16.8608, abs_tol=5e-5)
    own = (_strike_sigma(chain, expiry, 810.0) + _strike_sigma(chain, expiry, 815.0)) / 2.0
    assert value - own > 0.06


def test_a_price_of_another_moment_than_the_quotes_reads_the_same_steps() -> None:
    """INDUCED: the real SPY chain valued at a price a dollar lower and a dollar higher.

    The stock's price and a contract's quote and volatility are each the newest Schwab sent, of
    different moments, so the price can cross a strike before the options' own records follow.
    The price sets only one end of the pairs searched (the price plus interest), so every
    expiry's value is the one read at the captured price.
    """
    chain, spot = _quoted("spy")
    as_captured = atm_sigma_by_expiry(chain, spot)
    assert all(v is not None for v in as_captured.values())
    for moved in (spot - 1.0, spot + 1.0):
        assert atm_sigma_by_expiry(chain, moved) == as_captured, moved


def test_with_no_step_the_atm_iv_is_read_at_the_options_own_forward() -> None:
    """The real SPY chain's same-day expiry (2026-11-12, 10:30 ET): no interest left, no step.

    As captured: 755: 23.888, 756: 23.215, 757: 22.580, 758: 22.220, 759: 21.678, falling at
    every strike. The mid prices are nearest at 758, the put the dearer, so the forward is in
    the pair 757 and 758; the value is the mean of those two strikes', 22.4002.
    """
    chain, spot = _quoted("spy")
    expiry = "2026-11-12"
    sigma = {k: _strike_sigma(chain, expiry, k) for k in (755.0, 756.0, 757.0, 758.0, 759.0)}
    assert list(sigma.values()) == sorted(sigma.values(), reverse=True), "no rise, as captured"
    gaps = {k: _mid_gap(chain, expiry, k) for k in sigma}
    assert min(gaps, key=lambda k: abs(gaps[k])) == 758.0 and gaps[758.0] < 0, gaps
    value = atm_sigma_by_expiry(chain, spot)[expiry]
    assert value is not None
    assert math.isclose(value, (sigma[757.0] + sigma[758.0]) / 2.0, rel_tol=1e-12)
    assert math.isclose(100.0 * value, 22.4002, abs_tol=5e-5)


def test_the_atm_iv_is_the_same_whichever_way_the_chain_is_ordered() -> None:
    """The real AMZN chain of 2026-11-12, 24 expiries, read forwards and backwards.

    Once the first contract met won, so the answer followed the chain's order.
    """
    chain, spot = _quoted("amzn")
    forwards = atm_sigma_by_expiry(chain, spot)
    assert forwards == atm_sigma_by_expiry(list(reversed(chain)), spot)
    assert len(forwards) == 24 and all(v is not None for v in forwards.values())


def test_a_chain_kept_without_its_quotes_has_no_atm_iv() -> None:
    """The real NFLX chain of 2026-10-07 was stored before a chain was kept with its quotes.

    No contract of it carries a bid or an ask, so no expiry's forward can be taken from its
    options: every expiry's value is unknown, never the strike nearest the price's.
    """
    chain = read_chain(NFLX.chain)
    assert all(c.bid is None and c.ask is None for c in chain)
    assert set(atm_sigma_by_expiry(chain, NFLX.spot).values()) == {None}


def test_the_atm_iv_is_unknown_without_a_rate_days_a_quote_or_a_volatility_at_the_forward() -> None:
    """INDUCED on the real SPY chain's 2026-12-18 expiry, one input withheld at a time.

    Schwab's rate; its days to the expiry; every call's bid sent as 0 (no strike quoted on both
    sides, so no forward from the options); the 760 call's volatility (a strike of the forward's
    own pair, 759 and 760). Each leaves that expiry unknown and every other expiry as it was.
    """
    chain, spot = _quoted("spy")
    expiry = "2026-12-18"
    as_sent = atm_sigma_by_expiry(chain, spot)
    assert as_sent[expiry] is not None
    withheld = {
        "the rate": lambda c: replace(c, interest_rate=None),
        "the days": lambda c: replace(c, days_to_expiry=None),
        "a call's bid": lambda c: replace(c, bid=0.0) if c.side == "CALL" else c,
        "a volatility": lambda c: (
            replace(c, volatility=None) if (c.side, c.strike) == ("CALL", 760.0) else c
        ),
    }
    for name, withhold in withheld.items():
        induced = [withhold(c) if c.expiry == expiry else c for c in chain]
        assert atm_sigma_by_expiry(induced, spot) == {**as_sent, expiry: None}, name


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
    # the forward, each with its call and its put and each leg's quote (its mid price beside it:
    # the call the dearer at 700 by 3.0, the put at 705 by 2.0, so the forward is between them)
    day = {"daysToExpiration": 1, "expirationDate": "2026-10-02", "interestRate": 4.0}
    legs = (
        ("CALL", 700.0, -999.0, 6.0),
        ("CALL", 705.0, 30.0, 3.5),
        ("PUT", 700.0, 24.0, 3.0),
        ("PUT", 705.0, 30.0, 5.5),
    )
    chain = read_chain(
        [
            {
                "putCall": side,
                "strikePrice": k,
                "quote": {"bidPrice": mid - 0.05, "askPrice": mid + 0.05, "volatility": iv},
                **day,
            }
            for side, k, iv, mid in legs
        ]
    )
    assert atm_sigma_by_expiry(chain, 700.0) == {"2026-10-02": None}
    sent = [replace(chain[0], volatility=26.0), *chain[1:]]
    assert atm_sigma_by_expiry(sent, 700.0) == {"2026-10-02": pytest.approx((0.25 + 0.30) / 2.0)}


def test_every_expiry_carries_its_atm_iv_by_the_one_rule() -> None:
    """The Trade Desk's Volatility card draws ATM IV by expiry (2026-09-28).

    One function for every expiry. Real AMZN chain of 2026-11-12, 24 expiries, each contract
    with its quote, valued at its capture (tests/real_chains.py).
    """
    chain, spot = _quoted("amzn")
    snap = compute_terrain("AMZN", chain, spot, now=quoted("amzn").now, sessions=sessions())
    by_exp = snap.atm_iv_pct_by_expiry
    assert list(by_exp) == sorted({c.expiry for c in chain})
    assert list(snap.pcr_by_expiry) == list(by_exp), "both card lines run nearest expiry first"
    assert all(v is not None and 0 < v < 1000 for v in by_exp.values())


def test_an_expiry_whose_contracts_carry_two_dtes_is_one_expiry() -> None:
    """One expiry's contracts sent with two daysToExpiration values are read as one expiry.

    INDUCED: the real AMZN chain of 2026-11-12 with the last contract of one expiry carrying no
    daysToExpiration (Schwab's -999, read as None); no capture holds one (every expiry of every
    captured chain carries one value). The expiry's put/call ratio is over all its contracts, its
    ATM IV is the expiry's as sent, and its DTE, two values sent, is unknown: a book of the one
    contract used to overwrite the expiry's.
    """
    chain, spot = _quoted("amzn")
    now = quoted("amzn").now
    expiry = sorted({c.expiry for c in chain})[2]
    last = max(i for i, c in enumerate(chain) if c.expiry == expiry)
    induced = [*chain[:last], replace(chain[last], days_to_expiry=None), *chain[last + 1 :]]
    snap = compute_terrain("AMZN", induced, spot, now=now, sessions=sessions())
    as_sent = compute_terrain("AMZN", chain, spot, now=now, sessions=sessions())
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
