"""Same-day levels: one producer, every ticker. The nearest expiry keeps its open interest
and implied volatility; gamma and delta are rebuilt to that ticker's option close today.
A name with no listed same-day expiry still gets them. That pin is the only 0DTE pin."""

from __future__ import annotations

from terrain_engine import SAME_DAY_LEVELS, compute_terrain
from tests.real_chains import CRWD, MRVL, SPY_0DTE, TSLA
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


def test_open_interest_without_volatility_withholds_that_strike():
    """The captured call at the same-day call wall, with its volatility absent and its own
    open interest kept, is put back on the captured chain. That strike is not a same-day level."""
    book = SPY_0DTE
    strike = compute_terrain(book.ticker, book.chain, book.spot, now=book.now).to_dict()[
        "same_day"
    ]["call_wall"]
    assert strike is not None
    chain = [dict(ct) for ct in book.chain]
    seed = next(
        ct
        for ct in chain
        if ct.get("putCall") == "CALL" and float(ct["strikePrice"]) == float(strike)
    )
    absent = dict(seed)
    absent["volatility"] = None
    chain.append(absent)
    same = compute_terrain(book.ticker, chain, book.spot, now=book.now).to_dict()["same_day"]
    for name in (
        "call_wall",
        "put_wall",
        "absolute_gamma_strike",
        "net_gex_peak",
        "hvp",
        "lvp",
        "key_delta_strike",
        "call_charm_wall",
        "put_charm_wall",
    ):
        assert same[name] != float(strike), name
