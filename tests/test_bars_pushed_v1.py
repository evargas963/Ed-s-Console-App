"""The daemon pushes each completed 1-minute bar to the browser (live_ui), as the chart bar it
makes at every timeframe; the chart's history is /api/bars1m. The two are one producer: the push
and the route give the same bar for the same minutes, however many of the day's minutes the
daemon streamed itself and how many Schwab's price history gave it for the spans its stream
did not cover; a bar is never served missing a minute.

Before this, the console wrote each bar and pushed `liquidity`, and every chart read
/api/bars1m again. Real Schwab CHART_EQUITY bars: SPY 2026-09-25
(tests/fixtures/real_spy_1m_bars_2026_09_24_25.json), through the real live_ui server, bus and
socket, and the real route. The one stand-in is Schwab's network: its price-history response is
built from the same captured minutes (`_schwab`)."""
from __future__ import annotations

import asyncio
import json
import os
import random
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
from stream_spine import MessageBus, bar_msg, subscription_msg
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


#: the instant the daemon is serving, a stand-in: as Friday's 101st minute began
RESTART = FRIDAY[100]["timestamp"] / 1000.0


def _candle(b: dict) -> dict:
    """One minute as Schwab's price history sends it (get_price_history_every_minute)."""
    return {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
            "volume": b["volume"], "datetime": b["timestamp"]}


def _schwab(by_symbol: dict, asked: "list | None" = None):
    """The stand-in for Schwab's network: a price-history function answering, for each symbol,
    the candles built from these captured minutes that start in the asked range (an Exception
    instance: the request fails)."""
    def fetch(symbol, start, end):
        if asked is not None:
            asked.append((symbol, start, end))
        answer = by_symbol.get(symbol, [])
        if isinstance(answer, Exception):
            raise answer
        return [_candle(b) for b in answer if start <= b["timestamp"] / 1000.0 < end]
    return fetch


def _subscribed(*symbols: str, command: str = "SUBS") -> dict:
    """The daemon's message for a CHART_EQUITY request Schwab acknowledged (capture.Daemon.sync)."""
    return subscription_msg(service="CHART_EQUITY", command=command, symbols=list(symbols), code=0, reason="ok")


async def _settled(srv_ui) -> None:
    """Wait until no price-history request is out."""
    while any(d.asking for d in srv_ui.days.values()):
        await asyncio.sleep(0.005)


async def _start_day(srv_ui, client, msg) -> None:
    """Subscribe the symbol, stream its first minute and wait for the price-history request its
    uncovered minutes made; the updates sent so far are dropped."""
    srv_ui.on_subscription(_subscribed(msg["symbol"]))
    srv_ui.on_bar(msg)
    await _settled(srv_ui)
    client.bars.clear()


class _Ws:
    """A browser socket that keeps what it is sent."""
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _pushed(streamed, history, subscribe=("SPY",), after_start=None, stats=None):
    """Start the daemon's browser socket at RESTART, with `history` as Schwab's price history,
    call `after_start()` once it is listening, publish `streamed` on its bus, and return every
    bar update a browser subscribed to `subscribe` received, and every price-history message
    (barhist.*) published on its bus."""
    from websockets.asyncio.client import connect

    async def main():
        port, bus, stop = _free_port(), MessageBus(), asyncio.Event()
        st = stats if stats is not None else {}
        published = bus.subscribe("barhist.", maxsize=65536, name="test_published")
        feed = lambda: {"ts": RESTART, "schwab_socket_open": True, "held": {}, "health": {}}  # noqa: E731
        task = asyncio.create_task(live_ui.serve_live_ui(bus, stop, heartbeat_fn=feed, clock=lambda: RESTART,
                                                         host="127.0.0.1", port=port, stats=st,
                                                         history_fn=history))
        while not st.get("listening"):
            await asyncio.sleep(0.01)
        if after_start is not None:
            after_start()
        got = []
        try:
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"op": "subscribe", "symbols": list(subscribe)}))
                # Schwab acknowledges the daemon's CHART_EQUITY subscription of each streamed symbol
                bus.publish("sub.CHART_EQUITY", _subscribed(*sorted({b["symbol"] for b in streamed})))
                await asyncio.sleep(0.2)
                for b in streamed:
                    bus.publish(f"bar1m.{b['symbol']}", b)
                    await asyncio.sleep(0.01)
                end = time.monotonic() + 3
                while time.monotonic() < end and st.get("bars_sent", 0) < len(streamed):
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
        out = []
        while not published.queue.empty():
            out.append((await published.get())[1])
        return got, out
    return asyncio.run(main())


