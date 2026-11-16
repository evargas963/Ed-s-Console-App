"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on REAL captured chains (tests/real_chains.py, captured 2026-10-07), never a hand-built
one, each valued at its own capture instant, so the numbers are whatever the actual data produces.
"""

from __future__ import annotations

import json

import pytest

from calc.math_levels import GAMMA_FLIP_TRUSTED
from calc.terrain_engine import (
    TERRAIN_SCHEMA_VERSION,
    WALL_BREACHED,
    WALL_CONTAINS,
    atm_sigma_by_expiry,
    compute_implied_one_day_move,
    compute_terrain,
    nearest_position,
    nearest_strike,
    price_relations,
    wall_geometry_state,
)
from option_contract import read_chain, read_contract
from tests.real_chains import CRWD, MRVL, SPY_0DTE, spy_0dte_book
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


def test_narrow_0dte_slice_fails_closed_gate_retained() -> None:
    """RC-33: locking terrain to the full/wide chain must NOT weaken the narrow-chain protection.

    This real 40-contract 0DTE fixture spans only ~±1.3% (< the ±5% trust floor), so
    compute_terrain must fail closed to STAND_ASIDE — exactly the state the removed
    /api/analytics/state duplicate produced. One terrain source of truth keeps this fail-closed
    backstop.
    """
    chain, spot = spy_0dte_book()
    snap = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions())
    assert snap.profile, "the chain must price, so the NARROW gate (not an expiry) is tested"
    assert snap.confidence != GAMMA_FLIP_TRUSTED
    assert snap.regime == "UNAVAILABLE"
    assert snap.headline.startswith("No estimate"), snap.headline


def test_payload_is_json_serialisable() -> None:
    """It is served over HTTP; a non-serialisable field breaks the tab silently."""
    chain, spot = spy_0dte_book()
    payload = compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions()).to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["ticker"] == "SPY"
    assert "spot" in round_tripped and "confidence" in round_tripped
    assert "flip_note" in round_tripped


# ── RC-113: the institutional sigma band (SpotGamma-on-Bloomberg standard) ───────────────────


def test_implied_one_day_move_matches_the_named_formula() -> None:
    """EM = S x sigma_ATM x sqrt(1/252).

    The chain here is hand-built ON PURPOSE — a formula verification needs known inputs (the
    real-chain test below covers the live shape).
    """
    spot = 700.0
    # formula verification REQUIRES known inputs — the exactness
    # assertion below is meaningless on a live chain; the real-chain test covers the live shape.
    chain = read_chain(
        [
            {"putCall": "CALL", "strikePrice": 700.0, "volatility": 20.0, "daysToExpiration": 1},
            {"putCall": "PUT", "strikePrice": 700.0, "volatility": 24.0, "daysToExpiration": 1},
            # a farther expiry with wild IV must be IGNORED — front expiry only
            {"putCall": "CALL", "strikePrice": 700.0, "volatility": 80.0, "daysToExpiration": 30},
            # far-from-money same-expiry must lose to the ATM pair
            {"putCall": "PUT", "strikePrice": 650.0, "volatility": 99.0, "daysToExpiration": 1},
        ]
    )
    em = compute_implied_one_day_move(chain, spot, atm_sigma_by_expiry(chain, spot))
    assert em is not None
    sigma = (0.20 + 0.24) / 2.0
    assert abs(em["points"] - spot * sigma * (1.0 / 252.0) ** 0.5) < 1e-4
    assert em["iv_pct_atm"] == 22.0, "sigma must be the ATM call/put mean, Schwab percent /100"
    assert em["dte_used"] == 1
    assert "sqrt(1/252)" in em["method"], "the method label is part of the contract"


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
    front = min(k for k in forward if k[0] == chain[0].expiry)
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


def test_implied_move_fails_closed_without_usable_iv() -> None:
    """No usable ATM IV -> None. A fabricated sigma is worse than no sigma."""
    # fail-closed tests MUST feed malformed contracts on purpose.
    assert compute_implied_one_day_move([], 700.0, {}) is None
    assert compute_implied_one_day_move(None, 700.0, {}) is None
    negative = read_chain(
        [{"putCall": "CALL", "strikePrice": 700.0, "volatility": -5.0, "daysToExpiration": 1}]
    )
    assert (
        compute_implied_one_day_move(negative, 700.0, atm_sigma_by_expiry(negative, 700.0)) is None
    ), "negative IV must not produce a band"
    no_spot = read_chain(
        [{"putCall": "CALL", "strikePrice": 700.0, "volatility": 20.0, "daysToExpiration": 1}]
    )
    assert compute_implied_one_day_move(no_spot, None, {}) is None


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
    assert atm_sigma_by_expiry(chain, 700.0) == {("2026-10-02", 1): None}


def test_real_chain_carries_the_sigma_band() -> None:
    """The 1-day band uses the first expiry at least a day out (2026-09-27).

    A same-day-only chain has none; the CRWD chain (9 days out, valued at its capture) has one.
    """
    chain, spot = spy_0dte_book()
    assert compute_terrain("SPY", chain, spot, now=NOW, sessions=sessions()).implied_1d_move is None
    snap = compute_terrain(
        "CRWD", read_chain(CRWD.chain), CRWD.spot, now=CRWD.now, sessions=sessions()
    )
    em = snap.implied_1d_move
    assert em is not None, "the CRWD chain must yield a band (its ATM IV is present)"
    s = CRWD.spot
    # a one-day sigma is points, not pennies and not tens of percent of spot
    assert 0.0005 * s < em["points"] < 0.15 * s, em
    assert "implied_1d_move" in snap.to_dict(), "the payload must carry the band to the chart"


def test_every_expiry_carries_its_atm_iv_by_the_one_rule() -> None:
    """The Trade Desk's Volatility card draws ATM IV by expiry (2026-09-28).

    The ATM rule was applied to the front expiry only (the implied move); it is one function for
    every expiry, and the implied move reads its front entry. Real MRVL full chain, 20 expiries,
    valued at its capture (tests/real_chains.py).
    """
    chain = read_chain(MRVL.chain)
    snap = compute_terrain("MRVL", chain, MRVL.spot, now=MRVL.now, sessions=sessions())
    by_exp = snap.atm_iv_pct_by_expiry
    assert list(by_exp) == sorted({c.expiry for c in chain})
    assert list(snap.pcr_by_expiry) == list(by_exp), "both card lines run nearest expiry first"
    assert all(v is None or 0 < v < 1000 for v in by_exp.values())
    em = snap.implied_1d_move
    front = min(c.days_to_expiry for c in chain if c.days_to_expiry >= 1)
    front_exp = {c.expiry for c in chain if c.days_to_expiry == front}.pop()
    assert em is not None and by_exp[front_exp] == em["iv_pct_atm"]


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


def test_unavailable_terrain_does_not_fabricate_pin_score_stamps() -> None:
    snap = compute_terrain("SPY", None, SPY_0DTE.spot, now=NOW, sessions=sessions())
    assert snap.absolute_gamma_strike is None
    assert snap.pin_expected_moves is None
    assert snap.pin_strike_widths is None
    assert snap.pin_minutes_to_close is None
    assert snap.pin_candidate is None, "no chain must never yield a pin claim"
