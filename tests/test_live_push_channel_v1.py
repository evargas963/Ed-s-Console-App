"""Daemon -> console live push, end to end, with no database in the live path.

The REAL daemon-side server (app.market_data.schwab.streaming.live_push.serve_live_push,
fed by a real stream_spine.MessageBus) and the REAL console-side client
(app.options.order_flow.streaming._feed_loop) talk over a real local WebSocket. These tests
prove the seam the 2026-09-23 transport change created:

  * a Schwab message published on the daemon's bus reaches the console's live-price plane
    with its OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are forwarded (any other src on the same topic is not);
  * a connecting console first receives the bus's last values, then live messages;
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
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = None
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    monkeypatch.setattr(lmp, "_by_ticker", {})
    yield port
    ofs._feed_running = False
    ofs._active_ticker = None


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


async def _run(port, body):
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
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


def test_a_schwab_trade_reaches_the_plane_with_its_own_receive_time(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time() - 0.5          # received by the daemon half a second ago
        bus.publish("quote.SPY", _spy_trade(501.25, ts))
        assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 501.25)
        row = lmp.get_quote("SPY")
        assert row["server_received_ts"] == ts, "freshness must judge the daemon's receive time"
        assert row["spot_received_ts"] == ts
        assert ofs._streaming_last_update_ts == ts
        assert lmp.spot_is_fresh(row)
    asyncio.run(_run(feed, body))


def test_a_quote_only_tick_does_not_refresh_the_last_trade_age(feed):
    """Schwab resends only changed fields: a bid/ask tick keeps LAST_PRICE, but the price's
    age stays the age of the trade that set it -- a stale trade is never made to look new."""
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        t_trade = time.time() - 40.0     # older than PLANE_QUOTE_STALE_SEC (30s)
        bus.publish("quote.SPY", _spy_trade(500.0, t_trade))
        assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 500.0)
        t_quote = time.time()
        bus.publish("quote.SPY", quote_msg(
            symbol="SPY", bid=500.1, ask=500.2, src="schwab_l1", ts_recv=t_quote,
            native={"key": "SPY", "BID_PRICE": 500.1, "ASK_PRICE": 500.2}))
        assert await _until(lambda: lmp.get_quote("SPY").get("server_received_ts") == t_quote)
        row = lmp.get_quote("SPY")
        assert row["spot"] == 500.0 and row["spot_received_ts"] == t_trade
        assert lmp.quote_is_fresh(row) and not lmp.spot_is_fresh(row)
    asyncio.run(_run(feed, body))


def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05,
                                           src="not_schwab", ts_recv=time.time(),
                                           native={"LAST_PRICE": 1.05}))
        bus.publish("quote.SPY", _spy_trade(502.0, time.time()))
        assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 502.0)
        assert stats["sent"] == 1
    asyncio.run(_run(feed, body))


def test_a_connecting_console_receives_the_last_values_first(feed):
    async def body(bus, stats):
        assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 499.5)
    bus_holder = {}

    async def run():
        bus = MessageBus()
        bus.publish("quote.SPY", _spy_trade(499.5, time.time()))   # before any client
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


def test_option_l1_and_book_update_the_contract_and_report_greeks(feed, monkeypatch):
    seen: list = []
    monkeypatch.setattr(ofs, "_streamed_greeks_hook", lambda sym, ts: seen.append((sym, ts)))

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish(f"optquote.{_CONTRACT}", options_quote_msg(
            symbol=_CONTRACT, content={"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3,
                                       "GAMMA": 0.05}, src="schwab_options_l1", ts_recv=ts))
        bus.publish(f"book.{_CONTRACT}", book_msg(
            symbol=_CONTRACT, service="OPTIONS_BOOK", src="schwab_book", ts_recv=ts,
            content={"key": _CONTRACT, "BIDS": [], "ASKS": []}))
        assert await _until(lambda: seen == [(_CONTRACT, ts)])
        assert ofs._option_contract_last_update_ts[_CONTRACT] == ts
        assert ofls.get_content_for_symbol(_CONTRACT)
    asyncio.run(_run(feed, body))


def test_the_live_loop_never_opens_the_capture_database(feed, monkeypatch):
    def _no_db(*_a, **_k):
        raise AssertionError("the live feed must not read stream_capture.db")
    monkeypatch.setattr(sqlite3, "connect", _no_db)

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish("quote.SPY", _spy_trade(503.0, time.time()))
        assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 503.0)
    asyncio.run(_run(feed, body))


def test_push_down_serves_nothing_and_the_feed_recovers_when_it_returns(feed):
    async def run():
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        await asyncio.sleep(0.3)                    # no server: several failed connects
        assert lmp.get_quote("SPY") is None
        assert ofs._push_connected_ts is None
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        try:
            assert await _until(lambda: stats.get("clients") == 1)
            bus.publish("quote.SPY", _spy_trade(504.0, time.time()))
            assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("spot") == 504.0)
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_a_message_missing_its_receive_time_is_dropped_whole(monkeypatch):
    monkeypatch.setattr(lmp, "_by_ticker", {})
    assert ofs._ingest_pushed("quote.SPY", {"symbol": "SPY", "native": {"LAST_PRICE": 1.0}}) is None
    assert lmp.get_quote("ZZZNOPE") is None
    msg = _spy_trade(1.0, time.time())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("quote.ZZZNOPE", msg)
    assert lmp.get_quote("ZZZNOPE") is None


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


def test_a_late_console_gets_every_field_with_the_time_it_really_arrived(feed):
    """Schwab LEVELONE sends only changed fields. A console connecting after a trade and a
    later bid/ask tick must still get LAST_PRICE and CLOSE_PRICE -- each with the receive
    time of the message that carried it -- not just the last (bid/ask-only) message."""
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
            assert await _until(lambda: (lmp.get_quote("SPY") or {}).get("bid") == 504.9)
            row = lmp.get_quote("SPY")
            assert row["spot"] == 505.0 and row["spot_received_ts"] == t_trade
            assert row["prior_close"] == 500.0
            assert row["server_received_ts"] == t_quote
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_field_history_keeps_only_the_latest_carrier_of_each_field():
    h = live_push.FieldHistory()
    m1 = quote_msg(symbol="X", src="schwab_l1", ts_recv=1.0, native={"LAST_PRICE": 1, "CLOSE_PRICE": 9})
    m2 = quote_msg(symbol="X", src="schwab_l1", ts_recv=2.0, native={"LAST_PRICE": 2})
    m3 = quote_msg(symbol="X", src="schwab_l1", ts_recv=3.0, native={"BID_PRICE": 1.5})
    for m in (m1, m2, m3):
        h.record("quote.X", m)
    assert [m["ts_recv"] for _t, m in h.replay()] == [1.0, 2.0, 3.0]  # m1 still carries CLOSE_PRICE
    h.record("quote.X", quote_msg(symbol="X", src="schwab_l1", ts_recv=4.0,
                                  native={"CLOSE_PRICE": 9, "BID_PRICE": 1.6}))
    assert [m["ts_recv"] for _t, m in h.replay()] == [2.0, 4.0]       # m1 and m3 superseded