def test_the_pushed_bar_is_the_routes_bar_at_every_timeframe(monkeypatch, tmp_path):
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    stored, streamed = FRIDAY[:100], FRIDAY[100:140]
    for b in stored:                                 # written before the daemon (re)started
        assert srv._write_streamed_bar(_msg(b))
    got, _published = _pushed([_msg(b) for b in streamed], _schwab({"SPY": stored}))
    assert {u["ticker"] for u in got} == {"SPY"}
    for b in streamed:                               # the console writes the same bars
        assert srv._write_streamed_bar(_msg(b))
    last = got[-1]
    assert last["ts_recv"] == _msg(streamed[-1])["ts_recv"]
    for tf in live_price_rows.CHART_TFS:
        route = json.loads(srv.get_bars1m(ticker="SPY", tf=tf, limit=12000).body)
        assert last["tf"][tf] == route["bars"][-1], tf
        assert last["last_bar"] == route["last_bar"]
    # the daily bar holds the minutes Schwab's price history gave as well as the streamed ones; it is
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


def test_no_live_bar_is_built_from_the_database(monkeypatch):
    """The database is history: no live bar reads it. With every database read failing, a
    symbol's bars are still pushed, its daily bar holding the day's earlier minutes Schwab's price
    history gave. The daemon read the store for them (in session, then at its startup)."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    earlier, streamed = FRIDAY[:100], FRIDAY[100:110]
    reads = []

    def unreadable(*a, **k):
        reads.append(a)
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", unreadable)
    got, _published = _pushed([_msg(b) for b in streamed], _schwab({"SPY": earlier}))
    assert reads == []
    assert {u["tf"]["1"]["t"] for u in got} == {b["timestamp"] / 1000.0 for b in streamed}
    whole = [u for u in got if "D" in u["tf"]]
    assert whole and whole[-1]["tf"]["D"]["o"] == earlier[0]["open"]   # Schwab's earlier minutes


def test_a_symbol_streamed_mid_day_pushes_the_whole_days_bars(monkeypatch, tmp_path):
    """A symbol the daemon starts streaming mid-day pushes every timeframe's bar and its Order
    Flow hour equal to the route's: its earlier minutes come from Schwab's price history, asked
    when it starts streaming; until they arrive nothing above 1 minute is served as complete. Real
    SPY CHART_EQUITY bars of 2026-09-25 under the symbol QQQ (the stand-in for QQQ's own)."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    earlier, streamed = FRIDAY[:100], FRIDAY[100:110]
    for b in earlier:                                # the store has the day (the chart's history)
        assert srv._write_streamed_bar(_msg(b, sym="QQQ"))
    asked = []
    got, _published = _pushed([_msg(b, sym="QQQ") for b in streamed], _schwab({"QQQ": earlier}, asked),
                              subscribe=("QQQ",))
    for b in streamed:                               # the console writes the streamed bars
        assert srv._write_streamed_bar(_msg(b, sym="QQQ"))
    # asked once, for exactly the minutes before the first one streamed
    assert asked == [("QQQ", datetime(2026, 9, 25, 9, 15, tzinfo=ET).timestamp(), RESTART)]
    last = got[-1]
    for tf in live_price_rows.CHART_TFS:
        assert last["tf"][tf] == json.loads(srv.get_bars1m(ticker="QQQ", tf=tf, limit=12000).body)["bars"][-1], tf
    assert last["recent_1m"] == json.loads(srv.get_bars1m(ticker="QQQ", tf="30", limit=9000).body)["recent_1m"]
    # before the earlier minutes arrived nothing above 1 minute was served as complete
    first = got[0]
    assert {"D", "60", "30"}.isdisjoint(first["tf"]) and first["recent_1m"] is None
    assert first["unavailable"]["D"] == ("minutes Fri 09/25 08:15 AM CT – Fri 09/25 10:09 AM CT "
                                         "not received from Schwab")


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
                                                         host="127.0.0.1", port=port, stats=stats,
                                                         history_fn=_schwab({})))
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
    that bucket's bar is the route's roll-up of the day so far, at every minute (every minute
    covered)."""
    day = [live_price_rows.minute_bar(_msg(b)) for b in FRIDAY]
    for k in range(len(day)):
        so_far = day[:k + 1]
        whole = [(live_price_rows.session_first_minute(so_far[0]["t"]), so_far[-1]["t"])]
        update = live_price_rows.bar_update("SPY", so_far, so_far[-1], 0.0, whole)
        for tf in live_price_rows.CHART_TFS:
            assert update["tf"][tf] == live_price_rows.served_bar(live_price_rows.aggregate_bars(so_far, tf)[-1], tf), (k, tf)


def test_a_bar_that_is_not_a_chart_bar_or_not_subscribed_is_never_pushed(tmp_path):
    """A price sent as -999 (not a number), a minute outside the stored
    window (09:14 ET, before 09:15), and a symbol no browser asked for: none reaches the browser."""
    ok, bad, early = FRIDAY[10], dict(FRIDAY[11], close=-999), dict(FRIDAY[0])
    early["timestamp"] = int(datetime(2026, 9, 25, 9, 13, tzinfo=ET).timestamp() * 1000)
    got, _published = _pushed([_msg(ok), _msg(bad), _msg(early), _msg(FRIDAY[12], sym="QQQ")], _schwab({}))
    assert got and {u["ticker"] for u in got} == {"SPY"}
    assert {u["tf"]["1"]["t"] for u in got} == {ok["timestamp"] / 1000.0}
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
    CHART_EQUITY bars of 2026-09-25, delivered out of order (the order is the stand-in); Schwab's
    price history (the stand-in for its network) answers the minutes before the first streamed."""
    order = [FRIDAY[i] for i in (10, 11, 13, 14, 12, 15, 9, 16)]

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: RESTART,
                                      history_fn=_schwab({"SPY": FRIDAY}))
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        await _start_day(srv_ui, c, _msg(order[0]))
        for b in order[1:]:
            srv_ui.on_bar(_msg(b))
        pump = asyncio.create_task(srv_ui._pump(c))
        await asyncio.sleep(0.05)
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        return [u for f in c.ws.sent if f["type"] == "bars" for u in f["bars"]]

    sent = asyncio.run(main())                           # one update per minute after the first
    assert len(sent) == len(order) - 1
    for tf in live_price_rows.CHART_TFS:                 # each chart's pushes only move forward
        times = [u["tf"][tf]["t"] for u in sent if tf in u["tf"]]
        assert times == sorted(times), tf
    for k, update in enumerate(sent):
        held = sorted({live_price_rows.minute_bar(_msg(b))["t"]: live_price_rows.minute_bar(_msg(b))
                       for b in FRIDAY[:10] + order[:k + 2]}.values(), key=lambda m: m["t"])
        assert "D" in update["tf"], k                    # the daily bar keeps being pushed
        for tf, bar in update["tf"].items():             # every bar pushed holds every minute held
            assert bar == live_price_rows.served_bar(live_price_rows.aggregate_bars(held, tf)[-1], tf), (k, tf)
        assert [m["t"] for m in update["recent_1m"]] == [m["t"] for m in held][-live_price_rows.RECENT_1M_BARS:]
    for k in (3, 5):                                     # the late minutes' own bars are not tails
        assert "1" not in sent[k]["tf"], k
    assert sent[3]["tf"]["5"]["t"] == sent[2]["tf"]["5"]["t"]   # the bar it joins keeps its time
    assert sent[5]["tf"]["D"]["t"] == sent[4]["tf"]["D"]["t"] == datetime(2026, 9, 25, tzinfo=ET).timestamp()


