"""How often each fixed level held: liquidity_value_engine.hold_counts and the liquidity rows.

Osler (2000, Federal Reserve Bank of New York Economic Policy Review 6(2)): a touch is a 1-minute
bar reaching the level from one side, once per approach; it held when the close 15 minutes later is
still on that side; random levels counted the same way are the baseline.

Real data: Schwab's /pricehistory answers for SPY and TSLA captured 2026-10-07 (10 days of 1-minute
bars with extended hours, and daily candles;
tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json), and Schwab's /markets answers
(tests/conftest.py). The expected counts are worked out here from the raw candles, apart from the
code under test.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

import server
from calc.liquidity_value_engine import (
    HOLD_MIN_TOUCHES,
    HoldCount,
    _touch_outcomes,
    bars_from_candles,
    hold_counts,
    hold_window,
    wilson_interval,
)
from calc.micro_structure import Candle
from push import liquidity as push_liquidity
from state import bar_store, price_level_store
from tests.feed_live_helper import price_history
from time_et import ET, session, sessions

#: after the 2026-10-06 close and before the 2026-10-07 open: every captured day but the 7th closed
EVENING = datetime(2026, 10, 7, 8, 0, tzinfo=ET)


def _answer(symbol: str, series: str) -> dict:
    body = price_history(symbol, series)["body"]
    return body if isinstance(body, dict) else json.loads(body)


def _candles(symbol: str, series: str) -> list[Candle]:
    return [
        Candle(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
        for c in _answer(symbol, series)["candles"]
    ]


def _closed_days(symbol: str, now: datetime) -> dict[date, list[dict]]:
    """Each session closed at `now`: its regular-hours raw candles, oldest first, with times."""
    raw = _answer(symbol, "1m")["candles"]
    days: dict[date, list[dict]] = {}
    for c in sorted(raw, key=lambda c: c["datetime"]):
        dt = datetime.fromtimestamp(c["datetime"] / 1000, ET)
        s = session(dt.date().isoformat())
        if s is None or not s.regular:
            continue
        o, cl = s.regular[0][0], s.regular[-1][1]
        if o <= dt < cl and cl <= now:
            days.setdefault(dt.date(), []).append({**c, "dt": dt})
    return days


def _baseline(days: dict[date, list[dict]], d: date, minutes: int) -> tuple[int, int]:
    """(touches, holds) on session `d` of Osler's random levels, by the same rule from the open.

    100 levels evenly spaced (each in the middle of its 1/100 slice) over the open +- the largest
    open-to-high or open-to-low move of a session of the same month.
    """
    o = days[d][0]["open"]
    half = max(
        max(
            max(b["high"] for b in rth) - rth[0]["open"],
            rth[0]["open"] - min(b["low"] for b in rth),
        )
        for e, rth in days.items()
        if (e.year, e.month) == (d.year, d.month)
    )
    found = [
        _one_day(days[d], o - half + half * (2 * k + 1) / 100, days[d][0]["dt"], minutes)
        for k in range(100)
    ]
    return sum(t for t, _h in found), sum(h for _t, h in found)


def _expected(symbol: str, level_of, minutes: int, after_open: int = 0) -> HoldCount:
    """A level's counts over the closed sessions, from the raw candles by the stated rule.

    Its baseline is counted over the sessions the level existed.
    """
    days = _closed_days(symbol, EVENING)
    found = [
        (
            *_one_day(rth, level, rth[0]["dt"] + timedelta(minutes=after_open), minutes),
            *_baseline(days, d, minutes),
        )
        for d, rth in days.items()
        if (level := level_of(d, rth)) is not None
    ]
    return HoldCount(*(sum(row[i] for row in found) for i in range(4)))


def _one_day(rth: list[dict], level: float, start: datetime, minutes: int) -> tuple[int, int]:
    close_at = {b["dt"]: b["close"] for b in rth}
    touches = holds = 0
    armed = True
    for prev, bar in zip(rth, rth[1:], strict=False):
        if not bar["low"] <= level <= bar["high"]:
            armed = True
        elif bar["dt"] < start or not armed:
            armed = False
        elif prev["close"] != level:
            armed = False
            side = 1 if prev["close"] > level else -1
            later = bar["dt"] + timedelta(minutes=minutes)
            if later in close_at:
                touches += 1
                holds += (close_at[later] - level) * side > 0
    return touches, holds


def _prior_daily(symbol: str, d: date, field: str) -> float | None:
    before = [
        c
        for c in _answer(symbol, "1d")["candles"]
        if datetime.fromtimestamp(c["datetime"] / 1000, ET).date() < d
    ]
    return max(before, key=lambda c: c["datetime"])[field] if before else None


def _first_15_high(_d: date, rth: list[dict]) -> float:
    return max(b["high"] for b in rth if b["dt"] < rth[0]["dt"] + timedelta(minutes=15))


@pytest.mark.parametrize("symbol", ["SPY", "TSLA"])
@pytest.mark.parametrize("minutes", [15, 30])
def test_each_level_touch_and_hold_is_counted_by_the_stated_rule(symbol, minutes):
    got = hold_counts(
        bars_from_candles(_candles(symbol, "1m")),
        _candles(symbol, "1d"),
        EVENING,
        sessions=sessions(),
    )
    for lid, field in (("PDH", "high"), ("PDL", "low"), ("PDC", "close")):
        want = _expected(symbol, lambda d, _r, f=field: _prior_daily(symbol, d, f), minutes)
        assert got[lid][minutes] == want, lid
    want = _expected(symbol, _first_15_high, minutes, after_open=15)
    assert got["ORB_HIGH"][minutes] == want
    for lid, by in got.items():
        c = by[minutes]
        assert 0 <= c.holds <= c.touches and 0 <= c.baseline_holds <= c.baseline_touches, lid


@pytest.mark.parametrize("symbol", ["SPY", "TSLA"])
def test_a_level_at_each_price_a_bar_closed_at_is_counted_by_the_stated_rule(symbol):
    """Every closed session, every price one of its bars closed at as the level, 15 minutes.

    Such a level is met exactly: a bar before a touch closing on it is on neither side (no
    touch), and a close on it 15 minutes later is not on the side it came from (no hold).
    INDUCED: each session again with its 12:00 bar missing, as for a minute Schwab sends no bar
    for (no trade in it): a touch with no bar 15 minutes later is not counted, and the session's
    later touches still are.
    """
    by_time = {b["_dt"]: b for b in bars_from_candles(_candles(symbol, "1m"))}
    for rth in _closed_days(symbol, EVENING).values():
        noon = rth[0]["dt"].replace(hour=12, minute=0)
        for tape in (rth, [b for b in rth if b["dt"] != noon]):
            bars = [by_time[b["dt"]] for b in tape]
            for level in sorted({b["close"] for b in tape}):
                got = _touch_outcomes(bars, level, tape[0]["dt"], 15)
                assert got == _one_day(tape, level, tape[0]["dt"], 15), (tape[0]["dt"], level)


def test_a_session_still_open_is_not_counted():
    """At 12:00 ET on 2026-10-07 that day's session is open: the counts are the evening's."""
    bars, daily = bars_from_candles(_candles("SPY", "1m")), _candles("SPY", "1d")
    held = sessions()
    noon = datetime(2026, 10, 7, 12, 0, tzinfo=ET)
    assert hold_counts(bars, daily, noon, sessions=held) == hold_counts(
        bars, daily, EVENING, sessions=held
    )


def test_a_session_closing_at_now_is_counted_and_its_bars_are_read_to_its_close():
    """At 16:00 ET on 2026-10-06, that session's regular close: it is closed, so it is counted.

    The bars read are each one before that close: the bar of 16:00 itself is not.
    """
    bars, daily = bars_from_candles(_candles("SPY", "1m")), _candles("SPY", "1d")
    held = sessions()
    close = session("2026-10-06").regular[-1][1]
    assert any(b["_dt"] == close for b in bars), "no bar at the close: the check would be vacuous"
    assert hold_window(bars, close, held) == [b for b in bars if b["_dt"] < close]
    assert hold_counts(bars, daily, close, sessions=held) == hold_counts(
        bars, daily, EVENING, sessions=held
    )


def test_the_counts_are_counted_once_per_input_and_a_bar_of_the_open_session_is_no_input():
    """The panel is sent on every new bar; the counts read only closed sessions' bars.

    A bar of the session still open returns the very counts already counted (no recount); a
    changed bar of a closed session is a new input and is counted again.
    """
    bars, daily = bars_from_candles(_candles("SPY", "1m")), _candles("SPY", "1d")
    held = sessions()
    newest = max(b["_dt"] for b in bars).date()  # the capture's last day, open at its noon
    noon = datetime(newest.year, newest.month, newest.day, 12, 0, tzinfo=ET)
    before = [b for b in bars if b["_dt"] < noon]
    assert len(before) + 1 == len([b for b in bars if b["_dt"] <= noon]), "its noon bar"
    tk = "ZZHOLDONCE"
    try:
        first = price_level_store.materialize_hold_counts(tk, before, daily=daily, now=noon)
        assert first == hold_counts(bars, daily, noon, sessions=held)
        later = noon + timedelta(minutes=1)
        again = price_level_store.materialize_hold_counts(
            tk, [b for b in bars if b["_dt"] <= noon], daily=daily, now=later
        )
        assert again is first, "a bar of the open session recounts nothing"
        closed = datetime(newest.year, newest.month, newest.day, 20, 0, tzinfo=ET)
        at_close = price_level_store.materialize_hold_counts(tk, bars, daily=daily, now=closed)
        assert at_close is not first, "once the session closes its bars are counted"
        assert at_close == hold_counts(bars, daily, closed, sessions=held)
        edited = [dict(b) for b in before]
        closed_day = next(b for b in edited if b["_dt"].date() < newest)
        closed_day["high"] += 50.0  # a bar of a closed session: a new input
        recounted = price_level_store.materialize_hold_counts(tk, edited, daily=daily, now=later)
        assert recounted is not first
        assert recounted == hold_counts(edited, daily, later, sessions=held)
    finally:
        price_level_store._HOLD_COUNTS.pop(tk, None)


def test_ten_days_are_too_few_touches_to_show_a_rate():
    """Schwab's 10 days of minute bars give fewer than HOLD_MIN_TOUCHES on every level: '-'."""
    got = hold_counts(
        bars_from_candles(_candles("SPY", "1m")),
        _candles("SPY", "1d"),
        EVENING,
        sessions=sessions(),
    )
    assert all(by[15].touches < HOLD_MIN_TOUCHES for by in got.values())
    pdh = got["PDH"][15]
    assert push_liquidity.hold_text(pdh) == f"- ({pdh.touches} touches)"


