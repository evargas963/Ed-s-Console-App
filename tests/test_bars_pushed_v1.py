"""The daemon pushes each completed 1-minute bar to the browser (live_ui), as the chart bar it
makes at every timeframe; the chart's history is /api/bars1m. The two are one producer: the push
and the route give the same bar for the same minutes, however many of the day's minutes the
daemon streamed itself and how many Schwab's price history gave it when the symbol started
streaming.

Before this, the console wrote each bar and pushed `liquidity`, and every chart read
/api/bars1m again. Real Schwab CHART_EQUITY bars: SPY 2026-09-25
(tests/fixtures/real_spy_1m_bars_2026_09_24_25.json), through the real live_ui server, bus and
socket, and the real route. The one stand-in is Schwab's network: its price-history response is
built from the same captured minutes (`_schwab`)."""
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


#: the instant the daemon is serving, a stand-in: as Friday's 101st minute began
RESTART = FRIDAY[100]["timestamp"] / 1000.0


def _candle(b: dict) -> dict:
    """One minute as Schwab's price history sends it (get_price_history_every_minute)."""
    return {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
            "volume": b["volume"], "datetime": b["timestamp"]}


def _schwab(by_symbol: dict, asked: "list | None" = None):
    """The stand-in for Schwab's network: a price-history function answering, for each symbol,
    the candles built from these captured minutes (an Exception instance: the request fails)."""
    def fetch(symbol, start, end):
        if asked is not None:
            asked.append((symbol, start, end))
        answer = by_symbol.get(symbol, [])
        if isinstance(answer, Exception):
            raise answer
        return [_candle(b) for b in answer]
    return fetch


async def _start_day(srv_ui, client, msg) -> None:
    """Stream the symbol's first minute of the day and wait until Schwab's price history for its
    earlier minutes is received; the updates sent so far are dropped."""
    srv_ui.on_bar(msg)
    sym = live_ui.ticker_storage_key(msg["symbol"])
    while srv_ui.days[sym].earlier != live_ui.EARLIER_RECEIVED:
        await asyncio.sleep(0.005)
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
    assert [a[0] for a in asked] == ["QQQ"]          # asked once, when it started streaming
    assert asked[0][1] == datetime(2026, 9, 25, 9, 15, tzinfo=ET).timestamp() and asked[0][2] == RESTART
    last = got[-1]
    for tf in live_price_rows.CHART_TFS:
        assert last["tf"][tf] == json.loads(srv.get_bars1m(ticker="QQQ", tf=tf, limit=12000).body)["bars"][-1], tf
    assert last["recent_1m"] == json.loads(srv.get_bars1m(ticker="QQQ", tf="30", limit=9000).body)["recent_1m"]
    # before the earlier minutes arrived nothing above 1 minute was served as complete
    first = got[0]
    assert set(first["tf"]) == {"1"} and first["recent_1m"] is None
    assert first["unavailable"] == live_ui.EARLIER_MINUTES_UNAVAILABLE


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
    price history (the stand-in for its network) has no earlier minute."""
    order = [FRIDAY[i] for i in (10, 11, 13, 14, 12, 15, 9, 16)]

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: 0.0, history_fn=_schwab({}))
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
        held = sorted((live_price_rows.minute_bar(_msg(b)) for b in order[:k + 2]), key=lambda m: m["t"])
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
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, {}, clock=lambda: 0.0, history_fn=_schwab({}))
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
        c = live_ui._Client(_Ws())
        await _start_day(srv_ui, c, _msg(FRIDAY[11]))
        return srv_ui.days["SPY"]

    day = asyncio.run(main())
    t = FRIDAY[11]["timestamp"] / 1000.0
    assert day.minutes[t] == live_price_rows.minute_bar(_msg(FRIDAY[11])) and day.source[t] == live_ui.SRC_STREAM
    assert [day.source[b["timestamp"] / 1000.0] for b in FRIDAY[:11]] == [live_ui.SRC_PRICEHISTORY] * 11
    assert stats["bar_source_mismatches"] == 1
    (line,) = [r.getMessage() for r in caplog.records if "differ" in r.getMessage()]
    assert str(FRIDAY[11]["close"]) in line and str(differing["close"]) in line


def test_a_failed_price_history_request_serves_the_bars_above_1m_unavailable_until_a_retry(monkeypatch):
    """A failed request for the day's earlier minutes leaves every bar above 1 minute and the
    Order Flow hour unavailable, with the reason; never a partial bar served as complete. The
    symbol's next streamed minute asks again; once received, the bars are whole. Real SPY bars of
    2026-09-25; the stand-in for Schwab's network fails once (HTTP 429), then answers."""
    answers = [RuntimeError("HTTP 429 Too Many Requests"), FRIDAY[:100]]
    asked = []

    def history(symbol, start, end):
        asked.append(symbol)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return [_candle(b) for b in answer]

    stats: dict = {}

    async def main():
        srv_ui = live_ui.LiveUiServer(MessageBus(), lambda: {}, stats, clock=lambda: RESTART, history_fn=history)
        c = live_ui._Client(_Ws())
        c.symbols = frozenset({"SPY"})
        srv_ui.clients.add(c)
        srv_ui.on_bar(_msg(FRIDAY[100]))
        while stats["earlier_minutes_failures"] < 1:
            await asyncio.sleep(0.005)
        srv_ui.on_bar(_msg(FRIDAY[101]))
        while srv_ui.days["SPY"].earlier != live_ui.EARLIER_RECEIVED:
            await asyncio.sleep(0.005)
        return list(c.bars)

    first, failed, whole = asyncio.run(main())
    assert asked == ["SPY", "SPY"]                                   # asked again on the next minute
    for update in (first, failed):
        assert set(update["tf"]) == {"1"} and update["recent_1m"] is None
        assert update["unavailable"].startswith(live_ui.EARLIER_MINUTES_UNAVAILABLE)
    assert "HTTP 429" in failed["unavailable"]
    assert whole["unavailable"] is None and whole["recent_1m"]
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
        srv_ui.on_bar(_msg(FRIDAY[100]))
        while stats["earlier_minutes_failures"] < 1:
            await asyncio.sleep(0.005)
        srv_ui.on_bar(_msg(FRIDAY[101]))
        return list(c.bars)[-1]
    update = asyncio.run(main())
    assert update["unavailable"] == (f"{live_ui.EARLIER_MINUTES_UNAVAILABLE}: ConnectionError: "
                                     f"Schwab client: {expired}")


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
        while any(d.earlier != live_ui.EARLIER_RECEIVED for d in srv_ui.days.values()):
            await asyncio.sleep(0.005)
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
