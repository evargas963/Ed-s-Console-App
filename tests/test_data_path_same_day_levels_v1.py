"""Same-day levels: one producer, every ticker.

The levels of the nearest listed expiry alone, by the whole book's own producers. An expiry that
settles today is read from Schwab's gamma and delta as sent. With none today, the next listed
expiry keeps its open interest and implied volatility; gamma and delta are rebuilt to that
ticker's option close today. A name with no listed same-day expiry still gets them. That pin is
the only 0DTE pin.
"""

from __future__ import annotations

import math
import statistics

import pytest

import terrain_engine
from option_contract import read_chain
from terrain_engine import SAME_DAY_LEVELS, compute_terrain
from tests.real_chains import CRWD, MRVL, NFLX, SPY_0DTE, SPY_FULL, TSLA
from time_et import EQUITY_OPTIONS, ET, INDEX_OPTIONS, option_close_product, time_to_expiry_years


def test_the_option_close_follows_the_ticker():
    """SPY, QQQ, IWM and an index stop at the index close. A stock stops at the equity close."""
    assert option_close_product("SPY") == INDEX_OPTIONS
    assert option_close_product("QQQ") == INDEX_OPTIONS
    assert option_close_product("IWM") == INDEX_OPTIONS
    assert option_close_product("$SPX") == INDEX_OPTIONS
    assert option_close_product("DELL") == EQUITY_OPTIONS
    assert option_close_product("MRVL") == EQUITY_OPTIONS
    day = SPY_0DTE.now.astimezone(ET).date().isoformat()
    spy_left = time_to_expiry_years(day, SPY_0DTE.now, product=option_close_product("SPY"))
    dell_left = time_to_expiry_years(day, SPY_0DTE.now, product=option_close_product("DELL"))
    assert spy_left is not None and dell_left is not None and spy_left > dell_left


def test_every_ticker_gets_same_day_levels_from_its_nearest_expiry():
    """SPY 2026-10-07 12:32 ET expires that day. MRVL, CRWD and TSLA that morning do not.

    Each still gets a same-day pin. There is no second listed-expiry pin beside it.
    """
    for book in (SPY_0DTE, MRVL, CRWD, TSLA):
        snap = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now)
        same = snap.to_dict()["same_day"]
        assert set(same) == {name for name, _label in SAME_DAY_LEVELS}
        assert same["absolute_gamma_strike"] is not None, book.ticker
        assert same["call_wall"] is not None, book.ticker
        assert same["put_wall"] is not None, book.ticker

    mrvl = compute_terrain(MRVL.ticker, read_chain(MRVL.chain), MRVL.spot, now=MRVL.now).to_dict()
    assert "zero_dte_abs_gamma_strike" not in mrvl
    assert mrvl["same_day"]["absolute_gamma_strike"] != mrvl["absolute_gamma_strike"]


def test_a_same_day_expiry_reads_the_charm_map_already_priced():
    """SPY expires 2026-10-07, the day this chain was captured.

    The rail charm is that expiry's map. Charm is calculated once for the expiry, not again for
    the rail.
    """
    held = SPY_0DTE
    calls = {"n": 0}
    real = terrain_engine.compute_charm_by_strike

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    terrain_engine.compute_charm_by_strike = counting
    try:
        snap = terrain_engine.compute_terrain(
            held.ticker, read_chain(held.chain), held.spot, now=held.now
        )
    finally:
        terrain_engine.compute_charm_by_strike = real
    assert calls["n"] == len(snap.charm_by_expiry)
    assert snap.same_day["call_charm_wall"] == 780.0
    assert snap.same_day["put_charm_wall"] == 779.0


def test_a_later_front_expiry_keeps_its_charm_at_todays_close():
    """TSLA on 2026-10-07 expires 2026-10-09.

    The rail charm is that front expiry at today's close. It is not the charm of the Friday
    settlement.
    """
    snap = compute_terrain(TSLA.ticker, read_chain(TSLA.chain), TSLA.spot, now=TSLA.now)
    assert snap.same_day["call_charm_wall"] == 372.5
    assert snap.same_day["put_charm_wall"] == 380.0
    assert snap.call_charm_wall == 390.0
    assert snap.put_charm_wall == 370.0


@pytest.mark.parametrize(
    ("book", "pin"), [(CRWD, 270.0), (MRVL, 285.0), (NFLX, 69.0), (TSLA, 375.0)]
)
def test_gamma_rebuilt_to_todays_close_is_not_refused_at_the_listed_expiry(book, pin):
    """A front expiry later than today: gamma rebuilt to today's close is largest at the price.

    It is above any gamma the contract can have at its listed expiry. The strike there stays a
    level.
    """
    same = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now).same_day
    assert same["absolute_gamma_strike"] == pin


def _as_sent(contract: dict, _book) -> tuple[float, float]:
    return contract["gamma"], contract["delta"]


def _at_todays_close(contract: dict, book) -> tuple[float, float]:
    """Return the contract's gamma and delta as if it expired at today's option close.

    Black-Scholes-Merton (Hull, ch. 19) on Schwab's volatility, rate and dividend yield as sent,
    each a percent.
    """
    day = book.now.astimezone(ET).date().isoformat()
    t = time_to_expiry_years(day, book.now, product=option_close_product(book.ticker))
    sigma, r, q = (contract[f] / 100.0 for f in ("volatility", "interestRate", "dividendYield"))
    vt = sigma * math.sqrt(t)
    d1 = (math.log(book.spot / contract["strikePrice"]) + (r - q + sigma**2 / 2.0) * t) / vt
    normal = statistics.NormalDist()
    cdf = normal.cdf(d1)
    discount = math.exp(-q * t)
    return (
        discount * normal.pdf(d1) / (book.spot * vt),
        discount * (cdf if contract["putCall"] == "CALL" else cdf - 1.0),
    )


