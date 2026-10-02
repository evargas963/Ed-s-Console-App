"""Daemon -> console live push, end to end, with no database in the live path.

The REAL daemon-side server (app.market_data.schwab.streaming.live_push.serve_live_push,
fed by a real stream_spine.MessageBus) and the REAL console-side client
(app.options.order_flow.streaming._feed_loop) talk over a real local WebSocket. These tests
prove the seam the 2026-09-23 transport change created:

  * a Schwab message published on the daemon's bus reaches the console's live-price plane
    with its OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are forwarded (any other src on the same topic is not);
  * a connecting console first receives the bus's current records, then each that changes;
  * the live loop never opens the capture database;
  * with the push server down nothing is served, and the feed picks up when it returns.
"""
from __future__ import annotations

import asyncio
import socket
import sqlite3
import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.market_data.schwab.streaming import live_push
from stream_spine import MessageBus, book_msg, options_quote_msg, quote_msg

_CONTRACT = "SPY   260918C00500000"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def feed(monkeypatch):
    port = _free_port()
    monkeypatch.setattr(ofs, "LIVE_PUSH_URL", f"ws://127.0.0.1:{port}")
    monkeypatch.setattr(ofs, "PUSH_RECONNECT_SEC", 0.05)
    ofs._feed_running = False
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    monkeypatch.setattr(lmp, "_by_ticker", {})
    yield port
    ofs._feed_running = False


def _spy_trade(last: float, ts: float) -> dict:
    native = {"key": "SPY", "BID_PRICE": last - 0.01, "ASK_PRICE": last + 0.01,
              "LAST_PRICE": last, "QUOTE_TIME_MILLIS": int(ts * 1000)}
    return quote_msg(symbol="SPY", bid=last - 0.01, ask=last + 0.01, last=last,
                     src="schwab_l1", ts_recv=ts, native=native)


async def _until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def _daemon_heartbeat(socket_open=True, held=("SPY",)):
    """What capture.py's heartbeat reports for a session holding `held` on LEVELONE_EQUITIES."""
    return lambda: {"ts": time.time(), "schwab_socket_open": socket_open,
                    "held": {"LEVELONE_EQUITIES": list(held)}, "health": {}}


async def _run(port, body, heartbeat_fn=None):
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    server = asyncio.create_task(live_push.serve_live_push(
        bus, stop, port=port, stats=stats,
        heartbeat_fn=heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat()))
    assert await _until(lambda: stats.get("listening"))
    ofs._feed_running = True
    client = asyncio.create_task(ofs._feed_loop())
    try:
        await body(bus, stats)
    finally:
        ofs._feed_running = False
        client.cancel()
        stop.set()
        await asyncio.gather(client, server, return_exceptions=True)


def _received(ts):
    """The console applied SPY's trade that the daemon received at `ts`: it is on SPY's tape
    with that receive time."""
    return lambda: any(r.get("server_received_ts") == ts for r in ofls.get_content_for_symbol("SPY"))


def test_a_schwab_trade_reaches_the_console_with_its_own_receive_time(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time() - 0.5          # received by the daemon half a second ago
        bus.publish("quote.SPY", _spy_trade(501.25, ts))
        assert await _until(_received(ts)), "freshness must judge the daemon's receive time"
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES"))
        assert lmp.get_quote("SPY") is None      # the console keeps no price of its own
    asyncio.run(_run(feed, body))


def test_the_daemon_heartbeat_decides_liveness_end_to_end(feed):
    """Real push server -> real console feed loop. Live only while heartbeats arrive, the
    Schwab socket is open and the daemon holds the symbol; the feed is down the moment the
    push connection ends."""
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES"))
        assert not lmp.feed_live_for("QQQ", "LEVELONE_EQUITIES")   # not held by the daemon
        assert not lmp.feed_live_for("SPY", "NYSE_BOOK")           # held on another service only
        assert lmp.daemon_status() is not None
    asyncio.run(_run(feed, body))
    assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES")       # push ended -> feed down
    assert lmp.daemon_status() is None


def test_a_closed_schwab_socket_is_not_live(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)                            # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES")
    asyncio.run(_run(feed, body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded(feed):
    """Neither the message nor any value it carried: the SPY record a client receives holds
    only what Schwab sent (here, no CLOSE_PRICE -- only the non-Schwab message carried one)."""
    import json as _json

    from websockets.asyncio.client import connect

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05,
                                           src="not_schwab", ts_recv=time.time(),
                                           native={"LAST_PRICE": 1.05, "CLOSE_PRICE": 1.0}))
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(502.0, ts))
        assert await _until(_received(ts))
        assert stats["sent"] == 1
        async with connect(f"ws://127.0.0.1:{feed}", max_size=None) as ws:   # a second client
            while (m := _json.loads(await asyncio.wait_for(ws.recv(), 5)))["topic"] != "quote.SPY":
                pass
        assert "CLOSE_PRICE" not in m["msg"]["native"], "a non-Schwab value was forwarded as Schwab's"
    asyncio.run(_run(feed, body))


