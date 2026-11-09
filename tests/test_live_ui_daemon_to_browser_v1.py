"""Prices straight from the capture daemon to the browser (live_ui.py), end to end.

The REAL daemon-side server (serve_live_ui, its plane fed from a real stream_spine.MessageBus by
the daemon's follow_market), served at /ws by the program's real web server (server.app on
uvicorn with capture.PAGES), and a REAL WebSocket client standing in for the browser, over a
real local socket. No console startup work, no database. Proves:

  * a subscribed symbol gets its current row at once, then a row for every Schwab change;
  * the row is the one producer's row (live_price_rows.price_row): spot, feed verdict,
    Schwab trade age, and no bar (charts show Schwab's completed bars only);
  * a symbol nobody subscribed to is never sent;
  * the feed verdict rides every beat: a closed Schwab socket reads feed_live False within one
    beat, with no message needed from Schwab; the last values stand, and in session the row
    names the outage (docs/DATA_FLOW.md §2 D5);
  * the watchlist rides every beat as the daemon's status; a failed status is a beat with none;
  * a slow browser gets the newest row per symbol, never a backlog of stale ones;
  * shutdown is not held up by a connected browser.
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket

import psutil
import pytest
from websockets.asyncio.client import connect

import live_market_plane as lmp
import time_et
from app.market_data.schwab.streaming import capture, live_ui
from stream_spine import HealthRegistry, MessageBus, quote_msg
from tests.test_live_push_channel_v1 import listener, serve_page_socket


@pytest.fixture(autouse=True)
def _fresh_plane():
    """Each test starts from an empty quote plane, then the plane is put back."""
    quotes, fields = lmp._by_ticker, lmp._fields_by_ticker
    lmp._by_ticker = {}
    lmp._fields_by_ticker = {}
    yield
    lmp._by_ticker = quotes
    lmp._fields_by_ticker = fields


def _trade(sym: str, last: float, ts: float, **extra) -> dict:
    native = {
        "key": sym,
        "BID_PRICE": last - 0.01,
        "ASK_PRICE": last + 0.01,
        "LAST_PRICE": last,
        "TRADE_TIME_MILLIS": int(ts * 1000),
        "QUOTE_TIME_MILLIS": int(ts * 1000),
        **extra,
    }
    return quote_msg(
        symbol=sym,
        bid=last - 0.01,
        ask=last + 0.01,
        last=last,
        src="schwab_l1",
        ts_recv=ts,
        native=native,
    )


class _Feed:
    def __init__(self, held=("SPY", "AAPL"), clock=time_et.now):
        self.open = True
        self.held = list(held)
        self.clock = clock

    def __call__(self, now: float) -> dict:
        return {
            "ts": now,
            "schwab_socket_open": self.open,
            "held": {"LEVELONE_EQUITIES": self.held},
            "health": {},
        }


async def _run(body, feed=None):
    sock, url = listener()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    feed = feed if feed is not None else _Feed()
    server = asyncio.create_task(
        serve_page_socket(stop, sock, {"heartbeat_fn": feed, "stats": stats, "clock": feed.clock})
    )
    follower = asyncio.create_task(capture.Daemon(bus, HealthRegistry(), []).follow_market(stop))
    end = time_et.elapsed() + 5
    while "clients" not in stats and time_et.elapsed() < end:
        await asyncio.sleep(0.01)
    assert "clients" in stats  # serving
    try:
        async with connect(f"{url}/ws") as ws:
            await body(bus, ws, feed, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, follower, return_exceptions=True), 5)


async def _next_row(ws, sym, pred=lambda _r: True, timeout=3.0):
    end = time_et.elapsed() + timeout
    while time_et.elapsed() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time_et.elapsed())))
        for r in msg.get("rows") or []:
            if r["ticker"] == sym and pred(r):
                return msg, r
    raise AssertionError(f"no matching {sym} row within {timeout}s")


def test_a_schwab_trade_reaches_the_browser_as_a_finished_live_row():
    """In regular hours: the server's clock runs from _RTH."""
    clock = _clock_from(_RTH)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["spy"]}))
        now = clock()
        bus.publish("quote.SPY", _trade("SPY", 583.41, now))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["spot_disp"] == "583.41" and row["trade_time_ct"] is not None
        assert row["feed_live"] is True and row["spot_source"] == "streaming_plane"
        assert row["bid"] == pytest.approx(583.40) and row["ask"] == pytest.approx(583.42)
        assert row["trade_ts"] == pytest.approx(now, abs=0.001)  # epoch SECONDS
        assert row["trade_age_text"] in ("0s", "1s")
        assert "forming_1m" not in row
        # the next trade moves it, pushed on its own (not on the beat)
        t0 = time_et.elapsed()
        bus.publish("quote.SPY", _trade("SPY", 583.90, clock()))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.90)
        assert msg["type"] == "quotes"
        assert time_et.elapsed() - t0 < 0.15, "a change must go out immediately, not on the beat"

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_an_unsubscribed_symbol_is_never_sent():
    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.AAPL", _trade("AAPL", 230.0, time_et.now()))
        bus.publish("quote.SPY", _trade("SPY", 583.0, time_et.now()))
        frames = []
        end = time_et.elapsed() + 1.5 * live_ui.HEARTBEAT_SEC  # the rows, and a beat's rows
        while (left := end - time_et.elapsed()) > 0:
            try:
                frames.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
            except TimeoutError:
                break
        assert any(m["type"] == "feed" for m in frames), "a beat came within the window"
        assert all(r["ticker"] == "SPY" for m in frames for r in m.get("rows") or []), frames

    asyncio.run(_run(body))


