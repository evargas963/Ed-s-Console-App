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
    """At 08:00 ET Schwab sends the open, high and low as 0: no regular-session trade yet
    (Streamer Guide p.17-18). That is what Schwab sent, shown as its reason in one sentence,
    never filled from the pre-market minutes; no candle is drawn. The day's volume so far is
    TOTAL_VOLUME as sent (pre-market included, p.16), the 09-30 session's (SPY's last trade)."""
    plane("SPY", _at(8, 0))
    day = live_price_rows.price_row("SPY", _at(8, 0))["day"]
    assert day["bar"] is None and day["label"] == "Wed 09/30/2026"
    why = "Schwab's open, high and low are 0: no regular-session trade yet (Streamer Guide p.17-18)"
    assert day["absent"]["o"] == day["absent"]["h"] == day["absent"]["l"] == why
    assert day["unavailable"] == "No daily candle for Wed 09/30/2026: " + why          # one served sentence
    assert day["volume"] == lmp.day_fields("SPY")["TOTAL_VOLUME"][0] > 0


OVERNIGHT = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_l1_overnight_2026_09_08_28.json")
                       .read_text(encoding="utf-8"))["windows"]


@pytest.mark.parametrize("sym, when", [("SPY", (2026, 9, 8, 0, 10)), ("SPY", (2026, 9, 8, 2, 40)),
                                       ("SPY", (2026, 9, 8, 4, 30)), ("IWM", (2026, 9, 28, 2, 0))])
def test_after_midnight_the_prior_days_values_are_shown_as_that_days(monkeypatch, sym, when):
    """Schwab re-sends the prior day's day fields after midnight with a new receive time: SPY on
    2026-09-08 (after the Labor Day holiday) at 00:02 ET re-sent Friday 09-04's open, high, low
    and 34,054,199 shares, and they were served as Tuesday's candle and volume; IWM on 2026-09-28
    at 01:47 ET re-sent Friday's 22,613,925 shares. What Schwab sent is shown, whatever the hour,
    as the candle of the session its last trade belongs to (TRADE_TIME_MILLIS: Friday), labeled
    Friday -- never Tuesday's, never blank (operator 2026-10-01: "we use what schwab gives us and
    we display it, regardless of the time. if we have it we display it"). From 01:30 ET Schwab
    sends the open, high and low as 0 (no regular-session trade yet): no candle, with Schwab's
    reason, the volume still shown. Real messages, read-only from production stream_capture.db
    (tests/fixtures/real_l1_overnight_2026_09_08_28.json); the daemon's heartbeat, live and
    holding the symbol, a stand-in."""
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(lmp, "_by_ticker", {})
    now = datetime(*when, tzinfo=ET).timestamp()
    (w,) = [w for w in OVERNIGHT if w["symbol"] == sym and w["from_et"][:10] == datetime(*when).date().isoformat()]
    for m in w["messages"]:
        if m["ts_recv"] <= now:
            lmp.record_from_level_one_equity(sym, m["content"], received_ts=m["ts_recv"])
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [sym]}}, now)
    row = live_price_rows.price_row(sym, now)
    day = row["day"]
    friday, volume = {"SPY": ("Fri 09/04/2026", 34054199), "IWM": ("Fri 09/25/2026", 22613925)}[sym]
    assert (day["label"], day["volume"]) == (friday, volume)
    assert day["t"] == datetime.strptime(friday, "%a %m/%d/%Y").replace(tzinfo=ET).timestamp()
    if (sym, when[3]) == ("SPY", 0):                    # before Schwab's 01:30 day roll: Friday's candle
        assert (day["bar"]["o"], day["bar"]["h"], day["bar"]["l"], day["bar"]["c"]) == (772.01, 772.87, 769.0, 770.19)
        assert day["bar"]["label"] == friday and day["unavailable"] is None
    else:                                               # Schwab's own 0s: its reason, the volume shown
        assert day["bar"] is None and day["unavailable"] == (
            f"No daily candle for {friday}: Schwab's open, high and low are 0: no regular-session trade yet "
            f"(Streamer Guide p.17-18)")
    # the last trade is shown as Friday's, never as a live price
    assert row["spot"] is None and row["closed_last"]["session"] == f"post-market {friday}"


def test_the_daily_chart_is_schwabs_daily_candles_and_never_summed_minutes(plane, monkeypatch):
    """The daemon asks Schwab's daily price history once a day per streamed symbol and pushes it
    (bardays.SYM); the console carries it, and the daily chart's history is those candles with
    today's from the day fields -- the stored minutes are not rolled into days. Schwab's daily
    candle of 2026-09-30 (the stand-in for its network's answer, stamped 00:00 CT as Schwab's
    stored daily history stamps its candles, tests/fixtures/real_spy_daily_candles_2026_08_19.json);
    served on 2026-10-01 at 10:00 ET, with no day field from the stream."""
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
    # no day field from the stream: the route serves its own reason beside the history's
    assert body["today"]["bar"] is None and body["today"]["unavailable"].startswith("No daily candle")


def test_when_schwabs_fields_make_no_candle_its_reason_is_served_with_the_daily_history(monkeypatch):
    """/api/bars1m tf=D served only the history's reason when the day fields made no candle. The
    price row's `day` and the route's `today` carry its trading date and Schwab's reason (its
    open, high and low 0 since its overnight roll), which the chart prints; the candle already
    drawn for that date stays (operator 2026-10-01: "if we have it we display it"). Real SPY
    messages of 2026-09-08 to 04:30 ET (its last trade Friday's,
    tests/fixtures/real_l1_overnight_2026_09_08_28.json); the heartbeat a stand-in."""
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(lmp, "_by_ticker", {})
    now = datetime(2026, 9, 8, 4, 30, tzinfo=ET).timestamp()
    (w,) = [w for w in OVERNIGHT if w["symbol"] == "SPY"]
    for m in w["messages"]:
        lmp.record_from_level_one_equity("SPY", m["content"], received_ts=m["ts_recv"])
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["SPY"]}}, now)
    row = live_price_rows.price_row("SPY", now)
    monkeypatch.setattr(ofs, "_price_rows", {"SPY": row})
    monkeypatch.setattr(ofs, "_bar_days", {})
    why = ("No daily candle for Fri 09/04/2026: Schwab's open, high and low are 0: no regular-session trade "
           "yet (Streamer Guide p.17-18)")
    assert row["day"]["unavailable"] == why and row["day"]["t"] == datetime(2026, 9, 4, tzinfo=ET).timestamp()
    body = json.loads(srv.get_bars1m(ticker="SPY", tf="D", limit=12000).body)
    assert body["today"] == row["day"] and body["bars"] == []