def _front_walls(book, greeks) -> dict[str, float]:
    """Return the nearest expiry's walls, worked out from the raw chain outside the program.

    Per contract, the size of gamma x open interest x multiplier x spot^2 x 1% (GEX) and of
    delta x open interest x multiplier x spot (DEX). Call wall: the strike of the largest call
    GEX. Put wall: of the largest put GEX. Absolute gamma: of the largest call GEX + put GEX
    (SpotGamma). Key delta: of the largest call DEX + put DEX. Each captured front expiry lists
    one call and one put at every strike, and Schwab sent every field read here as a value: none
    absent, none -999.
    """
    day = book.now.astimezone(ET).date().isoformat()
    front = min(c["expirationDate"][:10] for c in book.chain if c["expirationDate"][:10] >= day)
    gex, dex = {}, {}
    for c in book.chain:
        if c["expirationDate"][:10] == front:
            gamma, delta = greeks(c, book)
            size = c["openInterest"] * c["multiplier"]
            gex[c["putCall"], c["strikePrice"]] = abs(gamma) * size * book.spot**2 * 0.01
            dex[c["putCall"], c["strikePrice"]] = abs(delta) * size * book.spot
    strikes = sorted({strike for _side, strike in gex})
    return {
        "call_wall": max(strikes, key=lambda k: gex["CALL", k]),
        "put_wall": max(strikes, key=lambda k: gex["PUT", k]),
        "absolute_gamma_strike": max(strikes, key=lambda k: gex["CALL", k] + gex["PUT", k]),
        "key_delta_strike": max(strikes, key=lambda k: dex["CALL", k] + dex["PUT", k]),
    }


@pytest.mark.parametrize("book", [SPY_0DTE, SPY_FULL], ids=lambda b: f"{b.now:%Y-%m-%d}")
def test_an_expiry_that_settles_today_is_read_from_schwabs_greeks_as_sent(book):
    """SPY lists an expiry on 2026-10-07 (its whole chain) and on 2026-11-09 (one of 35).

    Its walls are those of Schwab's gamma and delta as sent. On 2026-10-07 the put wall as sent
    is 777; priced to the close it would be 775.
    """
    same = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now).same_day
    expected = _front_walls(book, _as_sent)
    assert {name: same[name] for name in expected} == expected


@pytest.mark.parametrize("book", [CRWD, MRVL, NFLX, TSLA], ids=lambda b: b.ticker)
def test_with_no_expiry_today_the_next_one_is_priced_to_todays_close(book):
    """None of the four lists an expiry on 2026-10-07; Schwab sends no Greek at that day's close.

    The walls are those of the next expiry's gamma and delta at today's close. On each chain they
    differ from the walls of Schwab's gamma and delta as sent.
    """
    same = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now).same_day
    expected = _front_walls(book, _at_todays_close)
    assert {name: same[name] for name in expected} == expected
    assert expected != _front_walls(book, _as_sent)


def _with_a_call_at(strike: float, book) -> dict:
    """Induced test condition: the captured call at `strike` is put back on the captured chain.

    The call has its volatility absent and its own open interest kept. No capture holds a
    contract that cannot be rebuilt beside a good one on the other side.
    """
    chain = [dict(ct) for ct in book.chain]
    seed = next(
        ct
        for ct in chain
        if ct.get("putCall") == "CALL" and float(ct["strikePrice"]) == float(strike)
    )
    absent = dict(seed)
    absent["volatility"] = None
    chain.append(absent)
    snap = compute_terrain(book.ticker, read_chain(chain), book.spot, now=book.now)
    return snap.to_dict()["same_day"]


def _same_day(name: str, book) -> float:
    snap = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now)
    return snap.same_day[name]


def test_a_contract_with_no_rebuilt_gamma_leaves_its_side_and_the_strike_total_unknown():
    """TSLA's front expiry is later than today, so its gamma is rebuilt.

    A call that cannot be rebuilt is put at each level's strike in turn. No level stays on, or
    moves to, that strike.
    """
    names = ("call_wall", "absolute_gamma_strike", "hvp", "lvp", "key_delta_strike")
    same = compute_terrain(TSLA.ticker, read_chain(TSLA.chain), TSLA.spot, now=TSLA.now).same_day
    for strike in {same[name] for name in names}:
        after = _with_a_call_at(strike, TSLA)
        for name in names:
            assert after[name] != strike, (strike, name)


def test_a_contract_with_no_rebuilt_gamma_leaves_the_other_side_known():
    strike = _same_day("put_wall", TSLA)
    assert _with_a_call_at(strike, TSLA)["put_wall"] == strike


@pytest.mark.parametrize("book", [SPY_0DTE, TSLA])
def test_a_contract_with_no_rebuilt_gamma_leaves_only_its_sides_charm_unknown(book):
    """SPY's front expiry settles today (the held map), TSLA's does not (the rebuilt map)."""
    strike = _same_day("call_charm_wall", book)
    assert _with_a_call_at(strike, book)["call_charm_wall"] != strike
    strike = _same_day("put_charm_wall", book)
    assert _with_a_call_at(strike, book)["put_charm_wall"] == strike