def test_the_wilson_interval():
    """Brown, Cai & DasGupta (2001): 0 of n has a lower bound of 0; the interval holds the rate."""
    lo, hi = wilson_interval(0, 120)
    assert lo == pytest.approx(0.0, abs=1e-12) and 0 < hi < 0.04
    lo, hi = wilson_interval(72, 120)
    assert lo < 72 / 120 < hi
    # the interval to the four decimals it is stated in, worked out outside this code
    assert (lo, hi) == pytest.approx((0.5106, 0.6832), abs=1e-4)


def test_the_liquidity_panel_serves_each_level_types_rate_with_its_note():
    """The console holds Schwab's 1-minute history and daily candles as the daemon pushes them."""
    for series in ("1m", "1d"):
        server._write_price_history(
            {"symbol": "SPY", "series": series, "answer": _answer("SPY", series)}
        )
    rows = push_liquidity.hold_rates("SPY", EVENING)
    names = [r["level"] for r in rows]
    assert names[0] == "Prior day high" and "Opening range high" in names
    pdh = hold_counts(
        bars_from_candles(bar_store.bars_1m("SPY", bar_store.BARS_KEPT)),
        bar_store.series("SPY", "1d"),
        EVENING,
        sessions=sessions(),
    )["PDH"]
    assert rows[0]["text"] == (
        push_liquidity.hold_text(pdh[15]) + " [30 min: " + push_liquidity.hold_text(pdh[30]) + "]"
    )
    assert "Osler 2000" in push_liquidity.HOLD_NOTE and "not a forecast" in push_liquidity.HOLD_NOTE
