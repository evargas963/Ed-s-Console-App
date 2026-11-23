"""The prior session and its high, low and close are Schwab's daily candle, as sent.

Real data: Schwab's /pricehistory answers for SPY and TSLA of 2026-10-07 09:57 UTC
(fixtures/real_pricehistory_spy_tsla_2026_10_07.json): a year of daily candles and ten days of
1-minute bars, through the real bar writer (server._write_price_history) and the real level
producer. Schwab's daily close is the official close, which the last 1-minute bar's close is
not (SPY 2026-10-01: 763.99 against 764.03).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

import server
from calc.liquidity_value_engine import (
    OvernightRange,
    bars_from_candles,
    build_price_level_snapshot,
    get_overnight_levels,
    get_previous_day_levels,
    prior_session,
)
from state import bar_store, price_level_store
from time_et import ET, session, sessions

_FX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)


def _held(symbol: str) -> tuple[list, list]:
    """(daily candles, 1-minute candles) of `symbol` as the bar writer holds them."""
    for a in _FX["answers"]:
        if a["symbol"] == symbol and a["series"] in ("1m", "1d"):
            server._write_price_history(
                {"symbol": symbol, "series": a["series"], "answer": a["body"]}
            )
    try:
        return list(bar_store._series[(symbol, "1d")]), list(bar_store._bars[symbol])
    finally:
        bar_store._series.pop((symbol, "1d"), None)
        bar_store._bars.pop(symbol, None)


def _sent(symbol: str, day: date) -> dict:
    """Schwab's daily candle for `day`, as it sent it."""
    (candle,) = [
        c
        for a in _FX["answers"]
        if a["symbol"] == symbol and a["params"]["frequencyType"] == "daily"
        for c in a["body"]["candles"]
        if datetime.fromtimestamp(c["datetime"] / 1000, ET).date() == day
    ]
    return candle


def test_the_prior_days_high_low_and_close_are_schwabs_daily_candle_as_sent():
    for symbol in ("SPY", "TSLA"):
        daily, minutes = _held(symbol)
        for session_day, prior_day in (
            (date(2026, 10, 2), date(2026, 10, 1)),
            (date(2026, 10, 6), date(2026, 10, 5)),
            (date(2026, 10, 7), date(2026, 10, 6)),
        ):
            out = get_previous_day_levels(
                bars_from_candles(minutes), prior_session(daily, session_day), sessions=sessions()
            )
            sent = _sent(symbol, prior_day)
            assert out.prior_date == prior_day
            assert (out.pdh, out.pdl, out.pdc) == (
                sent["high"],
                sent["low"],
                sent["close"],
            )


def test_the_prior_close_is_schwabs_official_close_not_the_last_minutes():
    """SPY 2026-10-01: Schwab's daily close 763.99; its last regular 1-minute bar closed 764.03."""
    daily, minutes = _held("SPY")
    out = get_previous_day_levels(
        bars_from_candles(minutes), prior_session(daily, date(2026, 10, 2)), sessions=sessions()
    )
    assert out.pdc == 763.99


def test_monday_s_prior_session_is_friday_schwab_sends_no_weekend_candle():
    daily, _minutes = _held("SPY")
    prior = prior_session(daily, date(2026, 10, 5))
    assert datetime.fromtimestamp(prior.ts, ET).date() == date(2026, 10, 2)


def test_no_daily_candle_before_the_session_leaves_the_prior_day_absent():
    daily, minutes = _held("SPY")
    first = min(datetime.fromtimestamp(c.ts, ET).date() for c in daily)
    assert prior_session(daily, first) is None
    snap = build_price_level_snapshot(
        first,
        bars_from_candles(minutes),
        prior=prior_session(daily, first),
        bar_source="real_pricehistory_spy_tsla_2026_10_07.json",
        sessions=sessions(),
    )
    absent = {f["family"]: f["reason"] for f in snap.families_absent}
    assert snap.price("PDH") is None
    assert absent["prior_day"] == "no Schwab daily candle held for a prior session"


def test_the_prior_value_area_is_estimated_from_that_sessions_regular_bars_only():
    """The POC and value area are ours (Schwab sends no volume profile).

    They come from the prior session's 390 regular 1-minute bars, none before its open or after
    its close.
    """
    daily, minutes = _held("SPY")
    out = get_previous_day_levels(
        bars_from_candles(minutes), prior_session(daily, date(2026, 10, 2)), sessions=sessions()
    )
    assert out.rth_bars == 390
    p = out.profile
    assert p is not None and p.val is not None and p.poc is not None and p.vah is not None
    assert p.val <= p.poc <= p.vah
    assert out.pdl <= p.val and p.vah <= out.pdh


def test_the_overnight_range_runs_from_the_prior_close_itself_to_the_open():
    """Each captured session from 2026-10-01: the bars from the prior close to the open.

    The prior session's regular close (that minute's bar included) and this session's regular
    open are Schwab's /markets answers, held from 2026-09-30 (tests/conftest.py).
    """
    for symbol in ("SPY", "TSLA"):
        daily, minutes = _held(symbol)
        days = {datetime.fromtimestamp(m.ts, ET).date() for m in minutes}
        for day in sorted(
            d for d in days if d >= date(2026, 10, 1) and session(d.isoformat()).regular
        ):
            prior = prior_session(daily, day)
            assert prior is not None
            prev = datetime.fromtimestamp(prior.ts, ET).date()
            start = session(prev.isoformat()).regular[-1][1].timestamp()
            end = session(day.isoformat()).regular[0][0].timestamp()
            window = [m for m in minutes if start <= m.ts < end]
            assert window, f"{symbol} {day}: no overnight bar, the check would be vacuous"
            got = get_overnight_levels(bars_from_candles(minutes), day, prev, sessions=sessions())
            assert got == OvernightRange(
                high=max(m.high for m in window), low=min(m.low for m in window)
            ), (symbol, day)


