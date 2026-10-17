"""Same-day levels: one producer, every ticker. The nearest expiry keeps its open interest
and implied volatility; gamma and delta are rebuilt to that ticker's option close today.
A name with no listed same-day expiry still gets them. The listed same-day pin is unchanged."""
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
    Each still gets a same-day pin. MRVL's listed same-day pin stays absent."""
    for book in (SPY_0DTE, MRVL, CRWD, TSLA):
        snap = compute_terrain(book.ticker, book.chain, book.spot, now=book.now).to_dict()
        same = snap["same_day"]
        assert set(same) == {name for name, _label in SAME_DAY_LEVELS}
        assert same["absolute_gamma_strike"] is not None, book.ticker
        assert same["call_wall"] is not None, book.ticker
        assert same["put_wall"] is not None, book.ticker

    mrvl = compute_terrain(MRVL.ticker, MRVL.chain, MRVL.spot, now=MRVL.now).to_dict()
    assert mrvl["zero_dte_abs_gamma_strike"] is None
    assert mrvl["same_day"]["absolute_gamma_strike"] != mrvl["absolute_gamma_strike"]


def test_open_interest_without_volatility_withholds_that_strike():
    """A second contract at the call wall, with open interest and no volatility, is not
    dropped. The strike stops being the call wall."""
    book = SPY_0DTE
    wall = compute_terrain(book.ticker, book.chain, book.spot, now=book.now).to_dict()
    strike = wall["same_day"]["call_wall"]
    assert strike is not None
    chain = [dict(ct) for ct in book.chain]
    seed = next(ct for ct in chain
                if str(ct.get("putCall") or "").upper() == "CALL"
                and float(ct["strikePrice"]) == float(strike))
    withheld = dict(seed)
    withheld["volatility"] = None
    withheld["openInterest"] = 100000
    chain.append(withheld)
    again = compute_terrain(book.ticker, chain, book.spot, now=book.now).to_dict()
    assert again["same_day"]["call_wall"] != strike
