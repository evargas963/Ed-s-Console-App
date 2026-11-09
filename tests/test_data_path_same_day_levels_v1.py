"""Same-day levels: one producer, every ticker.

The levels of the nearest listed expiry alone (today's, else the next listed), from Schwab's
gamma and delta as sent, by the whole book's own producers. A name with no listed same-day expiry
still gets them. That pin is the only 0DTE pin.
"""

from __future__ import annotations

import math

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


def test_a_later_front_expiry_reads_its_own_charm_map():
    """TSLA on 2026-10-07: its one listed expiry is 2026-10-09.

    The rail charm is that expiry's map, priced to its own settlement as every expiry's is: on a
    chain of that one expiry, the whole book's charm walls.
    """
    snap = compute_terrain(TSLA.ticker, read_chain(TSLA.chain), TSLA.spot, now=TSLA.now)
    assert set(snap.charm_by_expiry) == {"2026-10-09"}
    assert snap.same_day["call_charm_wall"] == snap.call_charm_wall == 390.0
    assert snap.same_day["put_charm_wall"] == snap.put_charm_wall == 370.0


def _number(x):
    """A value Schwab sent as a number, else None (rule 2: -999, text, NaN)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return None if not math.isfinite(x) or x == -999 else float(x)


def _front_walls(book) -> dict[str, float | None]:
    """The front expiry's walls and key strikes from Schwab's gamma and delta as sent.

    Worked out here from the raw chain, independently of the program: per strike and side,
    gamma x open interest x multiplier x spot^2 x 1% (GEX) and delta x open interest x
    multiplier x spot (DEX); a side with a contract whose open interest or Greek is not known is
    not known. Call wall: the largest |call GEX|; put wall: the largest |put GEX|; absolute gamma:
    the largest |call GEX| + |put GEX| (SpotGamma); key delta: the largest |call DEX| + |put DEX|.
    """
    today = book.now.date().isoformat()
    front = min(c["expirationDate"][:10] for c in book.chain if c["expirationDate"][:10] >= today)
    side: dict[tuple[float, str], list] = {}
    for c in book.chain:
        if c["expirationDate"][:10] != front:
            continue
        k, oi, mult = (_number(c.get(f)) for f in ("strikePrice", "openInterest", "multiplier"))
        g, d = _number(c.get("gamma")), _number(c.get("delta"))
        if c.get("volatility") == -999:  # Schwab's no-value volatility voids its Greeks
            g = d = None
        acc = side.setdefault((k, c["putCall"]), [0.0, 0.0])
        if oi == 0:
            continue
        for i, greek, scale in ((0, g, book.spot**2 * 0.01), (1, d, book.spot)):
            known = acc[i] is not None and None not in (greek, oi, mult)
            acc[i] = acc[i] + greek * oi * mult * scale if known else None
    strikes = sorted({k for k, _ in side})

    def leg(k, s, i):
        v = side.get((k, s), [0.0, 0.0])[i]
        return None if v is None else abs(v)

    def best(value):
        known = {k: v for k in strikes if (v := value(k)) is not None and v > 0}
        return max(known, key=known.get) if known else None

    def both(i):
        def value(k):
            c, p = leg(k, "CALL", i), leg(k, "PUT", i)
            return None if c is None or p is None else c + p

        return value

    return {
        "call_wall": best(lambda k: leg(k, "CALL", 0)),
        "put_wall": best(lambda k: leg(k, "PUT", 0)),
        "absolute_gamma_strike": best(both(0)),
        "key_delta_strike": best(both(1)),
    }


@pytest.mark.parametrize(
    "book", [SPY_0DTE, CRWD, MRVL, NFLX, TSLA, SPY_FULL], ids=lambda b: f"{b.ticker}-{b.now:%m%d}"
)
def test_same_day_levels_are_schwabs_gamma_and_delta_as_sent(book):
    """Today's expiry (SPY 2026-10-07 and 2026-11-09) and a later one (CRWD, MRVL, NFLX, TSLA).

    Every contract's gamma and delta are Schwab's as sent, an expiry that settles today included:
    nothing is repriced to today's close.
    """
    same = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now).same_day
    expected = _front_walls(book)
    assert all(v is not None for v in expected.values()), expected
    assert {name: same[name] for name in expected} == expected


def _with_a_call_at(strike: float, book=SPY_0DTE) -> dict:
    """Induced test condition: the captured call at `strike` is put back on the captured chain.

    The call has its volatility absent and its own open interest kept, so its charm cannot be
    priced. No capture holds a contract that cannot be priced beside a good one on the other side.
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


def _same_day(name: str, book=SPY_0DTE) -> float:
    snap = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now)
    return snap.same_day[name]


@pytest.mark.parametrize("book", [SPY_0DTE, TSLA])
def test_a_contract_with_no_rebuilt_gamma_leaves_only_its_sides_charm_unknown(book):
    """SPY's front expiry settles today, TSLA's later: each reads its own expiry's charm map."""
    strike = _same_day("call_charm_wall", book)
    assert _with_a_call_at(strike, book)["call_charm_wall"] != strike
    strike = _same_day("put_charm_wall", book)
    assert _with_a_call_at(strike, book)["put_charm_wall"] == strike
