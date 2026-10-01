"""The day's values are Schwab's own (operator 2026-10-01: "lets use what schwab gives us so now we
have volume and total volume right?"): today's daily candle is Schwab's LEVELONE_EQUITIES day
fields as sent (live_price_rows.day_candle, on the price row), the days before are Schwab's daily
price history (the daemon asks it, live_ui; the console carries it, streaming.bar_days), and no
daily candle is summed from minutes. On 2026-09-30 the chart's daily bar summed from the stored
minutes was 767.00 / 769.41 / 761.80 / 763.31 / 46.3M against Schwab's 766.45 / 769.41 / 762.18 /
762.63 / 62,110,041: wrong on four of five.

Real data: SPY's and TSL's day fields of 2026-09-30, read-only from production stream_capture.db,
and Schwab's daily candle for the day from one read-only price-history request
(tests/fixtures/real_day_fields_2026_09_30.json, source and build time inside)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import live_price_rows
import server as srv
from app.market_data.schwab.streaming import live_ui
from app.market_data.schwab.streaming.live_push import is_forwarded
from stream_spine import MessageBus, subscription_msg
from time_et import ET

FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_day_fields_2026_09_30.json")
                .read_text(encoding="utf-8"))


def _at(h: int, m: int, s: int = 0) -> float:
    return datetime(2026, 9, 30, h, m, s, tzinfo=ET).timestamp()


@pytest.fixture
def plane(monkeypatch):
    """The plane, empty; `replay(sym, until)` feeds it `sym`'s captured day-field messages received
    by `until`, through its real ingest, and records the daemon's heartbeat holding the symbol on
    LEVELONE_EQUITIES at `until` (the feed live)."""
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(lmp, "_by_ticker", {})

    def replay(sym: str, until: float) -> None:
        d = FX["symbols"][sym]
        state = [[ts, {k: v}] for k, (ts, v) in d["state_at_1559"].items()]
        for ts, item in sorted(d["early"] + state + d["late"], key=lambda e: e[0]):
            if ts <= until:
                lmp.record_from_level_one_equity(sym, item, received_ts=ts)
        lmp.record_feed_heartbeat({"ts": until, "schwab_socket_open": True,
                                   "held": {"LEVELONE_EQUITIES": [sym]}}, until)
    return replay


@pytest.mark.parametrize("sym", ["SPY", "TSL"])
def test_the_served_daily_candle_is_schwabs_daily_candle_exactly(plane, sym):
    """Once the day's trading is over (20:00 ET: SPY's TOTAL_VOLUME took its last value at
    19:59:59; and 21:00 ET) the price row's daily candle is Schwab's daily candle to the last
    digit: the open, high and low as sent, the regular session's last (REGULAR_MARKET_LAST_PRICE)
    and TOTAL_VOLUME, which takes in the post-market. The Trade Desk's session volume and the
    candle's volume are one value."""
    want = FX["symbols"][sym]["schwab_daily_candle"]
    for now in (_at(20, 0), _at(21, 0)):
        plane(sym, now)
        day = live_price_rows.price_row(sym, now)["day"]
        bar = day["bar"]
        assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (
            want["open"], want["high"], want["low"], want["close"], want["volume"]), now
        assert day["volume"] == bar["v"] and day["absent"] == {}
        assert day["volume_text"] == bar["v_text"] == ("62.11M" if sym == "SPY" else "210.1K")   # one text
        assert bar["t"] == datetime(2026, 9, 30, tzinfo=ET).timestamp() and bar["label"] == "Wed 09/30/2026"


def test_before_the_regular_session_the_open_is_absent_with_schwabs_reason(plane):
    """At 08:00 ET Schwab's OPEN_PRICE is 0 (blank until the regular session opens, Streamer
    Guide p.18) and HIGH/LOW 0 (no regular-session trade yet): absent with those reasons, never
    filled from the pre-market minutes; no candle is drawn. The day's volume so far is
    TOTAL_VOLUME as sent (pre-market included, p.16)."""
    plane("SPY", _at(8, 0))
    day = live_price_rows.price_row("SPY", _at(8, 0))["day"]
    assert day["bar"] is None
    assert day["absent"]["o"] == "Schwab's OPEN_PRICE is blank (0) until the regular session opens (Streamer Guide p.18)"
    assert day["absent"]["h"] == "Schwab's HIGH_PRICE is 0 until the regular session's first trade (Streamer Guide p.17)"
    assert day["volume"] == lmp.day_fields("SPY")["TOTAL_VOLUME"][0] > 0


def test_the_daily_chart_is_schwabs_daily_candles_and_never_summed_minutes(plane, monkeypatch):
    """The daemon asks Schwab's daily price history once a day per streamed symbol and pushes it
    (bardays.SYM); the console carries it, and the daily chart's history is those candles with
    today's from the day fields -- the stored minutes are not rolled into days. Schwab's daily
    candle of 2026-09-30 (the stand-in for its network's answer: its timestamp, 00:00 CT, is
    Schwab's daily-candle convention [UNVERIFIED]); served on 2026-10-01 at 10:00 ET, before any
    day field of that day."""
    want = FX["symbols"]["SPY"]["schwab_daily_candle"]
    candle = {**want, "datetime": int(datetime(2026, 9, 30, 0, 0, tzinfo=ET).timestamp() * 1000) + 3_600_000}
    asked: list = []
    now = datetime(2026, 10, 1, 10, 0, tzinfo=ET).timestamp()
    bus = MessageBus()
    pushed = bus.subscribe("bardays.", maxsize=16, name="test_console")

    async def daemon():
        ui = live_ui.LiveUiServer(bus, lambda: {}, {}, clock=lambda: now, history_fn=lambda *a: [],
                                  daily_fn=lambda sym, a, b: asked.append((sym, a, b)) or [candle])
        ui.on_subscription(subscription_msg(service="CHART_EQUITY", command="SUBS", symbols=["SPY"], code=0,
                                            reason="ok", ts=now))
        while ui._asks:
            await asyncio.gather(*list(ui._asks))
    asyncio.run(daemon())
    today = datetime(2026, 10, 1, tzinfo=ET).timestamp()
    assert asked == [("SPY", today - live_ui.DAILY_HISTORY_DAYS * 86400.0, today)]
    monkeypatch.setattr(ofs, "_bar_days", {})
    monkeypatch.setattr(ofs, "_price_rows", {"SPY": live_price_rows.price_row("SPY", now)})
    topic, msg = pushed.queue.get_nowait()
    assert is_forwarded(topic, msg)                                # live_push forwards it
    ofs._ingest_pushed(topic, msg)                                 # the console's ingest
    body = json.loads(srv.get_bars1m(ticker="SPY", tf="D", limit=12000).body)
    assert body["days_absent_reason"] is None
    (bar,) = body["bars"]                                          # 09-30; 10-01 has no day field yet
    assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (
        want["open"], want["high"], want["low"], want["close"], want["volume"])
    assert bar["t"] == datetime(2026, 9, 30, tzinfo=ET).timestamp() and bar["label"] == "Wed 09/30/2026"