def test_bars_that_arrive_before_the_next_send_are_all_sent_in_order():
    """Every completed minute reaches the browser: three bars of one symbol received before the
    browser's next send go out as three updates, oldest first (a newer bar used to replace an
    unsent older one, and that minute never reached the chart)."""
    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: RESTART,
                                      history_fn=_schwab({"SPY": FRIDAY}))
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        await _start_day(srv_ui, c, _msg(FRIDAY[9]))
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


def test_the_streamed_minute_stands_over_schwabs_price_history_and_a_difference_is_recorded(caplog):
    """Where the stream and the price history both give a minute, the streamed one stands and is
    never replaced; a difference between the two is counted and logged with both, never settled
    silently. Real SPY bars of 2026-09-25; the price history's 12th minute differs (its close
    0.10 higher), the stand-in for a difference."""
    differing = dict(FRIDAY[11], close=FRIDAY[11]["close"] + 0.10)
    stats: dict = {}

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, stats, clock=lambda: RESTART,
                                      history_fn=_schwab({"SPY": FRIDAY[:11] + [differing]}))
        srv_ui.on_bar(_msg(FRIDAY[11]))      # streamed before its subscription was acknowledged:
        await _settled(srv_ui)               # uncovered, so the price history is asked for it too
        return srv_ui.days["SPY"]

    day = asyncio.run(main())
    t = FRIDAY[11]["timestamp"] / 1000.0
    assert day.minutes[t] == live_price_rows.minute_bar(_msg(FRIDAY[11])) and day.source[t] == live_ui.SRC_STREAM
    assert [day.source[b["timestamp"] / 1000.0] for b in FRIDAY[:11]] == [live_ui.SRC_PRICEHISTORY] * 11
    assert stats["bar_source_mismatches"] == 1
    (line,) = [r.getMessage() for r in caplog.records if "differ" in r.getMessage()]
    assert str(FRIDAY[11]["close"]) in line and str(differing["close"]) in line


