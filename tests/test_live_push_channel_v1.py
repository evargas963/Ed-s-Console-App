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
import sys
import threading
import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.market_data.schwab.streaming import live_push, live_ui
from app.options.order_flow import history
from stream_spine import MessageBus, book_msg, quote_msg

_CONTRACT = "SPY   260918C00500000"


#: ports this test holds bound and not listening (every connect refused, no other process can
#: take them); closed by the `feed` fixture
_HELD: list = []


def _held_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _HELD.append(s)
    return s.getsockname()[1]


@pytest.fixture
def feed():
    """The console's state cleared before and after."""
    ofs._feed_running = False
    ofls.clear_all_live_state()
    lmp._by_ticker.clear()
    yield
    ofs._feed_running = False
    lmp._by_ticker.clear()
    while _HELD:
        _HELD.pop().close()


def _port(stats: dict) -> int:
    """The port a daemon server took (it was asked for port 0: the system's free pick)."""
    return int(stats["listening"].rsplit(":", 1)[1])


def _console(push_port: int, ui_port: "int | None" = None):
    """The console's real feed loop on the daemon's live push at `push_port` and its price rows
    at `ui_port` (none given: a port this test holds, nothing listening), retried every 0.05 s."""
    return ofs._feed_loop(f"ws://127.0.0.1:{push_port}",
                          f"ws://127.0.0.1:{_held_port() if ui_port is None else ui_port}", 0.05)


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
                    "held": {"LEVELONE_EQUITIES": list(held)}, "health": {},
                    "options": {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []}}


async def _run(body, heartbeat_fn=None):
    """The daemon's two servers on one bus -- the message push and the price-row push, which
    beats the daemon's status -- and the console's real feed loop connected to both: what the
    console knows of the daemon arrives over the wire or not at all."""
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    ui_stats: dict = {}
    server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=0, stats=stats))
    ui = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat(),
        host="127.0.0.1", port=0, stats=ui_stats))
    assert await _until(lambda: stats.get("listening") and ui_stats.get("listening"))
    ofs._feed_running = True
    client = asyncio.create_task(_console(_port(stats), _port(ui_stats)))
    try:
        await body(bus, stats)
    finally:
        ofs._feed_running = False
        client.cancel()
        stop.set()
        await asyncio.gather(client, server, ui, return_exceptions=True)


def _received(ts):
    """The console applied SPY's trade that the daemon received at `ts`: it is on SPY's tape
    with that receive time."""
    return lambda: any(p["ts_recv"] == ts for p in history.TAPE.prints("SPY"))




def test_the_daemon_heartbeat_decides_liveness_end_to_end(feed):
    """Real daemon servers -> real console feed loop. Live only while the daemon's status beats
    arrive, the Schwab socket is open and the daemon holds the symbol; the feed is down the
    moment the daemon's connections end."""
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time()))
        now = time.time()
        assert not lmp.feed_live_for("QQQ", "LEVELONE_EQUITIES", now)   # not held by the daemon
        assert not lmp.feed_live_for("SPY", "NYSE_BOOK", now)           # held on another service only
        assert lmp.daemon_status(now) is not None
    asyncio.run(_run(body))
    now = time.time()
    assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", now)       # push ended -> feed down
    assert lmp.daemon_status(now) is None


def test_a_live_feed_stays_live_while_the_console_works_through_a_backlog_of_chains(feed):
    """Measured 2026-10-02 after the close: the console spent 79% of its event loop decoding
    chain parts and read 25 of 60 one-second samples of DELL as "feed down" on a healthy feed,
    the daemon's status waiting behind the chains. 300 chains arrive at once and each takes the
    console 20 ms to apply on its event loop (a named stand-in for pricing it: the console's chain
    callback, as start_order_flow_stream sets it, sleeps); the feed, live and holding SPY, reads
    live at every sample a route thread takes while it works through them."""
    import json as _json
    import threading

    import option_ledger
    from calibration.complete_chain_capture import chain_round_message
    from pathlib import Path
    contracts = _json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json")
                            .read_text(encoding="utf-8"))["chain"][:1]
    samples: list = []

    def sample(seconds):                   # a route, on its own thread, as the console serves them
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            samples.append(lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time()))
            time.sleep(0.05)

    async def body(bus, stats):
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time()))
        for i in range(300):                     # each round: its contract's record opened, then in
            ct = {**contracts[0], "symbol": f"ZZ{i:03d}  {contracts[0]['symbol'][6:]}"}
            bus.publish(*option_ledger.posting(ct["symbol"], option_ledger.opening(ct, f"ZZ{i:03d}"),
                                               ct.get("quoteTimeInLong")))
            bus.publish(*chain_round_message(f"ZZ{i:03d}", time.time()))
        sampler = threading.Thread(target=sample, args=(7.0,))
        sampler.start()
        while sampler.is_alive():
            await asyncio.sleep(0.05)
    ofs._on_chain_callback = lambda *_chain: time.sleep(0.02)
    try:
        asyncio.run(_run(body))
    finally:
        ofs._on_chain_callback = None
    assert samples and all(samples), f"read down in {samples.count(False)} of {len(samples)} samples"


