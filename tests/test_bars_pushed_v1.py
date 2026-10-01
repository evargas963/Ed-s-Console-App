"""The daemon pushes each completed 1-minute bar to the browser (live_ui), as the chart bar it
makes at every timeframe; the chart's history is /api/bars1m. The two are one producer: the push
and the route give the same bar for the same minutes, however many of the day's minutes the
daemon streamed itself and how many it read from the store at startup.

Before this, the console wrote each bar and pushed `liquidity`, and every chart read
/api/bars1m again. Real Schwab CHART_EQUITY bars: SPY 2026-09-25
(tests/fixtures/real_spy_1m_bars_2026_09_24_25.json), through the real live_ui server, bus and
socket, and the real route."""
from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import server as srv
from app.market_data.schwab.streaming import live_ui
from db import EdDB
from stream_spine import MessageBus, bar_msg
from time_et import ET, ct_label

_FX = Path(__file__).resolve().parent / "fixtures"
FRIDAY = [b for b in json.loads((_FX / "real_spy_1m_bars_2026_09_24_25.json").read_text(encoding="utf-8"))["bars"]
          if datetime.fromtimestamp(b["timestamp"] / 1000, ET).day == 25]


def _msg(b: dict, sym: str = "SPY") -> dict:
    """The bus message the daemon builds from Schwab's CHART_EQUITY item; received a stand-in
    2.7 s after the minute ends (the median measured 2026-09-30: 62.7 s after the bar starts)."""
    start = b["timestamp"] / 1000.0
    return bar_msg(symbol=sym, bar_start_ms=b["timestamp"], open=b["open"], high=b["high"], low=b["low"],
                   close=b["close"], volume=b["volume"], src="schwab_chart", ts_recv=start + 62.7)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


#: the instant the daemon (re)started, a stand-in: as Friday's 101st stored minute began
RESTART = FRIDAY[100]["timestamp"] / 1000.0


def _pushed(bars_db, streamed, subscribe=("SPY",), after_start=None):
    """Start the daemon's browser socket at RESTART as the daemon does (the day's stored minutes
    of every symbol read from the store `bars_db`, none when it is None), call `after_start()` once
    it is listening, publish `streamed` on its bus, and return every bar update a browser
    subscribed to `subscribe` received."""
    from websockets.asyncio.client import connect

    async def main():
        port, bus, stop, stats = _free_port(), MessageBus(), asyncio.Event(), {}
        feed = lambda: {"ts": RESTART, "schwab_socket_open": True, "held": {}, "health": {}}  # noqa: E731
        minutes = None if bars_db is None else live_ui.day_minutes(bars_db, RESTART)
        task = asyncio.create_task(live_ui.serve_live_ui(bus, stop, heartbeat_fn=feed, clock=lambda: RESTART,
                                                         host="127.0.0.1", port=port, stats=stats,
                                                         minutes=minutes))
        while not stats.get("listening"):
            await asyncio.sleep(0.01)
        if after_start is not None:
            after_start()
        got = []
        try:
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"op": "subscribe", "symbols": list(subscribe)}))
                await asyncio.sleep(0.2)
                for b in streamed:
                    bus.publish(f"bar1m.{b['symbol']}", b)
                    await asyncio.sleep(0.01)
                end = time.monotonic() + 3
                while time.monotonic() < end and stats.get("bars_sent", 0) < len(streamed):
                    try:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                    except asyncio.TimeoutError:
                        continue
                    if frame.get("type") == "bars":
                        got.extend(frame["bars"])
                end = time.monotonic() + 0.3
                while time.monotonic() < end:
                    try:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), 0.1))
                    except asyncio.TimeoutError:
                        continue
                    if frame.get("type") == "bars":
                        got.extend(frame["bars"])
        finally:
            stop.set()
            await task
        return got
    return asyncio.run(main())