def test_a_failed_price_history_request_serves_the_bars_above_1m_unavailable_until_a_retry(monkeypatch):
    """A failed request for the uncovered minutes leaves every bar above 1 minute and the Order
    Flow hour unavailable, naming the minutes not received and the failure; never a partial bar
    served as complete. The symbol's next streamed minute asks again; once received, the bars are
    whole. Real SPY bars of 2026-09-25; the stand-in for Schwab's network fails once (HTTP 429),
    then answers."""
    answers = [RuntimeError("HTTP 429 Too Many Requests")]
    asked = []
    truth = _schwab({"SPY": FRIDAY})

    def history(symbol, start, end):
        asked.append(symbol)
        if answers:
            raise answers.pop(0)
        return truth(symbol, start, end)

    stats: dict = {}

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, stats, clock=lambda: RESTART + 70, history_fn=history)
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        srv_ui.on_subscription(_subscribed("SPY"))
        srv_ui.on_bar(_msg(FRIDAY[100]))
        await _settled(srv_ui)
        srv_ui.on_bar(_msg(FRIDAY[101]))
        await _settled(srv_ui)
        return list(c.bars)

    first, failed, retried, whole = asyncio.run(main())
    assert asked == ["SPY", "SPY"]                                   # asked again on the next minute
    gone = "minutes Fri 09/25 08:15 AM CT – Fri 09/25 10:09 AM CT not received from Schwab"
    for update in (first, failed, retried):      # the bars reaching into the gap are not served
        assert {"D", "60", "30"}.isdisjoint(update["tf"]) and update["recent_1m"] is None
        assert update["unavailable"]["D"].startswith(gone)
    assert failed["unavailable"]["D"] == f"{gone} (Schwab's price history: RuntimeError: HTTP 429 Too Many Requests)"
    assert whole["unavailable"] == {} and whole["recent_1m"]
    assert whole["tf"]["D"]["o"] == FRIDAY[0]["open"]


def test_the_price_history_backfills_the_store_and_never_overwrites_a_stored_bar(monkeypatch, tmp_path):
    """The day's earlier minutes from Schwab's price history are published to the console's one
    bar writer, which writes the minutes the store lacks (source schwab_pricehistory) and leaves
    every stored bar as it is. Real SPY bars of 2026-09-25: the store has the first five minutes,
    streamed; the price history (the stand-in for Schwab's network) gives the first twenty, its
    first five 0.10 higher. The reply travels as one message (barhist.SPY), so a full queue
    cannot drop part of it, and it is not a stream message: stream_capture.db does not keep it."""
    import app.options.order_flow.streaming as ofs
    from app.market_data.schwab.streaming.live_push import is_forwarded
    from stream_spine import CaptureWriter
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    for b in FRIDAY[:5]:
        assert srv._write_streamed_bar(_msg(b))
    history = [dict(b, close=b["close"] + 0.10) for b in FRIDAY[:5]] + FRIDAY[5:20]
    _got, published = _pushed([_msg(FRIDAY[100])], _schwab({"SPY": history}))
    (reply,) = published                                           # one message for the reply
    assert reply["src"] == live_ui.SRC_PRICEHISTORY
    assert [m["bar_start_ms"] for m in reply["bars"]] == [b["timestamp"] for b in history]
    assert is_forwarded("barhist.SPY", reply)                      # the daemon forwards it
    writer = CaptureWriter(tmp_path / "stream_capture.db")
    writer.insert("barhist.SPY", reply)
    assert writer.rows_written == 0                                # not a stream message
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get()
    ofs._ingest_pushed("barhist.SPY", reply)                       # the console's ingest
    srv._write_streamed_bars([ofs.streamed_bars.get() for _ in range(ofs.streamed_bars.qsize())])
    con = sqlite3.connect(db.db_path)
    try:
        rows = con.execute("SELECT bar_start_ts_utc, close, source FROM price_bars_1m WHERE ticker='SPY' "
                           "ORDER BY bar_start_ts_utc").fetchall()
    finally:
        con.close()
    assert rows == ([(b["timestamp"] / 1000.0, b["close"], "schwab_chart_equity") for b in FRIDAY[:5]]
                    + [(b["timestamp"] / 1000.0, b["close"], "schwab_pricehistory") for b in FRIDAY[5:20]])


def test_the_daemon_asks_schwab_for_the_days_minutes_with_extended_hours():
    """The daemon's one price-history call (capture.schwab_minutes): Schwab's
    get_price_history_every_minute for the symbol, from the start to the end it is given, with
    extended hours (the collect window opens 09:15 ET), and Schwab's candles as sent, asked with
    the daemon's one Schwab client (every request built its own from the token file). The stand-in
    is Schwab's client, answering the captured minutes."""
    from app.market_data.schwab.streaming.capture import Daemon, schwab_minutes
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"symbol": "SPY", "empty": False, "candles": [_candle(b) for b in FRIDAY[:3]]}

    class _Client:
        def get_price_history_every_minute(self, symbol, **kw):
            calls.append((symbol, kw))
            return _Response()

    daemon = Daemon(MessageBus(), None, Path("unused_wanted.json"))
    daemon.client = _Client()
    fetch = schwab_minutes(daemon)
    start, end = datetime(2026, 9, 25, 9, 15, tzinfo=ET).timestamp(), RESTART
    assert fetch("SPY", start, end) == [_candle(b) for b in FRIDAY[:3]]
    assert fetch("QQQ", start, end) == [_candle(b) for b in FRIDAY[:3]]
    (symbol, kw), (other, _kw) = calls                    # both on the daemon's one client
    assert (symbol, other) == ("SPY", "QQQ") and kw["need_extended_hours_data"] is True
    assert kw["start_datetime"].timestamp() == start and kw["end_datetime"].timestamp() == end


