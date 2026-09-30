"""Daemon -> console live push, end to end, with no database in the live path.

The REAL daemon-side server (app.market_data.schwab.streaming.live_push.serve_live_push,
fed by a real stream_spine.MessageBus) and the REAL console-side client
(app.options.order_flow.streaming._feed_loop) talk over a real local WebSocket. These tests
prove the seam the 2026-09-23 transport change created:

  * a Schwab message published on the daemon's bus reaches the console's state with its OWN
    receive time (never the time the console processed it);
  * an equity quote is not forwarded: the console reads it as the daemon's price row;
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
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    monkeypatch.setattr(lmp, "_by_ticker", {})
    yield port
    ofs._feed_running = False
    ofs._active_ticker = None


def _opt_quote(gamma: float, ts: float, src: str = "schwab_options_l1") -> dict:
    """Stand-in (named): one LEVELONE_OPTIONS message for _CONTRACT carrying GAMMA."""
    return options_quote_msg(symbol=_CONTRACT, content={"key": _CONTRACT, "GAMMA": gamma},
                             src=src, ts_recv=ts)


_TOPIC = f"optquote.{_CONTRACT}"


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
    """The console applied the contract's quote that the daemon received at `ts`: its gamma is
    in the console's state with that receive time."""
    return lambda: (ofls.get_stream_greeks(_CONTRACT) or {}).get("gamma_ts_recv") == ts


def test_a_schwab_message_reaches_the_console_with_its_own_receive_time(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time() - 0.5          # received by the daemon half a second ago
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
        assert await _until(_received(ts)), "freshness must judge the daemon's receive time"
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES"))
    asyncio.run(_run(feed, body))


def test_an_equity_quote_is_not_forwarded_to_the_console(feed):
    """ONE-02: the console held a second copy of every equity quote (its order-flow tape). The
    equity quote is the daemon's price row; the message itself stays in the daemon."""
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=501.0, ask=501.02, last=501.01,
                                           src="schwab_l1", ts_recv=time.time(),
                                           native={"key": "SPY", "LAST_PRICE": 501.01}))
        ts = time.time()
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
        assert await _until(_received(ts))
        assert stats["sent"] == 1
        assert ofls.get_stream_greeks("SPY") is None and lmp.get_quote("SPY") is None
    asyncio.run(_run(feed, body))


def test_the_daemon_heartbeat_decides_liveness_end_to_end(feed):
    """Real push server -> real console feed loop. Live only while heartbeats arrive, the
    Schwab socket is open and the daemon holds the symbol; the feed is down the moment the
    push connection ends."""
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
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
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)                            # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES")
    asyncio.run(_run(feed, body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish(_TOPIC, _opt_quote(0.99, time.time(), src="not_schwab"))
        ts = time.time()
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
        assert await _until(_received(ts))
        assert stats["sent"] == 1
        assert ofls.get_stream_greeks(_CONTRACT)["gamma"] == 0.05
    asyncio.run(_run(feed, body))


def test_a_connecting_console_receives_the_last_values_first(feed):
    ts = time.time()

    async def body(bus, stats):
        assert await _until(_received(ts))
    bus_holder = {}

    async def run():
        bus = MessageBus()
        bus.publish(_TOPIC, _opt_quote(0.05, ts))   # before any client
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
        bus.publish(_TOPIC, _opt_quote(0.05, ts))
        assert await _until(_received(ts))
    asyncio.run(_run(feed, body))


def test_push_down_serves_nothing_and_the_feed_recovers_when_it_returns(feed):
    async def run():
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        await asyncio.sleep(0.3)                    # no server: several failed connects
        assert ofls.get_stream_greeks(_CONTRACT) is None
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        try:
            assert await _until(lambda: stats.get("clients") == 1)
            ts = time.time()
            bus.publish(_TOPIC, _opt_quote(0.05, ts))
            assert await _until(_received(ts))
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_a_message_missing_its_receive_time_is_dropped_whole(monkeypatch):
    ofs._ingest_pushed("optquote.ZZZNOTS", {"symbol": "ZZZNOTS", "content": {"GAMMA": 1.0}})
    msg = _opt_quote(1.0, time.time())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("optquote.ZZZNOPE", msg)
    assert ofls.get_stream_greeks("ZZZNOTS") is None and ofls.get_stream_greeks("ZZZNOPE") is None


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


def test_a_late_console_gets_every_message_with_the_time_it_really_arrived(feed):
    """Schwab LEVELONE sends only changed fields. A console connecting after a greeks message
    and a later bid/ask tick still gets both messages -- each with the receive time the daemon
    gave it -- not just the last (bid/ask-only) one."""
    async def run():
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=feed, stats=stats))
        assert await _until(lambda: stats.get("listening"))
        # the daemon publishes greeks, then a bid/ask-only tick -- before any console exists
        t_greeks = time.time() - 5.0
        t_quote = time.time() - 1.0
        bus.publish(_TOPIC, _opt_quote(0.05, t_greeks))
        bus.publish(_TOPIC, options_quote_msg(
            symbol=_CONTRACT, content={"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3},
            src="schwab_options_l1", ts_recv=t_quote))
        await asyncio.sleep(0.05)
        ofs._feed_running = True
        client = asyncio.create_task(ofs._feed_loop())
        try:
            assert await _until(_received(t_greeks))   # the greeks, not only the later bid/ask tick
            assert await _until(lambda: ofls.option_top(_CONTRACT) == {"bid": 1.2, "ask": 1.3})
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())


def test_field_history_keeps_only_the_latest_carrier_of_each_field():
    h = live_push.FieldHistory()
    def q(ts, content):
        return options_quote_msg(symbol="X", content=content, src="schwab_options_l1", ts_recv=ts)
    for m in (q(1.0, {"LAST_PRICE": 1, "CLOSE_PRICE": 9}), q(2.0, {"LAST_PRICE": 2}), q(3.0, {"BID_PRICE": 1.5})):
        h.record("optquote.X", m)
    assert [m["ts_recv"] for _t, m in h.replay()] == [1.0, 2.0, 3.0]  # m1 still carries CLOSE_PRICE
    h.record("optquote.X", q(4.0, {"CLOSE_PRICE": 9, "BID_PRICE": 1.6}))
    assert [m["ts_recv"] for _t, m in h.replay()] == [2.0, 4.0]       # m1 and m3 superseded