def test_the_pushed_bar_is_the_routes_bar_at_every_timeframe(monkeypatch, tmp_path):
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    stored, streamed = FRIDAY[:100], FRIDAY[100:140]
    for b in stored:                                 # written before the daemon (re)started
        assert srv._write_streamed_bar(_msg(b))
    got = _pushed(db.db_path, [_msg(b) for b in streamed])
    assert len(got) == len(streamed) and {u["ticker"] for u in got} == {"SPY"}
    for b in streamed:                               # the console writes the same bars
        assert srv._write_streamed_bar(_msg(b))
    last = got[-1]
    assert last["ts_recv"] == _msg(streamed[-1])["ts_recv"]
    for tf in live_price_rows.CHART_TFS:
        route = json.loads(srv.get_bars1m(ticker="SPY", tf=tf, limit=12000).body)
        assert last["tf"][tf] == route["bars"][-1], tf
        assert last["last_bar"] == route["last_bar"]
    # the daily bar holds the minutes the daemon read from the store as well as its own; it is
    # stamped with its trading date's start, 00:00 ET (a bar's time is its bucket's start, the
    # chart convention: it was the first held minute's, which a late minute could move)
    assert last["tf"]["D"]["o"] == stored[0]["open"]
    assert last["tf"]["D"]["t"] == datetime(2026, 9, 25, tzinfo=ET).timestamp()
    # each bar carries its label, served (the chart formatted bar times itself): the daily bar its
    # ET trading date, an intraday bar its Central Time
    assert last["tf"]["D"]["label"] == "Fri 09/25/2026"
    assert last["tf"]["5"]["label"] == ct_label(last["tf"]["5"]["t"])
    # the newest hour of 1-minute bars the push carries whole is the hour the chart's history
    # serves (the Trade Desk's Order Flow card shows each as served; its size exists once, on the
    # server: the page asked for its own 60 and cut its own window)
    history = json.loads(srv.get_bars1m(ticker="SPY", tf="30", limit=9000).body)
    assert last["recent_1m"] == history["recent_1m"] and len(last["recent_1m"]) == live_price_rows.RECENT_1M_BARS


def test_the_store_is_read_at_startup_only(monkeypatch, tmp_path):
    """The database is history: the daemon reads the day's stored minutes of every symbol once,
    at startup, and never for a live screen. With the database unreadable after startup, a
    symbol's first bar in session is still pushed, its daily bar holding the stored minutes, and
    no read is made. The daemon used to read the store the first time a symbol had a bar that
    day, in session. QQQ's bars are SPY's real bars under another symbol, a stand-in."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    stored, streamed = FRIDAY[:100], FRIDAY[100:110]
    for b in stored:
        assert srv._write_streamed_bar(_msg(b)) and srv._write_streamed_bar(_msg(b, sym="QQQ"))
    reads = []

    def unreadable(*a, **k):
        reads.append(a)
        raise sqlite3.OperationalError("unable to open database file")

    got = _pushed(db.db_path, [_msg(b) for b in streamed], subscribe=("SPY",),
                  after_start=lambda: monkeypatch.setattr(live_ui.sqlite3, "connect", unreadable))
    assert reads == []
    assert [u["tf"]["1"]["t"] for u in got] == [b["timestamp"] / 1000.0 for b in streamed]
    assert got[0]["tf"]["D"]["o"] == stored[0]["open"]                # the minutes read at startup


def test_a_symbol_streamed_after_startup_pushes_the_whole_days_bars(monkeypatch, tmp_path):
    """CHART_EQUITY changes as the operator moves between tickers. A symbol that was not streamed
    when the daemon started, with minutes already stored today, was held from its first streamed
    minute only: its pushed daily, 30m and 60m bars and its Order Flow hour were partial and were
    drawn over the chart's full-day candle (QQQ: open 769.09 for 768.78, volume 372,524 for
    8,324,197). The daemon loads every symbol's stored minutes at startup, so the pushed bars are
    the route's. Real SPY CHART_EQUITY bars of 2026-09-25 under the symbol QQQ (the stand-in);
    QQQ is not streamed at startup and is subscribed after."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    stored, streamed = FRIDAY[:100], FRIDAY[100:110]
    for b in stored:                                 # stored today before the daemon started
        assert srv._write_streamed_bar(_msg(b, sym="QQQ"))
    got = _pushed(db.db_path, [_msg(b, sym="QQQ") for b in streamed], subscribe=("QQQ",))
    for b in streamed:                               # the console writes the same bars
        assert srv._write_streamed_bar(_msg(b, sym="QQQ"))
    last = got[-1]
    for tf in live_price_rows.CHART_TFS:
        assert last["tf"][tf] == json.loads(srv.get_bars1m(ticker="QQQ", tf=tf, limit=12000).body)["bars"][-1], tf
    assert last["recent_1m"] == json.loads(srv.get_bars1m(ticker="QQQ", tf="30", limit=9000).body)["recent_1m"]