def test_without_a_schwab_sign_in_the_reason_served_is_schwabs_own(monkeypatch):
    """A missing or expired Schwab token surfaced as "AttributeError: 'NoneType' object has no
    attribute ..." on the charts. The daemon keeps the reason its Schwab client could not be built
    (Schwab's own message) and the price history serves it as the unavailable reason. The stand-in
    is the client builder's answer for an expired token."""
    from types import SimpleNamespace

    from app.market_data.schwab.streaming.capture import Daemon, schwab_minutes
    expired = "refresh token expired; run python reauth_schwab.py"
    daemon = Daemon(MessageBus(), None, Path("unused_wanted.json"))

    async def run_once():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.run(lambda: SimpleNamespace(ok=False, client=None, message=expired), stop))
        while daemon.client_problem is None or expired not in daemon.client_problem:
            await asyncio.sleep(0.005)
        stop.set()
        await task
    asyncio.run(run_once())
    stats: dict = {}

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, stats, clock=lambda: RESTART,
                                      history_fn=schwab_minutes(daemon))
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        srv_ui.on_subscription(_subscribed("SPY"))
        srv_ui.on_bar(_msg(FRIDAY[100]))
        await _settled(srv_ui)
        return list(c.bars)[-1]
    update = asyncio.run(main())
    assert update["unavailable"]["D"] == (
        "minutes Fri 09/25 08:15 AM CT – Fri 09/25 10:09 AM CT not received from Schwab "
        f"(Schwab's price history: ConnectionError: Schwab client: {expired})")


def test_at_most_two_price_history_requests_are_in_flight(monkeypatch):
    """About 45 symbols start streaming together (the daemon's start, the open): each asked
    Schwab's price history at once. They go HISTORY_IN_FLIGHT (two) at a time. Real SPY bars of
    2026-09-25 under six symbols (the stand-in), Schwab's network the stand-in, held until
    released."""
    import threading
    gate, lock, state = threading.Event(), threading.Lock(), {"now": 0, "max": 0}

    def history(symbol, start, end):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        gate.wait(5)
        with lock:
            state["now"] -= 1
        return []

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: RESTART, history_fn=history)
        for sym in ("SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT"):
            srv_ui.on_bar(_msg(FRIDAY[100], sym=sym))
        await asyncio.sleep(0.2)
        in_flight = state["now"]
        gate.set()
        await _settled(srv_ui)
        return in_flight
    assert asyncio.run(main()) == live_ui.HISTORY_IN_FLIGHT == 2
    assert state["max"] == 2


def test_a_full_bus_queue_is_logged_not_silent(caplog):
    """A consumer's full queue drops a message: counted, and logged (at 1, 2, 4, ... drops), so a
    lost bar or price-history reply is never silent."""
    bus = MessageBus()
    sub = bus.subscribe("barhist.", maxsize=1, name="console")
    for b in FRIDAY[:3]:
        bus.publish("barhist.SPY", {"symbol": "SPY", "bars": [_msg(b)]})
    assert sub.dropped == 2
    assert [r.getMessage() for r in caplog.records if "dropped" in r.getMessage()] == [
        "bus: the 'barhist.' consumer's queue is full: 1 messages dropped (latest barhist.SPY)",
        "bus: the 'barhist.' consumer's queue is full: 2 messages dropped (latest barhist.SPY)"]


#: what a day's stream suffers: Schwab acknowledges an UNSUBS of the symbol and later a SUBS
#: (leave), the Schwab socket closes and the daemon reconnects (reconnect), the daemon restarts
#: holding nothing (restart), the next price-history reply is empty (empty) or lacks its newest
#: three minutes, not yet in Schwab's history (lagging)
CUTS = ("leave", "reconnect", "restart", "empty", "lagging")


