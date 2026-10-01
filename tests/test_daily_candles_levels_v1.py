"""The prior day's high and low (PDH / PDL) and the daily ATR are Schwab's daily candles (the
daemon's daily price history, pushed as bardays), through the real path: the console's ingest,
its bar writer's levels build, /api/levels and the ATR pair. Neither had a test through it (the
sixth review: taking the oldest candle as the prior day, or the ATR ignoring the pushed candles,
both survived). The candles must reach the previous trading session, or the values are absent
with the reason, and the daemon asks again until they do.

Real data: SPY's daily candles as Schwab sent them, captured 2026-08-20 13:04 UTC
(tests/fixtures/real_spy_daily_candles_2026_08_19.json, its newest the 2026-08-19 session)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import liquidity_value_engine as lve
import live_price_rows
import server as srv
from app.market_data.schwab.streaming import live_ui
from stream_spine import MessageBus, bar_days_msg, subscription_msg
from time_et import ET

RAW = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_daily_candles_2026_08_19.json")
                 .read_text(encoding="utf-8"))["candles"]


def _day(y, m, d) -> float:
    return datetime(y, m, d, tzinfo=ET).timestamp()


@pytest.fixture
def console(monkeypatch, pin_clock):
    """The console at `when` (ET) with the daemon's pushed daily candles of the days before it
    (the daemon's own conversion, live_price_rows.daily_candles), ingested as pushed; returns the
    levels the bar writer built from them."""
    def at(*when):
        pin_clock(*when)
        monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
        monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda tk: [])
        monkeypatch.setattr(srv, "resolve_spot", lambda tk, **k: (None, "none", None))
        monkeypatch.setattr(srv, "terrain_cache_get", lambda tk, t: {})
        monkeypatch.setattr(srv, "_atr_cache", {})
        monkeypatch.setattr(ofs, "_bar_days", {})
        while not ofs.streamed_bars.empty():
            ofs.streamed_bars.get_nowait()
        today = _day(*when[:3])
        candles = live_price_rows.daily_candles(RAW, today)
        ofs._ingest_pushed("bardays.SPY", bar_days_msg(symbol="SPY", candles=candles,
                                                      problem=live_price_rows.daily_history_gap(candles, today),
                                                      ts=today + 3600))
        srv._write_streamed_bars([ofs.streamed_bars.get_nowait() for _ in range(ofs.streamed_bars.qsize())])
        body = json.loads(srv.get_levels(ticker="SPY", tf="1").body)
        return {lv["id"]: lv for lv in body["levels"]}, body["families_absent"]
    return at


def test_the_prior_days_high_and_low_are_schwabs_candle_of_the_previous_session(console):
    """On 2026-08-20 the prior day is the 2026-08-19 session: PDH / PDL are its candle's high and
    low as Schwab sent them, built when the candles arrive (no minute bar needed)."""
    levels, _absent = console(2026, 8, 20, 10, 0)
    assert (levels["PDH"]["price"], levels["PDL"]["price"]) == (RAW[-1]["high"], RAW[-1]["low"]) == (772.47, 768.1)


@pytest.mark.parametrize("when, prior", [((2026, 8, 17, 10, 0), (778.8, 775.4301)),     # Monday: Friday 08-14
                                         ((2026, 7, 6, 10, 0), (751.31, 740.03))])     # after the 07-03 holiday
def test_after_a_weekend_or_a_market_holiday_the_prior_day_is_the_last_session(console, when, prior):
    """The previous trading session skips weekends and market holidays: on Monday 2026-08-17 it
    is Friday 08-14, and on Monday 2026-07-06 it is Thursday 07-02 (07-03, Independence Day
    observed, the market closed). Taking the previous calendar day read those days' history as
    short and left the prior day's high and low absent (the sixth review's M8 survived)."""
    levels, absent = console(*when)
    assert (levels["PDH"]["price"], levels["PDL"]["price"]) == prior
    assert not [a for a in absent if a["family"] == "prior_day_range"]


def test_the_daily_atr_is_the_average_true_range_of_schwabs_last_15_candles(console):
    """The daily ATR leg is the simple average of the last 14 true ranges of Schwab's daily
    candles before today (each the greatest of high - low and the distances of the high and the
    low from the prior close)."""
    console(2026, 8, 20, 10, 0)
    last = RAW[-15:]
    trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
           for p, c in zip(last, last[1:])]
    pair = srv._atr_pair("SPY", datetime(2026, 8, 20, 10, 0, tzinfo=ET).timestamp())
    assert pair.daily == round(sum(trs) / 14, 4) and pair.daily_reason is None     # served to 4 places


def test_candles_short_of_the_previous_session_give_no_prior_day_and_no_daily_atr(console):
    """On 2026-08-21 the candles end 2026-08-19: the previous session (2026-08-20) is not in them,
    so the prior day's high and low and the daily ATR are absent with that reason, never the older
    day's."""
    levels, absent = console(2026, 8, 21, 10, 0)
    why = "Schwab's daily history does not yet include 2026-08-20"
    assert "PDH" not in levels and "PDL" not in levels
    assert {"family": "prior_day_range", "reason": why} in absent
    pair = srv._atr_pair("SPY", datetime(2026, 8, 21, 10, 0, tzinfo=ET).timestamp())
    assert pair.daily is None and pair.daily_reason == why


def test_the_daemon_asks_again_on_a_new_day_and_until_the_history_reaches_the_previous_session():
    """The daemon asked a symbol's daily history once and kept it: on a new day, or while the
    reply did not yet hold the previous session, it was never asked again (M12 survived). It is
    asked on each new day and, while short, again on its clock. Schwab's network the stand-in,
    answering the captured candles (newest 2026-08-19)."""
    clock, asked = {"now": datetime(2026, 8, 20, 9, 0, tzinfo=ET).timestamp()}, []

    def daily(sym, start, end):
        asked.append((datetime.fromtimestamp(clock["now"], ET).strftime("%m-%d %H:%M"), end))
        return RAW

    async def main():
        bus = MessageBus()
        ui = live_ui.LiveUiServer(bus, lambda: {}, {}, clock=lambda: clock["now"], history_fn=lambda *a: [],
                                  daily_fn=daily)
        ui.on_subscription(subscription_msg(service="CHART_EQUITY", command="SUBS", symbols=["SPY"], code=0,
                                            reason="ok", ts=clock["now"]))
        for at in ((8, 20, 9, 2), (8, 21, 9, 0), (8, 21, 9, 2)):     # a whole history; a new day: short twice
            while ui._asks:
                await asyncio.gather(*list(ui._asks))
            clock["now"] = datetime(2026, *at, tzinfo=ET).timestamp()
            ui.tick(clock["now"])
        while ui._asks:
            await asyncio.gather(*list(ui._asks))
        return ui.daily["SPY"]
    held = asyncio.run(main())
    assert asked == [("08-20 09:00", _day(2026, 8, 20)), ("08-21 09:00", _day(2026, 8, 21)),
                     ("08-21 09:02", _day(2026, 8, 21))]
    assert held.problem == "Schwab's daily history does not yet include 2026-08-20"