def test_a_browser_back_from_a_drop_is_told_the_gap_and_sent_only_new_bars(monkeypatch, tmp_path):
    """Live bars are only the ones Schwab sends while the browser is connected. The subscribe after
    a drop carries the last beat's time; the daemon answers with the gap (from that beat, less
    two beats, to its reconnect) and resends none of the bars it received in it: the next bar the
    browser gets is the next one Schwab sends. A first subscribe is told no gap."""
    from websockets.asyncio.client import connect

    monkeypatch.setattr(live_ui, "HEARTBEAT_SEC", 0.2)
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    before, gone, after = FRIDAY[:20], FRIDAY[20:35], FRIDAY[35]   # connected / disconnected / back

    async def frames(ws, seconds):
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                out.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except asyncio.TimeoutError:
                continue
        return out

    async def main():
        port, bus, stop, stats = _free_port(), MessageBus(), asyncio.Event(), {}
        feed = lambda: {"ts": time.time(), "schwab_socket_open": True, "held": {}, "health": {}}  # noqa: E731
        task = asyncio.create_task(live_ui.serve_live_ui(bus, stop, heartbeat_fn=feed, clock=time.time,
                                                         host="127.0.0.1", port=port, stats=stats))
        while not stats.get("listening"):
            await asyncio.sleep(0.01)
        try:
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
                first = await frames(ws, 0.3)
                for b in before:
                    msg = dict(_msg(b), ts_recv=time.time())
                    bus.publish("bar1m.SPY", msg)
                    await asyncio.sleep(0.01)
                seen = first + await frames(ws, 1.2)          # a second of beats after the last bar
            last_beat = [f["feed"]["ts"] for f in seen if f.get("type") == "feed"][-1]
            for b in gone:                                    # the daemon receives, nobody listens
                bus.publish("bar1m.SPY", dict(_msg(b), ts_recv=time.time()))
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.2)
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                t0 = time.time()
                await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"], "disconnected_since": last_beat}))
                back = await frames(ws, 0.5)
                t1 = time.time()
                bus.publish("bar1m.SPY", dict(_msg(after), ts_recv=time.time()))   # Schwab's next bar
                back += await frames(ws, 0.5)
        finally:
            stop.set()
            await task
        return first, back, last_beat, t0, t1
    first, back, last_beat, t0, t1 = asyncio.run(main())
    assert not [f for f in first if f.get("type") in ("bars", "bars_gap")], "a first subscribe: no gap, no bar"
    (gap,) = [f["gap"] for f in back if f.get("type") == "bars_gap"]
    assert gap["from_ts"] == last_beat - 2 * live_ui.HEARTBEAT_SEC and t0 <= gap["to_ts"] <= t1
    assert gap["note"].startswith(f"No live bars from {ct_label(gap['from_ts'])} to {ct_label(gap['to_ts'])}")
    sent = [u for f in back if f.get("type") == "bars" for u in f["bars"]]
    assert [u["tf"]["1"]["t"] for u in sent] == [after["timestamp"] / 1000.0], "no bar of the gap is resent"


def test_at_every_minute_of_a_real_day_the_push_is_the_roll_up_at_every_timeframe():
    """The daemon rolls only the bucket the new minute is in (it must not hold its event loop:
    44 symbols' updates took 78 ms rolling the whole day at every timeframe, 9 ms the bucket);
    that bucket's bar is the route's roll-up of the day so far, at every minute."""
    day = [live_price_rows.minute_bar(_msg(b)) for b in FRIDAY]
    for k in range(len(day)):
        so_far = day[:k + 1]
        update = live_price_rows.bar_update("SPY", so_far, so_far[-1], 0.0)
        for tf in live_price_rows.CHART_TFS:
            assert update["tf"][tf] == live_price_rows.served_bar(live_price_rows.aggregate_bars(so_far, tf)[-1], tf), (k, tf)