def _replay(minutes: list[dict], first: int, cuts: dict, away: dict,
            ack_after: "frozenset[int]" = frozenset()) -> "tuple[list, list]":
    """Stream `minutes` (real SPY CHART_EQUITY minutes of 2026-09-25) from index `first` (the
    daemon started then) to the daemon's browser push, each at its receive time, with Schwab's
    price history answering from the same `minutes` (the stand-in for its network). Before
    minute k, `cuts[k]` happens; a leave, reconnect or restart keeps the next `away[k]` minutes
    from being streamed, then Schwab acknowledges the SUBS again: before the next minute, or,
    for a minute in `ack_after`, after it (the acknowledgement and the bar travel on separate
    bus queues). The socket's close is the daemon's own message (capture.Daemon.disconnect).
    Returns, per streamed minute k, the updates a browser was sent once the requests that minute
    made were answered, and every request (start, end)."""
    from app.market_data.schwab.streaming.capture import Daemon
    truth, asked, faults, clock = _schwab({"SPY": minutes}), [], [], {"now": 0.0}

    def history(symbol, start, end):
        asked.append((start, end))
        got = truth(symbol, start, end)
        fault = faults.pop(0) if faults else None
        return [] if fault == "empty" else got[:-3] if fault == "lagging" else got

    def start():
        s = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: clock["now"], history_fn=history)
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        s.clients.add(c)
        return s, c

    async def main():
        daemon = Daemon(MessageBus(), None, Path("unused_wanted.json"))
        closed = daemon.bus.subscribe("sub.", maxsize=64, name="test_subscriptions")
        (srv_ui, c), steps, away_left, ack = start(), [], 0, True
        for k in range(first, len(minutes)):
            clock["now"] = minutes[k]["timestamp"] / 1000.0 + 62.7
            cut = None if away_left else cuts.get(k)
            if cut in ("empty", "lagging"):
                faults.append(cut)
            elif cut == "leave":
                srv_ui.on_subscription(_subscribed("SPY", command="UNSUBS"))
            elif cut == "reconnect":
                await daemon.disconnect()
                srv_ui.on_subscription((await closed.get())[1])
            elif cut == "restart":
                srv_ui, c = start()
            if cut in ("leave", "reconnect", "restart"):
                away_left, ack = away.get(k, 0), True
            if away_left:
                away_left -= 1
                continue
            if ack and k not in ack_after:
                srv_ui.on_subscription(_subscribed("SPY"))
                ack = False
            srv_ui.on_bar(_msg(minutes[k]))
            await _settled(srv_ui)
            if ack:
                srv_ui.on_subscription(_subscribed("SPY"))
                ack = False
            steps.append((k, list(c.bars)))
            c.bars.clear()
        return steps
    return asyncio.run(main()), asked


def _check(steps: list, minutes: list[dict], why: str) -> int:
    """Every update: each timeframe's bar is either served or unavailable with its reason, and a
    served bar (and the Order Flow hour) is the roll-up of every Schwab minute through the newest
    (a bar missing a minute differs from it). Returns how many updates served the daily bar."""
    day = [live_price_rows.minute_bar(_msg(b)) for b in minutes]
    whole = 0
    for k, updates in steps:
        for u in updates:
            held = [m for m in day if m["t"] <= u["last_bar"]["t"]]
            for tf in live_price_rows.CHART_TFS:
                assert (tf in u["tf"]) != (tf in u["unavailable"]), (why, k, tf)
                if tf in u["tf"]:
                    assert u["tf"][tf] == live_price_rows.served_bar(
                        live_price_rows.aggregate_bars(held, tf)[-1], tf), (why, k, tf)
            if u["recent_1m"] is not None:
                assert u["recent_1m"] == live_price_rows.recent_1m(held), (why, k)
            whole += "D" in u["tf"]
    return whole


def _t(k: int) -> float:
    return FRIDAY[k]["timestamp"] / 1000.0