def test_resubscribing_sends_the_new_symbols_current_rows_at_once():
    async def body(bus, ws, _feed, _stats):
        bus.publish("quote.AAPL", _trade("AAPL", 230.5, time_et.now()))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        msg, row = await _next_row(ws, "AAPL", lambda r: r["spot"] == 230.5, timeout=0.15)
        assert msg["type"] == "quotes"

    asyncio.run(_run(body))


def test_a_subscribe_is_answered_with_what_each_symbol_is_before_its_rows():
    """A subscribe is answered with what each symbol is, before its rows.

    ONE-14 (2026-09-28 audit): the page stripped "$" in eight places to match a row to what it
    asked for, and kept its own list of index roots. The daemon answers each subscribe with
    each asked-for symbol's key (what its rows carry) and display name, from instrument_identity,
    for an index typed bare or with "$", an ETF and a single name alike.
    """

    async def body(_bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX", "$VIX", "spy", "MU"]}))
        first = json.loads(await asyncio.wait_for(ws.recv(), 2))
        assert first == {
            "type": "symbols",
            "symbols": [
                {"requested": "SPX", "key": "$SPX", "display": "SPX"},
                {"requested": "$VIX", "key": "$VIX", "display": "VIX"},
                {"requested": "spy", "key": "SPY", "display": "SPY"},
                {"requested": "MU", "key": "MU", "display": "MU"},
            ],
        }

    asyncio.run(_run(body))


def test_an_index_typed_bare_is_served_under_its_storage_key():
    """The operator types "SPX"; Schwab keys "$SPX".

    The subscription goes through ticker_storage_key, so the typed form gets the index's rows. In
    regular hours (_RTH).
    """
    clock = _clock_from(_RTH)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX"]}))
        bus.publish("quote.$SPX", _trade("$SPX", 6512.25, clock()))
        _, row = await _next_row(ws, "$SPX", lambda r: r["spot"] == 6512.25)
        assert row["feed_live"] is True

    asyncio.run(_run(body, feed=_Feed(held=("$SPX",), clock=clock)))


#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH, _CLOSED = 1790780400.0, 1790820000.0


def _clock_from(start: float):
    """Return a clock running from `start` (the session the test is in); time still passes."""
    began = time_et.elapsed()
    return lambda: start + time_et.elapsed() - began


@pytest.mark.parametrize("start", [_RTH, _CLOSED], ids=["rth", "closed"])
def test_a_closed_schwab_socket_reads_feed_down_within_one_beat(start):
    """Nothing from Schwab; only the beat knows (docs/DATA_FLOW.md §2 D5).

    The last price and bid stand, and the row reads OFFLINE and names the outage, the market open
    or closed. Before the socket closes the row is LIVE in regular hours and NOT LIVE at 22:00,
    the market closed. The server's clock runs from `start` so the session is that hour, and time
    still passes.
    """
    clock = _clock_from(start)

    async def body(bus, ws, feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.SPY", _trade("SPY", 583.41, clock()))
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["feed_label"] == ("LIVE" if start == _RTH else "NOT LIVE")
        feed.open = False
        msg, row = await _next_row(
            ws, "SPY", lambda r: r["feed_label"] == "OFFLINE", timeout=1.5 * live_ui.HEARTBEAT_SEC
        )  # the next beat
        assert msg["type"] == "feed" and msg["feed"]["schwab_socket_open"] is False
        assert row["spot"] == 583.41 and row["bid"] == pytest.approx(583.40)
        assert row["feed_live"] is False and row["outage"].startswith(
            "Schwab LEVELONE_EQUITIES feed down during "
        )

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_a_symbol_the_daemon_does_not_hold_reads_feed_not_live():
    clock = _clock_from(_CLOSED)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["TSLA"]}))
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, clock()))
        msg, row = await _next_row(ws, "TSLA", lambda r: r["spot"] == 400.0)
        assert row["feed_live"] is False

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_a_missing_heartbeat_keeps_the_last_watchlist():
    """Carry the daemon's list on a beat, and no status on a beat whose status failed.

    The daemon holds SPY and TSLA: the page's socket carries them on a beat, as the daemon's own
    status. Then the daemon's status fails (induced: the status raises), and the next beat carries
    no status at all, never a list of its own: the page keeps the last list and says the daemon is
    not reporting (tests/e2e/console-watchlist-socket.spec.js).
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "TSLA"])
    failing = False

    def status(now: float) -> dict:
        if failing:
            raise RuntimeError("induced: the daemon's status failed")
        return daemon.status(now)

    async def beat(ws) -> dict:
        while (msg := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "feed":
            pass
        return msg

    async def go():
        nonlocal failing
        sock, url = listener()
        stop, stats = asyncio.Event(), {}
        served = asyncio.create_task(
            serve_page_socket(stop, sock, {"heartbeat_fn": status, "stats": stats})
        )
        try:
            while "clients" not in stats:
                await asyncio.sleep(0.01)
            async with connect(f"{url}/ws") as ws:
                live = await beat(ws)
                failing = True
                down = await beat(ws)
                while down["feed"] is not None:  # a beat already made before the failure
                    down = await beat(ws)
        finally:
            stop.set()
            await asyncio.wait_for(served, 5)
        return live, down

    try:
        live, down = asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        lmp.record_feed_down()
        with lmp._lock:
            lmp._feed["status"] = None
    assert live["feed"]["watchlist"] == ["SPY", "TSLA"] and live["feed"]["ts"] is not None
    assert down["feed"] is None


def test_a_burst_is_conflated_to_the_newest_row_per_symbol():
    """A browser that is behind gets the newest value of each symbol, never a stale backlog.

    Latest-value-per-symbol per client.
    """

    async def body(bus, ws, _feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        await _next_row(ws, "SPY")  # the (empty) snapshot
        for i in range(500):
            now = time_et.now()
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, now))
            bus.publish("quote.AAPL", _trade("AAPL", 200 + i / 100, now))
        _, spy = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(504.99))
        _, aapl = await _next_row(ws, "AAPL", lambda r: r["spot"] == pytest.approx(204.99))
        # 1000 messages, far fewer frames: the browser was never handed the backlog
        assert stats["rows_sent"] < 200, stats

    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_browser():
    async def body(_bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await _next_row(ws, "SPY")

    t0 = time_et.elapsed()
    asyncio.run(_run(body))
    assert time_et.elapsed() - t0 < 5


def test_a_page_before_the_first_schwab_quote_reads_no_price_until_one_comes():
    """A page that subscribes before the daemon holds any quote for its symbol is answered at once.

    It gets the row as it is: no price ("-" on the page), never a filler; Schwab's first quote
    then reaches it.
    """

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "symbols"
        msg, row = await _next_row(ws, "SPY")
        assert msg["type"] == "quotes"
        assert (row["spot"], row["spot_disp"], row["bid"], row["ask"]) == (None, None, None, None)
        bus.publish("quote.SPY", _trade("SPY", 583.41, time_et.now()))
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["spot_disp"] == "583.41"

    asyncio.run(_run(body))


def test_a_page_that_goes_away_mid_send_ends_only_its_own_connection():
    """One page's connection is cut (no close) while rows are being pushed to it.

    Its handler ends, and the other page keeps its rows and its beats.
    """

    async def body(bus, ws, _feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await _next_row(ws, "SPY")
        url = f"ws://127.0.0.1:{ws.remote_address[1]}/ws"
        gone = await connect(url)
        await gone.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(gone.recv(), 2)
        assert stats["clients"] == 2
        for i in range(200):
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, time_et.now()))
            if i == 100:
                gone.transport.abort()  # the page's side of the connection cut mid-burst
            await asyncio.sleep(0)
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(501.99))
        end = time_et.elapsed() + 5
        while stats["clients"] != 1 and time_et.elapsed() < end:
            await asyncio.sleep(0.01)
        assert stats["clients"] == 1
        msg, _ = await _next_row(ws, "SPY", timeout=2 * live_ui.HEARTBEAT_SEC)
        while msg["type"] != "feed":  # the beat goes on
            msg, _ = await _next_row(ws, "SPY", timeout=2 * live_ui.HEARTBEAT_SEC)

    asyncio.run(_run(body))


#: what the frozen page subscribed to: its first rows alone outgrow its 1 KB receive window
_WATCHED = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL"]


def _page_that_never_reads(port: int) -> socket.socket:
    """Open a page's connection that subscribes and then never reads (a frozen tab).

    Its receive window is 1 KB.
    """
    page = socket.socket()
    page.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)  # before connecting: the window
    page.connect(("127.0.0.1", port))
    key = base64.b64encode(b"never-read page!").decode()  # 16 bytes, as RFC 6455 4.1 asks
    page.sendall(
        f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    text = json.dumps({"op": "subscribe", "symbols": _WATCHED}, separators=(",", ":")).encode()
    assert len(text) < 126  # its length in the frame's second byte
    mask = b"\x01\x02\x03\x04"
    page.sendall(  # one masked text frame, as a browser sends it (RFC 6455 section 5.2)
        bytes([0x81, 0x80 | len(text)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(text))
    )
    return page


def _held_by_this_program(server_port: int, page: socket.socket) -> bool:
    """Whether the program still holds the server side of `page`'s connection open.

    Once it lets go, the system closes it (FIN_WAIT_1, its unsent bytes still offered to the page,
    which reads them and the end when it thaws, then reconnects), never ESTABLISHED.
    """
    page_port = page.getsockname()[1]
    return any(
        c.laddr.port == server_port
        and c.raddr
        and c.raddr.port == page_port
        and c.status == psutil.CONN_ESTABLISHED
        for c in psutil.net_connections("tcp")
    )


def test_a_page_that_stops_reading_while_little_is_sent_is_dropped_at_the_keepalive_ping(caplog):
    """A page that stops reading while its buffers are not full is dropped at the keepalive ping.

    It is found by the keepalive ping it does not answer, and its connection is aborted
    (live_ui.PageSocket): uvicorn's own close waits for bytes the page never takes, holding the
    connection for as long as the page stays frozen. The program then holds no connection to it,
    its handler has ended, and the stop is not held. Induced test conditions: the program's socket
    buffers no bytes in the kernel (SO_SNDBUF 0) and each beat carries a 15 KB pad, so the page's
    window fills at once and a write it does not take stays pending in the program, short of the
    buffer that pauses writing (64 KiB); and the keepalive ping every 0.5 s, answered within
    0.5 s (production: uvicorn's 20 s and 20 s).
    """
    feed = _Feed()

    def padded(now: float) -> dict:
        return {**feed(now), "pad": "x" * 15_000}

    async def go():
        stop, stats = asyncio.Event(), {}
        sock, _ = listener()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        port = sock.getsockname()[1]
        served = asyncio.create_task(
            serve_page_socket(
                stop,
                sock,
                {"heartbeat_fn": padded, "stats": stats, "clock": feed.clock},
                ws_ping_interval=0.5,
                ws_ping_timeout=0.5,
            )
        )
        page = _page_that_never_reads(port)
        try:
            end = time_et.elapsed() + 5
            while stats.get("clients") != 1 and time_et.elapsed() < end:
                await asyncio.sleep(0.01)
            assert stats["clients"] == 1 and _held_by_this_program(port, page)
            end = time_et.elapsed() + 5  # a ping, its timeout and a beat's margin
            # the handler ends on the loop's next turns after the connection (connection_lost)
            while (stats["clients"] or _held_by_this_program(port, page)) and (
                time_et.elapsed() < end
            ):
                await asyncio.sleep(0.05)
            assert not _held_by_this_program(port, page), "the frozen page's connection is held"
            assert stats["clients"] == 0
            t0 = time_et.elapsed()
            stop.set()
            await asyncio.wait_for(served, 5)
            return time_et.elapsed() - t0
        finally:
            page.close()

    took = asyncio.run(asyncio.wait_for(go(), 30))
    assert took < 2, f"the stop took {took:.1f} s"
    dropped = [r.getMessage() for r in caplog.records if "stopped reading" in r.getMessage()]
    assert dropped == [
        "live ui: a page stopped reading (the keepalive ping unanswered); dropping it"
    ], dropped
