"""Same-day levels: one producer, every ticker. The nearest expiry keeps its open interest
and implied volatility; gamma and delta are rebuilt to that ticker's option close today.
A name with no listed same-day expiry still gets them. That pin is the only 0DTE pin."""

from __future__ import annotations

import pytest

from terrain_engine import SAME_DAY_LEVELS, compute_terrain
from tests.real_chains import CRWD, MRVL, NFLX, SPY_0DTE, TSLA
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
    Each still gets a same-day pin. There is no second listed-expiry pin beside it."""
    for book in (SPY_0DTE, MRVL, CRWD, TSLA):
        snap = compute_terrain(book.ticker, book.chain, book.spot, now=book.now).to_dict()
        same = snap["same_day"]
        assert set(same) == {name for name, _label in SAME_DAY_LEVELS}
        assert same["absolute_gamma_strike"] is not None, book.ticker
        assert same["call_wall"] is not None, book.ticker
        assert same["put_wall"] is not None, book.ticker

    mrvl = compute_terrain(MRVL.ticker, MRVL.chain, MRVL.spot, now=MRVL.now).to_dict()
    assert "zero_dte_abs_gamma_strike" not in mrvl
    assert mrvl["same_day"]["absolute_gamma_strike"] != mrvl["absolute_gamma_strike"]


def test_a_same_day_expiry_reads_the_charm_map_already_priced():
    """SPY expires 2026-10-07, the day this chain was captured. The rail charm is that
    expiry's map. Charm is calculated once for the expiry, not again for the rail."""
    import terrain_engine

    held = SPY_0DTE
    calls = {"n": 0}
    real = terrain_engine.compute_charm_by_strike

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    terrain_engine.compute_charm_by_strike = counting
    try:
        snap = terrain_engine.compute_terrain(held.ticker, held.chain, held.spot, now=held.now)
    finally:
        terrain_engine.compute_charm_by_strike = real
    assert calls["n"] == len(snap.charm_by_expiry)
    assert snap.same_day["call_charm_wall"] == 780.0
    assert snap.same_day["put_charm_wall"] == 779.0


def test_a_later_front_expiry_keeps_its_charm_at_todays_close():
    """TSLA on 2026-10-07 expires 2026-10-09. The rail charm is that front expiry at today's
    close. It is not the charm of the Friday settlement."""
    snap = compute_terrain(TSLA.ticker, TSLA.chain, TSLA.spot, now=TSLA.now)
    assert snap.same_day["call_charm_wall"] == 372.5
    assert snap.same_day["put_charm_wall"] == 380.0
    assert snap.call_charm_wall == 390.0
    assert snap.put_charm_wall == 370.0


@pytest.mark.parametrize(
    ("book", "pin"), [(CRWD, 270.0), (MRVL, 285.0), (NFLX, 69.0), (TSLA, 375.0)]
)
def test_gamma_rebuilt_to_todays_close_is_not_refused_at_the_listed_expiry(book, pin):
    """A front expiry later than today: gamma rebuilt to today's close is largest at the price,
    above any gamma the contract can have at its listed expiry. The strike there stays a level."""
    same = compute_terrain(book.ticker, book.chain, book.spot, now=book.now).same_day
    assert same["absolute_gamma_strike"] == pin


def _with_a_call_at(strike: float, book=SPY_0DTE) -> dict:
    """Induced test condition: the captured call at `strike`, its volatility absent and its own
    open interest kept, is put back on the captured chain. No capture holds a contract that cannot
    be rebuilt beside a good one on the other side."""
    chain = [dict(ct) for ct in book.chain]
    seed = next(
        ct
        for ct in chain
        if ct.get("putCall") == "CALL" and float(ct["strikePrice"]) == float(strike)
    )
    absent = dict(seed)
    absent["volatility"] = None
    chain.append(absent)
    return compute_terrain(book.ticker, chain, book.spot, now=book.now).to_dict()["same_day"]


def _same_day(name: str, book=SPY_0DTE) -> float:
    return compute_terrain(book.ticker, book.chain, book.spot, now=book.now).same_day[name]


def test_a_contract_with_no_rebuilt_gamma_leaves_its_side_and_the_strike_total_unknown():
    strike = _same_day("call_wall")
    same = _with_a_call_at(strike)
    for name in (
        "call_wall",
        "absolute_gamma_strike",
        "net_gex_peak",
        "hvp",
        "lvp",
        "key_delta_strike",
    ):
        assert same[name] != float(strike), name


def test_a_contract_with_no_rebuilt_gamma_leaves_the_other_side_known():
    strike = _same_day("put_wall")
    assert _with_a_call_at(strike)["put_wall"] == strike


@pytest.mark.parametrize("book", [SPY_0DTE, TSLA])
def test_a_contract_with_no_rebuilt_gamma_leaves_only_its_sides_charm_unknown(book):
    """SPY's front expiry settles today (the held map), TSLA's does not (the rebuilt map)."""
    strike = _same_day("call_charm_wall", book)
    assert _with_a_call_at(strike, book)["call_charm_wall"] != strike
    strike = _same_day("put_charm_wall", book)
    assert _with_a_call_at(strike, book)["put_charm_wall"] == strike