def test_a_connecting_console_receives_the_last_values_first(feed):
    ts = time.time()

    async def body(bus, stats):
        assert await _until(_received(ts))
    bus_holder = {}

    async def run():
        bus = MessageBus()
        bus.publish("quote.SPY", _spy_trade(499.5, ts))   # before any client
        bus_holder["bus"] = bus
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        assert await _until(lambda: stats.get("listening"))
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        try:
            await body(bus, stats)
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_a_consoles_wanted_list_is_withdrawn_when_its_connection_ends(feed):
    """What the console's screens show is the console's now: when its connection ends, the
    daemon holds no list from it (no books, contracts or chain asked for with no console to show
    them)."""
    import json as _json

    from websockets.asyncio.client import connect
    said: list = []

    async def run():
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(MessageBus(), stop, port=feed, stats=stats,
                                                               on_wanted=lambda raw, _ws: said.append(raw)))
        assert await _until(lambda: stats.get("listening"))
        async with connect(f"ws://127.0.0.1:{feed}") as ws:
            await ws.send(_json.dumps({"op": "wanted", "wanted": {"active": "SPY", "NYSE_BOOK": ["SPY"]}}))
            assert await _until(lambda: said)
        assert await _until(lambda: len(said) == 2)
        stop.set()
        await asyncio.gather(server, return_exceptions=True)
    asyncio.run(run())
    assert said == [{"active": "SPY", "NYSE_BOOK": ["SPY"]}, None]


def test_option_l1_and_book_update_the_contract_and_report_greeks(feed, monkeypatch):
    seen: list = []
    monkeypatch.setattr(ofs, "_on_tick_callback", seen.append)

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish(f"optquote.{_CONTRACT}", options_quote_msg(
            symbol=_CONTRACT, content={"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3,
                                       "GAMMA": 0.05}, src="schwab_options_l1", ts_recv=ts))
        bus.publish(f"book.{_CONTRACT}", book_msg(
            symbol=_CONTRACT, service="OPTIONS_BOOK", src="schwab_book", ts_recv=ts,
            content={"key": _CONTRACT, "BIDS": [], "ASKS": []}))
        assert await _until(lambda: seen == [_CONTRACT])
        assert ofs._option_contract_last_update_ts[_CONTRACT] == ts
        assert ofls.option_top(_CONTRACT) == {"bid": 1.2, "ask": 1.3}
    asyncio.run(_run(feed, body))


def test_the_live_loop_never_opens_the_capture_database(feed, monkeypatch):
    def _no_db(*_a, **_k):
        raise AssertionError("the live feed must not read stream_capture.db")
    monkeypatch.setattr(sqlite3, "connect", _no_db)

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(503.0, ts))
        assert await _until(_received(ts))
    asyncio.run(_run(feed, body))


def test_push_down_serves_nothing_and_the_feed_recovers_when_it_returns(feed):
    async def run():
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        await asyncio.sleep(0.3)                    # no server: several failed connects
        assert ofls.get_content_for_symbol("SPY") == []
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        try:
            assert await _until(lambda: stats.get("clients") == 1)
            ts = time.time()
            bus.publish("quote.SPY", _spy_trade(504.0, ts))
            assert await _until(_received(ts))
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_a_message_missing_its_receive_time_is_dropped_whole(monkeypatch):
    ofs._ingest_pushed("quote.ZZZNOTS", {"symbol": "ZZZNOTS", "native": {"LAST_PRICE": 1.0}})
    msg = _spy_trade(1.0, time.time())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("quote.ZZZNOPE", msg)
    assert ofls.get_content_for_symbol("ZZZNOTS") == [] and ofls.get_content_for_symbol("ZZZNOPE") == []


def test_daemon_shutdown_is_not_held_up_by_a_connected_console(feed):
    """A handler blocked waiting for the next bus message must not keep the server open:
    before the fix, stopping the daemon with a console attached hung forever."""
    async def run():
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        assert await _until(lambda: stats.get("listening"))
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        try:
            assert await _until(lambda: stats["clients"] == 1)
            stop.set()                                  # console still connected
            await asyncio.wait_for(asyncio.shield(server), timeout=3.0)
            assert stats["clients"] == 0
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_a_late_console_gets_the_current_record_with_each_fields_own_time(feed):
    """Schwab LEVELONE sends only changed fields. A console connecting after a trade and a
    later bid/ask tick gets the current record (docs/DATA_FLOW.md §2 D3): the trade's fields
    and the bid/ask together, each stamped with the receive time the daemon gave the message
    that carried it -- the trade is not lost behind the later bid/ask-only tick, nor re-dated
    to it."""
    async def run():
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        assert await _until(lambda: stats.get("listening"))
        # the daemon publishes a trade, then a bid/ask-only tick -- before any console exists
        t_trade = time.time() - 5.0
        t_quote = time.time() - 1.0
        bus.publish("quote.SPY", quote_msg(symbol="SPY", src="schwab_l1", ts_recv=t_trade,
                                           native={"key": "SPY", "LAST_PRICE": 505.0,
                                                   "CLOSE_PRICE": 500.0}))
        bus.publish("quote.SPY", quote_msg(symbol="SPY", src="schwab_l1", ts_recv=t_quote,
                                           native={"key": "SPY", "BID_PRICE": 504.9,
                                                   "ASK_PRICE": 505.1}))
        await asyncio.sleep(0.05)
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        try:
            assert await _until(_received(t_trade))    # the trade, at its own receive time
            assert not _received(t_quote)(), "the trade was re-dated to the later bid/ask tick"
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())
