"""The pin: the strike with the most open interest near the price, of the expiry closing today.

terrain_engine.pin_by_open_interest, published as TerrainSnapshot.pin_candidate with its distance
in expected moves and strike widths and its minutes to the close, and push.levels.pin_note on hover.
The definition is the pinning studies' (Ni, Pearson & Poteshman 2005; Golez & Jackwerth 2012;
Avellaneda & Lipkin 2003): open interest by strike of the expiry settling at today's close, the
distance z = ln(price/strike) / (sigma * sqrt(T)), the most open interest with |z| <= 1.

Real data: Schwab's SPY chains captured 2026-10-07 12:32 ET (one expiry, that day's) and
2026-11-09 11:06 ET (every expiry), and CRWD, TSLA, MRVL and NFLX of 2026-10-07 (no expiry that
day) and SPY at 16:17 ET on 2026-10-22 (past its close), through option_contract.read_chain; T
from time_et.time_to_expiry_years on Schwab's /markets answers. The expected values are worked
out here from the raw chain, apart from the code under test. Induced (named): the open interest
taken out of one contract, as Schwab leaves a field out.
"""

from __future__ import annotations

import math

import pytest

from calc.terrain_engine import compute_terrain, pin_by_open_interest
from option_contract import read_chain
from push import levels as push_levels
from tests.real_chains import (
    CRWD,
    MRVL,
    NFLX,
    SPY_0DTE,
    SPY_CLOSE,
    SPY_FULL,
    TSLA,
    book_ranks,
)
from time_et import option_close_product, sessions, time_to_expiry_years


def _expected(raw: list[dict], spot: float, today: str, t: float) -> tuple[float, float, float]:
    """(strike, z, strike widths) worked out from Schwab's raw contracts."""
    oi: dict[float, float] = {}
    iv: dict[float, list[float]] = {}
    strikes: set[float] = set()
    for c in raw:
        if c["expirationDate"][:10] != today or c["settlementType"] == "A":
            continue
        k = float(c["strikePrice"])
        strikes.add(k)
        oi[k] = oi.get(k, 0.0) + float(c["openInterest"])
        if c["volatility"] > 0:
            iv.setdefault(k, []).append(c["volatility"] / 100.0)
    ranked = []
    for k, n in oi.items():
        if k in iv:
            z = math.log(spot / k) / (sum(iv[k]) / len(iv[k]) * math.sqrt(t))
            if abs(z) <= 1.0:
                ranked.append((n, -abs(z), k, z))
    _n, _d, strike, z = max(ranked)
    gap = min(abs(strike - k) for k in strikes if k != strike)
    return strike, z, (spot - strike) / gap


@pytest.mark.parametrize(
    ("chain", "strike"),
    [(SPY_0DTE, 775.0), (SPY_FULL, 750.0)],
    ids=["spy_2026_10_07", "spy_2026_11_09"],
)
def test_the_pin_is_the_most_open_interest_within_one_expected_move(chain, strike):
    today = chain.now.date().isoformat()
    held = sessions()
    product = option_close_product("SPY")
    t = time_to_expiry_years(today, chain.now, sessions=held, product=product)
    assert t is not None and t > 0
    contracts = read_chain(chain.chain)
    pin = pin_by_open_interest(contracts, chain.spot, now=chain.now, sessions=held, product=product)
    want_strike, want_z, want_widths = _expected(chain.chain, chain.spot, today, t)
    assert pin is not None and pin.strike == want_strike == strike
    assert pin.expected_moves == pytest.approx(want_z, rel=1e-12)
    assert abs(pin.expected_moves) <= 1.0
    assert pin.strike_widths == pytest.approx(want_widths, rel=1e-12)
    assert pin.minutes_to_close == pytest.approx(t * 365 * 24 * 60, rel=1e-12)
    snap = compute_terrain("SPY", contracts, chain.spot, now=chain.now, sessions=held)
    assert snap.pin_candidate == strike
    assert (snap.pin_expected_moves, snap.pin_strike_widths, snap.pin_minutes_to_close) == (
        pin.expected_moves,
        pin.strike_widths,
        pin.minutes_to_close,
    )


def test_the_pin_is_not_the_largest_gamma_strike():
    """Abs Γ and the pin are two measures: on SPY 2026-11-09 they are 605 and 750."""
    snap = compute_terrain(
        "SPY", read_chain(SPY_FULL.chain), SPY_FULL.spot, now=SPY_FULL.now, sessions=sessions()
    )
    assert (snap.absolute_gamma_strike, snap.pin_candidate) == (605.0, 750.0)
    worked_out = book_ranks(SPY_FULL.chain, SPY_FULL.spot)["absolute_gamma_strike"]
    assert snap.absolute_gamma_strike == worked_out


@pytest.mark.parametrize(
    ("ticker", "chain"),
    [
        ("CRWD", CRWD),
        ("TSLA", TSLA),
        ("MRVL", MRVL),
        ("NFLX", NFLX),
        ("SPY", SPY_CLOSE),
    ],
    ids=["crwd", "tsla", "mrvl", "nflx", "spy_after_the_close"],
)
def test_no_pin_without_an_expiry_closing_ahead_today(ticker, chain):
    """No expiry that day, or the close already past: no pin, never another expiry's strike."""
    snap = compute_terrain(
        ticker, read_chain(chain.chain), chain.spot, now=chain.now, sessions=sessions()
    )
    assert snap.pin_candidate is None
    assert snap.pin_expected_moves is None and snap.pin_minutes_to_close is None
    assert push_levels.pin_note(snap) is None


def test_a_strike_whose_open_interest_is_not_known_is_not_ranked():
    """Induced: the 775 put's open interest taken out. 775 is not ranked; the next strike is."""
    raw = [dict(c) for c in SPY_0DTE.chain]
    del next(c for c in raw if c["strikePrice"] == 775.0 and c["putCall"] == "PUT")["openInterest"]
    held = sessions()
    product = option_close_product("SPY")
    pin = pin_by_open_interest(
        read_chain(raw), SPY_0DTE.spot, now=SPY_0DTE.now, sessions=held, product=product
    )
    today = SPY_0DTE.now.date().isoformat()
    t = time_to_expiry_years(today, SPY_0DTE.now, sessions=held, product=product)
    rest = [c for c in SPY_0DTE.chain if c["strikePrice"] != 775.0]
    assert pin is not None and pin.strike != 775.0
    assert pin.strike == _expected(rest, SPY_0DTE.spot, today, t)[0]
    # its neighbour 775 is still a listed strike, so the width is the chain's 1.00
    assert pin.strike_widths == pytest.approx(SPY_0DTE.spot - pin.strike, rel=1e-12)


def test_the_note_says_how_far_the_price_is_and_how_long_is_left():
    snap = compute_terrain(
        "SPY", read_chain(SPY_0DTE.chain), SPY_0DTE.spot, now=SPY_0DTE.now, sessions=sessions()
    )
    assert push_levels.pin_note(snap) == (
        "Most open interest within one expected move, of the expiry settling at today's close. "
        "Price 0.73 expected moves (1.6 strike widths) above it; 223 minutes to the close."
    )