def test_a_bar_that_is_not_a_chart_bar_or_not_subscribed_is_never_pushed(tmp_path):
    """A price sent as -999 (not a number), a minute outside the stored
    window (09:14 ET, before 09:15), and a symbol no browser asked for: none reaches the browser."""
    ok, bad, early = FRIDAY[10], dict(FRIDAY[11], close=-999), dict(FRIDAY[0])
    early["timestamp"] = int(datetime(2026, 9, 25, 9, 13, tzinfo=ET).timestamp() * 1000)
    got = _pushed(None, [_msg(ok), _msg(bad), _msg(early), _msg(FRIDAY[12], sym="QQQ")])
    assert [u["tf"]["1"]["t"] for u in got] == [ok["timestamp"] / 1000.0]
    assert live_price_rows.minute_bar(_msg(bad)) is None and live_price_rows.minute_bar(_msg(early)) is None


def test_a_minute_schwab_sends_late_is_never_pushed_as_a_charts_newest_bar():
    """A chart places each pushed bar with the library's own update, which only replaces the
    newest bar or adds a newer one: a bar older than the chart's last raised a page error. A
    minute Schwab sends late (here the 12th, after the 14th, and the 9th, before the day's first
    held minute) is a past event: it joins the held minutes, so the timeframes whose newest bar
    contains it, the daily bar and the Order Flow hour hold it; the older chart bar it belongs to
    is not pushed as a tail. A bar's time is its bucket's start, so no late minute moves it: the
    daily bar is pushed with every minute (it stopped for the rest of the day when the late minute
    preceded the day's first, as a bar was stamped with its first held minute). Real SPY
    CHART_EQUITY bars of 2026-09-25, delivered out of order (the order is the stand-in)."""
    class _Ws:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            self.sent.append(json.loads(text))

    order = [FRIDAY[i] for i in (10, 11, 13, 14, 12, 15, 9, 16)]

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: 0.0)
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        for b in order:
            srv_ui.on_bar(_msg(b))
        pump = asyncio.create_task(srv_ui._pump(c))
        await asyncio.sleep(0.05)
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        return [u for f in c.ws.sent if f["type"] == "bars" for u in f["bars"]]

    sent = asyncio.run(main())
    assert len(sent) == len(order)
    for tf in live_price_rows.CHART_TFS:                 # each chart's pushes only move forward
        times = [u["tf"][tf]["t"] for u in sent if tf in u["tf"]]
        assert times == sorted(times), tf
    for k, update in enumerate(sent):
        held = sorted((live_price_rows.minute_bar(_msg(b)) for b in order[:k + 1]), key=lambda m: m["t"])
        assert "D" in update["tf"], k                    # the daily bar keeps being pushed
        for tf, bar in update["tf"].items():             # every bar pushed holds every minute held
            assert bar == live_price_rows.served_bar(live_price_rows.aggregate_bars(held, tf)[-1], tf), (k, tf)
        assert [m["t"] for m in update["recent_1m"]] == [m["t"] for m in held][-live_price_rows.RECENT_1M_BARS:]
    for k in (4, 6):                                     # the late minutes' own bars are not tails
        assert "1" not in sent[k]["tf"], k
    assert sent[4]["tf"]["5"]["t"] == sent[3]["tf"]["5"]["t"]   # the bar it joins keeps its time
    assert sent[6]["tf"]["D"]["t"] == sent[5]["tf"]["D"]["t"] == datetime(2026, 9, 25, tzinfo=ET).timestamp()


def test_bars_that_arrive_before_the_next_send_are_all_sent_in_order():
    """Every completed minute reaches the browser: three bars of one symbol received before the
    browser's next send go out as three updates, oldest first (a newer bar used to replace an
    unsent older one, and that minute never reached the chart)."""
    class _Ws:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            self.sent.append(json.loads(text))

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: 0.0)
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        for b in FRIDAY[10:13]:
            srv_ui.on_bar(_msg(b))
        pump = asyncio.create_task(srv_ui._pump(c))
        await asyncio.sleep(0.05)
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        return c.ws.sent

    sent = asyncio.run(main())
    assert [u["tf"]["1"]["t"] for f in sent if f["type"] == "bars" for u in f["bars"]] == \
        [b["timestamp"] / 1000.0 for b in FRIDAY[10:13]]
