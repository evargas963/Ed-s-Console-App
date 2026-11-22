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
from tests.real_chains import MRVL, NFLX, SPY_0DTE, spy_0dte_book
from time_et import sessions

NOW = SPY_0DTE.now


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


def test_a_price_midway_between_two_strikes_takes_the_lower_strikes_iv_in_any_order() -> None:
    """The real SPY chain at a price exactly between two of its listed strikes.

    Each leg's IV is the lower strike's (nearest_strike's rule), whichever way the chain is
    ordered: once the first contract met won, so the answer followed the chain's order.
    """
    chain, spot = spy_0dte_book()
    strikes = sorted({c.strike for c in chain if c.expiry == chain[0].expiry})
    lower = max(k for k in strikes if k <= spot)
    upper = min(k for k in strikes if k > lower)
    midway = (lower + upper) / 2.0
    assert nearest_strike(strikes, midway) == lower
    at_lower = atm_sigma_by_expiry([c for c in chain if c.strike != upper], midway)
    forward = atm_sigma_by_expiry(chain, midway)
    assert forward == atm_sigma_by_expiry(list(reversed(chain)), midway)
    front = chain[0].expiry
    assert forward[front] is not None and forward[front] == at_lower[front]


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
    (operator 2026-10-01: "we use what schwab gives us and we display it").
    """
    # the rule needs a known ATM contract with no IV beside a priced one
    chain = read_chain(
        [
            {
                "putCall": "CALL",
                "strikePrice": 700.0,
                "volatility": -999.0,
                "daysToExpiration": 1,
                "expirationDate": "2026-10-02",
            },
            {
                "putCall": "CALL",
                "strikePrice": 705.0,
                "volatility": 30.0,
                "daysToExpiration": 1,
                "expirationDate": "2026-10-02",
            },
            {
                "putCall": "PUT",
                "strikePrice": 700.0,
                "volatility": 24.0,
                "daysToExpiration": 1,
                "expirationDate": "2026-10-02",
            },
        ]
    )
    assert atm_sigma_by_expiry(chain, 700.0) == {"2026-10-02": None}


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