#: a Tuesday, and its prior session: Monday 2026-10-05, 390 regular 1-minute bars in the capture
TUESDAY, MONDAY = date(2026, 10, 6), date(2026, 10, 5)


def _regular_bars(minutes: list, day: date) -> list:
    """`day`'s 1-minute candles inside its regular session as Schwab's /markets sent it."""
    hours = session(day.isoformat()).regular
    return [m for m in minutes if hours[0][0].timestamp() <= m.ts < hours[-1][1].timestamp()]


def test_each_family_with_no_bar_in_its_window_is_declared_absent_by_name_with_why():
    """Tuesday's levels over Monday's regular bars alone: Tuesday's four families have no bar.

    None of Monday's regular bars is in Tuesday's session or in the overnight window (Monday's
    close to Tuesday's open): each family is declared, in order, and the prior day stands whole.
    """
    daily, minutes = _held("SPY")
    snap = build_price_level_snapshot(
        TUESDAY,
        bars_from_candles(_regular_bars(minutes, MONDAY)),
        prior=prior_session(daily, TUESDAY),
        bar_source="real_pricehistory_spy_tsla_2026_10_07.json",
        sessions=sessions(),
    )
    assert snap.families_absent == [
        {"family": "vwap", "reason": "no RTH volume for session VWAP in available bars"},
        {"family": "opening_range", "reason": "no bar in the opening minutes, or no open known"},
        {"family": "extended_hours", "reason": "no extended-hours bars in the bars held"},
        {
            "family": "value_area",
            "reason": "no RTH volume for the volume profile in available bars",
        },
    ]
    assert set(snap.levels) == {"PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL"}
    assert (snap.degraded, snap.vwap_series, snap.volume_profile) == ([], [], None)


@pytest.mark.parametrize("kept", [0, 299, 300, 389, 390])
def test_a_prior_session_whose_bars_do_not_cover_its_regular_window_is_a_partial_tape(kept):
    """INDUCED: Monday's tape cut to its first `kept` regular bars, as a capture begun late cuts it.

    Monday's regular window, as Schwab's /markets sent it, is 9:30 to 16:00 ET: 390 minutes, each
    with a bar in the capture. Below that the prior day is served and disclosed as partial; with
    none of its bars its value area is absent, with why. Tuesday's own bars are all kept.
    """
    daily, minutes = _held("SPY")
    tuesday = [m for m in minutes if datetime.fromtimestamp(m.ts, ET).date() == TUESDAY]
    snap = build_price_level_snapshot(
        TUESDAY,
        bars_from_candles(_regular_bars(minutes, MONDAY)[:kept] + tuesday),
        prior=prior_session(daily, TUESDAY),
        bar_source="real_pricehistory_spy_tsla_2026_10_07.json",
        sessions=sessions(),
    )
    hours = session(MONDAY.isoformat()).regular
    assert (hours[0][0].strftime("%H:%M"), hours[-1][1].strftime("%H:%M")) == ("09:30", "16:00")
    assert len(_regular_bars(minutes, MONDAY)) == 390
    partial = (
        f"prior_day: prior session 2026-10-05 holds only {kept} RTH bars of its 390 "
        "regular-session minutes (Schwab's /markets); its POC and value area are estimated from "
        "a partial tape"
    )
    assert snap.degraded == ([] if kept == 390 else [partial])
    assert snap.families_absent == (
        [
            {
                "family": "prior_value_area",
                "reason": "no RTH bars of the prior session 2026-10-05 in available bars",
            }
        ]
        if kept == 0
        else []
    )


def test_the_levels_read_every_held_bar_from_the_prior_sessions_regular_open():
    """Tuesday 19:59 ET: the published levels read the bars from Monday's 9:30 ET open on.

    The console holds SPY's ten days of 1-minute bars and its daily candles as the daemon pushes
    them. The levels read the bars from the prior session's regular open (Schwab's /markets) to
    the newest: each one, and none older, whatever their count.
    """
    for a in _FX["answers"]:
        if a["symbol"] == "SPY" and a["series"] in ("1m", "1d"):
            server._write_price_history(
                {"symbol": "SPY", "series": a["series"], "answer": a["body"]}
            )
    now = datetime(2026, 10, 6, 19, 59, tzinfo=ET)
    try:
        server._publish_price_levels("SPY", now)
        snap = price_level_store.canonical_price_level_snapshot("SPY", now)
        held = bar_store._bars["SPY"]
    finally:
        bar_store._series.pop(("SPY", "1d"), None)
        bar_store._bars.pop("SPY", None)
        for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == "SPY"]:
            del price_level_store._MATERIALIZED_SNAPSHOTS[key]
    monday_open = session(MONDAY.isoformat()).regular[0][0].timestamp()
    read = [b for b in held if b.ts >= monday_open]
    assert len(held) > len(read) > 0
    assert snap is not None and snap.session_date == TUESDAY
    assert snap.bars_used == len(read)
    assert snap.degraded == []