def test_a_day_cut_at_random_never_serves_a_bar_missing_a_minute_and_ends_whole(monkeypatch, tmp_path):
    """A real day's minutes (SPY 2026-09-25) replayed with the stream cut at random points:
    unsubscribed and back, the socket reconnecting, an empty or lagging price-history reply, the
    daemon restarting. After every step no bar is served unless it holds every minute (a bar was
    served complete from whatever minutes were held, and a gap after the first streamed minute
    was never asked for); once the price history covers the gaps, every bar is the route's. The
    seed is printed (ED_REPLAY_SEED replays one)."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    for b in FRIDAY:
        assert srv._write_streamed_bar(_msg(b))
    route = {tf: json.loads(srv.get_bars1m(ticker="SPY", tf=tf, limit=12000).body) for tf in live_price_rows.CHART_TFS}
    seed = int(os.environ.get("ED_REPLAY_SEED") or random.randrange(2 ** 32))
    print(f"seed {seed}")
    rng = random.Random(seed)
    for run in range(4):
        first, cuts, away, ack_after = rng.randint(1, 60), {}, {}, set()
        for k in range(first + 1, len(FRIDAY) - 20):           # the last 20 minutes settle the day
            if rng.random() < 0.05:
                cuts[k], away[k] = rng.choice(CUTS), rng.randint(0, 6)
                if rng.random() < 0.5:
                    ack_after.add(k + away[k])
        why = f"seed {seed} run {run} first {first} cuts {cuts} away {away} ack after {sorted(ack_after)}"
        steps, _asked = _replay(FRIDAY, first, cuts, away, frozenset(ack_after))
        assert _check(steps, FRIDAY, why), why
        last = steps[-1][1][-1]
        assert last["unavailable"] == {}, why
        for tf in live_price_rows.CHART_TFS:
            assert last["tf"][tf] == route[tf]["bars"][-1], (why, tf)
        assert last["recent_1m"] == route["30"]["recent_1m"], why


def _gone(a: int, b: int) -> str:
    return f"minutes {ct_label(_t(a))} – {ct_label(_t(b))} not received from Schwab"


def _whole_after(steps: list, k: int) -> None:
    """At minute k the update before the reply named the gap; the one after it is whole."""
    (at,) = [u for j, u in steps if j == k]
    assert len(at) == 2 and at[1]["unavailable"] == {}
    assert at[1]["tf"]["D"]["o"] == FRIDAY[0]["open"] and at[1]["recent_1m"]


def test_a_symbol_unsubscribed_and_back_asks_for_exactly_the_minutes_it_missed():
    """Schwab acknowledges an UNSUBS at 10:20 CT and a SUBS four minutes later: the minutes
    between were not streamed, so every bar holding them is unavailable naming them, and exactly
    they are asked of the price history; once received, the bars are whole. A re-subscription
    was not asked for at all: the bars above 1 minute were served without those minutes."""
    steps, asked = _replay(FRIDAY, 100, {110: "leave"}, {110: 4})
    assert _check(steps, FRIDAY, "leave")
    (at,) = [u for j, u in steps if j == 114]
    assert at[0]["unavailable"]["D"] == _gone(110, 113) and at[0]["recent_1m"] is None
    assert asked[-1] == (_t(110), _t(113) + 60.0)
    _whole_after(steps, 114)
    # the first minute back received before the SUBS acknowledgement is uncovered too
    steps, asked = _replay(FRIDAY, 100, {110: "leave"}, {110: 4}, frozenset({114}))
    assert _check(steps, FRIDAY, "leave, acknowledged after the minute")
    assert asked[-1] == (_t(110), _t(114) + 60.0)
    _whole_after(steps, 114)


def test_a_reconnect_ends_the_streams_coverage_and_the_missed_minutes_are_asked():
    """The daemon's Schwab socket closes (its own sub.CONNECTION message, capture.Daemon.
    disconnect) and comes back three minutes later, its first minute received before Schwab's
    acknowledgement of the new subscription: those minutes and that one are unavailable and
    asked, then whole. A reconnect was not seen at all by the bars; the stream's coverage
    surviving the close would cover the missed minutes with that first one."""
    steps, asked = _replay(FRIDAY, 100, {110: "reconnect"}, {110: 3}, frozenset({113}))
    assert _check(steps, FRIDAY, "reconnect")
    (at,) = [u for j, u in steps if j == 113]
    assert at[0]["unavailable"]["60"] == _gone(110, 113)
    assert asked[-1] == (_t(110), _t(113) + 60.0)
    _whole_after(steps, 113)


def test_an_empty_price_history_reply_covers_nothing_and_is_asked_again():
    """The price history answers the missed minutes with no candles: nothing is covered and the
    bars stay unavailable (no second push: nothing changed); the next streamed minute asks
    again, and that reply makes them whole."""
    steps, asked = _replay(FRIDAY, 100, {105: "empty", 110: "leave"}, {110: 2})
    assert _check(steps, FRIDAY, "empty")
    (at,) = [u for j, u in steps if j == 112]
    assert len(at) == 1 and at[0]["unavailable"]["D"] == _gone(110, 111)
    assert asked[-2:] == [(_t(110), _t(111) + 60.0)] * 2
    _whole_after(steps, 113)


def test_a_lagging_price_history_reply_covers_only_what_it_holds():
    """The price history answers five missed minutes without its newest three (not yet in
    Schwab's history): it covers through its newest minute, the bars stay unavailable naming the
    three, and the next streamed minute asks for exactly them."""
    steps, asked = _replay(FRIDAY, 100, {105: "lagging", 110: "leave"}, {110: 5})
    assert _check(steps, FRIDAY, "lagging")
    (at,) = [u for j, u in steps if j == 115]
    assert at[0]["unavailable"]["D"] == _gone(110, 114)
    assert at[1]["unavailable"]["D"] == _gone(112, 114)
    assert asked[-2:] == [(_t(110), _t(114) + 60.0), (_t(112), _t(114) + 60.0)]
    _whole_after(steps, 116)


def test_a_daemon_restarted_mid_day_asks_for_the_day_before_its_first_minute():
    """The daemon restarts holding nothing and is subscribed again two minutes later: the day
    from 09:15 ET to its first streamed minute is asked, and the bars are whole once received."""
    steps, asked = _replay(FRIDAY, 100, {110: "restart"}, {110: 2})
    assert _check(steps, FRIDAY, "restart")
    (at,) = [u for j, u in steps if j == 112]
    gone = f"minutes {ct_label(live_price_rows.session_first_minute(_t(0)))} – {ct_label(_t(111))} not received from Schwab"
    assert at[0]["unavailable"]["D"] == gone
    assert asked[-1] == (live_price_rows.session_first_minute(_t(0)), _t(111) + 60.0)
    _whole_after(steps, 112)


def test_a_covered_minute_with_no_bar_is_no_trade_and_an_uncovered_one_is_unavailable():
    """Inside a span the stream covers, a minute Schwab sends no bar for is a minute with no
    trade: the 5-minute bar is served without it and nothing is asked. The same minute not
    streamed because the symbol was unsubscribed is unavailable, named, until the price history
    answers it. Real SPY minutes of 2026-09-25; the no-trade minute (11:15 ET) is the stand-in,
    removed from both the stream and the price history."""
    no_trade = FRIDAY[:105] + FRIDAY[106:]
    steps, asked = _replay(no_trade, 100, {}, {})
    assert _check(steps, no_trade, "no trade")
    (at,) = [u for j, u in steps if j == 105]                  # 11:16 ET, the 5m bucket 11:15
    assert at[0]["unavailable"] == {} and at[0]["tf"]["5"]["t"] == _t(105)
    assert asked == [(live_price_rows.session_first_minute(_t(0)), _t(100))]
    steps, asked = _replay(FRIDAY, 100, {105: "leave"}, {105: 1})
    (at,) = [u for j, u in steps if j == 106]
    assert "5" not in at[0]["tf"] and at[0]["unavailable"]["5"] == _gone(105, 105)
    assert asked[-1] == (_t(105), _t(105) + 60.0)
    _whole_after(steps, 106)


def test_the_regular_session_high_and_low_are_reconciled_with_schwabs_and_a_mismatch_is_flagged(monkeypatch, caplog):
    """The daily bar's regular-session high and low, from the covered minutes, are compared with
    Schwab's LEVELONE_EQUITIES HIGH_PRICE and LOW_PRICE (regular-session trades only, Streamer
    Guide p.17). A mismatching high is flagged on the bar update with both values, counted and
    logged once; nothing is corrected. A 0 is not compared. Real SPY minutes 09:30-09:59 ET of
    2026-09-25; Schwab's HIGH_PRICE 0.05 above the bars' high is the stand-in for a mismatch."""
    monkeypatch.setattr(lmp, "_by_ticker", {})
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    stats: dict = {}
    high, low = max(b["high"] for b in FRIDAY[:30]), min(b["low"] for b in FRIDAY[:30])

    async def main(quote):
        monkeypatch.setattr(lmp, "_fields_by_ticker", {})
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, stats, clock=lambda: _t(29) + 62.7,
                                      history_fn=_schwab({"SPY": FRIDAY}))
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        srv_ui.on_subscription(_subscribed("SPY"))
        for b in FRIDAY[:30]:
            if b is FRIDAY[29]:               # Schwab's day high and low as of 09:59 ET
                lmp.record_from_level_one_equity("SPY", dict(LAST_PRICE=b["close"], **quote), received_ts=_t(29) + 62.7)
            srv_ui.on_bar(_msg(b))
            await _settled(srv_ui)
        return [u["reconciliation"]["state"] for u in c.bars[:-1]], c.bars[-1]["reconciliation"]

    before, flag = asyncio.run(main({"HIGH_PRICE": high + 0.05, "LOW_PRICE": low}))
    assert set(before) == {live_price_rows.RECONCILE_NOT_COMPARED}     # no HIGH_PRICE received yet
    assert flag == {"state": live_price_rows.RECONCILE_MISMATCH, "bars_high": high, "bars_low": low,
                    "schwab_high": high + 0.05, "schwab_low": low}
    assert stats["reconcile_mismatches"] == 1
    (line,) = [r.getMessage() for r in caplog.records if "HIGH_PRICE/LOW_PRICE" in r.getMessage()]
    assert f"{high}/{low}" in line and f"{high + 0.05}/{low}" in line
    assert asyncio.run(main({"HIGH_PRICE": high, "LOW_PRICE": low}))[1]["state"] == live_price_rows.RECONCILED
    assert asyncio.run(main({"HIGH_PRICE": 0, "LOW_PRICE": low}))[1]["state"] == live_price_rows.RECONCILE_NOT_COMPARED