def test_a_closed_schwab_socket_is_not_live(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)                            # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time())
    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


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
        async with connect(f"ws://127.0.0.1:{_port(stats)}", max_size=None) as ws:   # a second client
            while (m := _json.loads(await asyncio.wait_for(ws.recv(), 5)))["topic"] != "quote.SPY":
                pass
        assert "CLOSE_PRICE" not in m["msg"]["native"], "a non-Schwab value was forwarded as Schwab's"
    asyncio.run(_run(body))




def test_option_l1_and_book_update_the_contract_and_report_greeks(feed):
    """The console's tick callback, as start_order_flow_stream sets it, records each tick: a
    LEVELONE_OPTIONS message posted to the contract's record (as the daemon's handler posts it)
    reaches the console's mirror, with the message's own receive time; the book does not tick."""
    import option_ledger
    seen: list = []

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish(*option_ledger.posting(_CONTRACT, option_ledger.from_stream(
            {"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3, "GAMMA": 0.05}, int(ts * 1000)),
            int(ts * 1000), ts))
        bus.publish(f"book.{_CONTRACT}", book_msg(
            symbol=_CONTRACT, service="OPTIONS_BOOK", src="schwab_book", ts_recv=ts,
            content={"key": _CONTRACT, "BIDS": [], "ASKS": []}))
        assert await _until(lambda: _CONTRACT in seen)       # (SPY's price row ticks too)
        assert seen.count(_CONTRACT) == 1
        assert ofls.contract(_CONTRACT).times["bid"][1] == ts
        assert ofls.option_top(_CONTRACT) == {"bid": 1.2, "ask": 1.3}
    ofs._on_tick_callback = seen.append
    try:
        asyncio.run(_run(body))
    finally:
        ofs._on_tick_callback = None


#: every sqlite3.connect this process makes while _AUDITING is set, as Python's audit hook reports it
_OPENED: list = []
_AUDITING = threading.Event()
sys.addaudithook(lambda event, args: _OPENED.append(args) if event == "sqlite3.connect" and _AUDITING.is_set() else None)


def test_the_live_loop_never_opens_the_capture_database(feed):
    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(503.0, ts))
        assert await _until(_received(ts))
    _OPENED.clear()
    _AUDITING.set()
    try:
        asyncio.run(_run(body))
    finally:
        _AUDITING.clear()
    assert _OPENED == [], f"the live feed opened a database: {_OPENED}"


def test_push_down_serves_nothing_and_the_feed_recovers_when_it_returns(feed):
    """The daemon's push port is held by this test (bound, not listening: every connect is
    refused, and no other process can take it) until the daemon's server starts on it."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    port = held.getsockname()[1]

    async def run():
        ofs._feed_running = True
        client = asyncio.create_task(_console(port))
        await asyncio.sleep(0.3)                    # no server: several failed connects
        assert ofls.get_content_for_symbol("SPY") == [] and history.TAPE.prints("SPY") == []
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        held.close()
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
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


def test_a_message_missing_its_receive_time_is_dropped_whole():
    ofs._ingest_pushed("quote.ZZZNOTS", {"symbol": "ZZZNOTS", "native": {"LAST_PRICE": 1.0}})
    msg = _spy_trade(1.0, time.time())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("quote.ZZZNOPE", msg)
    assert ofls.get_content_for_symbol("ZZZNOTS") == [] and ofls.get_content_for_symbol("ZZZNOPE") == []
    assert history.TAPE.prints("ZZZNOTS") == [] and history.TAPE.prints("ZZZNOPE") == []


def test_daemon_shutdown_is_not_held_up_by_a_connected_console(feed):
    """A handler blocked waiting for the next bus message must not keep the server open:
    before the fix, stopping the daemon with a console attached hung forever."""
    async def run():
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=0, stats=stats))
        assert await _until(lambda: stats.get("listening"))
        ofs._feed_running = True
        client = asyncio.create_task(_console(_port(stats)))
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
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=0, stats=stats))
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
        client = asyncio.create_task(_console(_port(stats)))
        try:
            assert await _until(_received(t_trade))    # the trade, at its own receive time
            assert not _received(t_quote)(), "the trade was re-dated to the later bid/ask tick"
        finally:
            ofs._feed_running = False
            client.cancel()
            stop.set()
            await asyncio.gather(client, server, return_exceptions=True)
    asyncio.run(run())
