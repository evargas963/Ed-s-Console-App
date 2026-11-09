"""Daemon -> console in one program, end to end, with no database in the live path.

The REAL daemon (capture.Daemon on a real stream_spine.MessageBus, its market follower, its
browser price socket live_ui.serve_live_ui, whose beat records the daemon's status, and the
program's web server with its control route, /control, streaming.control_socket) and the REAL
console feed (app.options.order_flow.streaming.start_order_flow_stream: _bus_loop reading the
daemon's bus, bound with bind_daemon) run on one event loop, as capture.run runs them. These tests
prove:

  * a Schwab message published on the daemon's bus reaches the console's live planes with its
    OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are applied or forwarded (any other src on the same topic is
    not);
  * a console that starts late first takes the bus's current records, then each that changes;
  * the live loop never opens the capture database;
  * with no daemon in the program nothing is served, and the feed starts once one is bound;
  * the program's control route does not hold its stop behind a connected client, takes a stop
    while it serves, logs a frame it cannot read with what arrived, and refuses a browser,
    another machine and a program with no daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import launch
import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture, live_push, live_ui
from calibration.complete_chain_capture import chain_messages
from stream_spine import (
    LATEST,
    HealthRegistry,
    MessageBus,
    book_msg,
    quote_msg,
    verbatim_msg,
)
from tests.feed_live_helper import RTH_INSTANT, clock_from

_CONTRACT = "SPY   260918C00500000"


def _spy_trade(last: float, ts: float) -> dict:
    native = {
        "key": "SPY",
        "BID_PRICE": last - 0.01,
        "ASK_PRICE": last + 0.01,
        "LAST_PRICE": last,
        "QUOTE_TIME_MILLIS": int(ts * 1000),
    }
    return quote_msg(
        symbol="SPY",
        bid=last - 0.01,
        ask=last + 0.01,
        last=last,
        src="schwab_l1",
        ts_recv=ts,
        native=native,
    )


async def _until(pred, timeout=5.0):
    end = time_et.elapsed() + timeout
    while time_et.elapsed() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def listener() -> tuple[socket.socket, str]:
    """Open a listening socket of the test's own and return it with its address.

    Its port is the system's pick as it binds, as capture.open_sockets opens the program's.
    """
    sock = socket.create_server(("127.0.0.1", 0))
    return sock, f"ws://127.0.0.1:{sock.getsockname()[1]}"


def program_web(**settings) -> capture._PagesServer:
    """The program's web server (capture._PagesServer with capture.PAGES, `settings` over them)
    with the console's startup work not run (lifespan off): its sockets, /ws and /control, alone.
    """
    return capture._PagesServer(
        uvicorn.Config(server.app, **{**capture.PAGES, "lifespan": "off", **settings})
    )


async def serve_page_socket(stop: asyncio.Event, sock: socket.socket, prices: dict, **settings):
    """The page's price socket as the program serves it, until `stop`: the daemon's side
    (live_ui.serve_live_ui, `prices` its arguments) and /ws on the program's web server
    (program_web, `settings`) on `sock`.
    """
    web = program_web(**settings)
    serving = asyncio.create_task(web.serve(sockets=[sock]))
    try:
        await live_ui.serve_live_ui(stop, state=server.app.state, **prices)
    finally:
        web.should_exit = True
        await serving


def _daemon_heartbeat(socket_open=True, held=("SPY",), clock=time_et.now):
    """What capture.py's heartbeat reports for a session holding `held` on LEVELONE_EQUITIES, each
    beat stamped by `clock`.
    """
    return lambda _now: {
        "ts": clock(),
        "schwab_socket_open": socket_open,
        "held": {"LEVELONE_EQUITIES": list(held)},
        "health": {},
    }


@contextlib.asynccontextmanager
async def program_routes(daemon):
    """The program's web server (program_web) serving on a socket of the test's own, with
    `daemon` its app's state `daemon` as capture.serve_console sets it (None: no daemon). Yields
    the server and its port; the server ends on exit, as serve_console ends it on the program's
    stop.
    """
    sock, _url = listener()
    web = program_web()
    server.app.state.daemon = daemon
    serving = asyncio.create_task(web.serve(sockets=[sock]))
    try:
        assert await _until(lambda: web.started)  # serving
        yield web, sock.getsockname()[1]
    finally:
        web.should_exit = True
        await serving
        server.app.state.daemon = None


async def _run(body, heartbeat_fn=None, on_tick=None, on_chain=None):
    """The daemon on one bus, as capture.run runs it -- the program's web server with its control
    route, its browser price socket, whose beat records the daemon's status (the one program's
    one plane), and its market follower feeding the plane -- with the console's real feed started
    on the same loop, bound to that daemon (start_order_flow_stream, with the tick and chain
    callbacks the console passes it). `body` takes the bus and the web server.
    """
    bus = MessageBus()
    stop = asyncio.Event()
    ui_stats: dict = {}
    daemon = capture.Daemon(bus, HealthRegistry(), [])
    ofs.bind_daemon(daemon)  # as capture.serve_console binds it
    async with program_routes(daemon) as (web, _port):
        ui = asyncio.create_task(
            live_ui.serve_live_ui(
                stop,
                state=server.app.state,
                heartbeat_fn=heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat(),
                stats=ui_stats,
            )
        )
        follower = asyncio.create_task(daemon.follow_market(stop))
        assert await _until(lambda: "clients" in ui_stats)  # both serving
        assert ofs.start_order_flow_stream(on_tick_callback=on_tick, on_chain_callback=on_chain)
        try:
            await body(bus, web)
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
            stop.set()
            await asyncio.gather(ui, follower, return_exceptions=True)


def _received(ts):
    """The console applied SPY's trade that the daemon received at `ts`: it is on SPY's tape
    with that receive time.
    """
    return lambda: any(
        r.get("server_received_ts") == ts for r in ofls.get_content_for_symbol("SPY")
    )


def test_the_daemon_heartbeat_decides_liveness_end_to_end(feed):
    """Real daemon -> real console feed, one program. Live only while the daemon's status beats,
    the Schwab socket is open and the daemon holds the symbol; once the program stops, its last
    status is past the live limit and the feed is down. In regular hours: the beats and the reads
    run from RTH_INSTANT.
    """
    clock = clock_from(RTH_INSTANT)

    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = clock()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
        now = clock()
        assert not lmp.feed_live_for("QQQ", "LEVELONE_EQUITIES", now)  # not held by the daemon
        assert not lmp.feed_live_for("SPY", "NYSE_BOOK", now)  # held on another service only
        assert lmp.daemon_status(now) is not None

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(clock=clock)))
    now = clock() + lmp.FEED_HEARTBEAT_MAX_AGE_SEC + 0.01  # the last beat is past the limit
    assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", now)  # program ended -> feed down
    assert lmp.daemon_status(now) is None


def test_a_live_feed_stays_live_while_the_console_works_through_a_backlog_of_chains(feed):
    """Measured 2026-10-02 after the close: the console spent 79% of its event loop decoding
    chain parts and read 25 of 60 one-second samples of DELL as "feed down" on a healthy feed,
    the daemon's status waiting behind the chains. 300 chains arrive at once and each takes the
    console 20 ms to apply on its event loop (a named stand-in for pricing it: the console's chain
    callback, as start_order_flow_stream sets it, sleeps); the feed, live and holding SPY, reads
    live at every sample a route thread takes while it works through them. In regular hours: the
    beats and the reads run from RTH_INSTANT.
    """
    contracts = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(
            encoding="utf-8"
        )
    )["chain"][:1]
    samples: list = []
    clock = clock_from(RTH_INSTANT)

    def sample(seconds):  # a route, on its own thread, as the console serves them
        end = time_et.elapsed() + seconds
        while time_et.elapsed() < end:
            samples.append(lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
            time.sleep(0.05)

    async def body(bus, web):
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
        for i in range(300):
            for topic, msg in chain_messages(f"ZZ{i:03d}", contracts, time_et.now(), None, None):
                bus.publish(topic, msg)
        sampler = threading.Thread(target=sample, args=(7.0,))
        sampler.start()
        while sampler.is_alive():
            await asyncio.sleep(0.05)

    asyncio.run(
        _run(
            body,
            heartbeat_fn=_daemon_heartbeat(clock=clock),
            on_chain=lambda *_chain: time.sleep(0.02),
        )
    )
    assert samples and all(samples), (
        f"read down in {samples.count(False)} of {len(samples)} samples"
    )


def test_a_closed_schwab_socket_is_not_live(feed):
    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)  # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time_et.now())

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded(feed):
    """Neither the message nor any value it carried: what the console applies, and the SPY record
    a second reader of the daemon's bus takes as the console's _bus_loop does (a LATEST
    subscription, Schwab's records only by live_push.is_forwarded), hold only what Schwab sent
    (here, no CLOSE_PRICE and no 1.05 -- only the non-Schwab message carried them).
    """

    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                bid=1.0,
                ask=1.1,
                last=1.05,
                src="not_schwab",
                ts_recv=time_et.now(),
                native={"LAST_PRICE": 1.05, "CLOSE_PRICE": 1.0},
            ),
        )
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(502.0, ts))
        assert await _until(_received(ts))
        assert not any(
            "CLOSE_PRICE" in item or item.get("LAST_PRICE") == 1.05
            for item in ofls.get_content_for_symbol("SPY")
        ), "the console applied a non-Schwab value"
        sub = bus.subscribe("", policy=LATEST)  # a second reader, as the console's _bus_loop
        try:
            while True:
                topic, record = await asyncio.wait_for(sub.get(), 5)
                if topic == "quote.SPY" and live_push.is_forwarded(topic, record):
                    break
        finally:
            bus.unsubscribe(sub)
        assert "CLOSE_PRICE" not in record["native"], "a non-Schwab value was forwarded as Schwab's"
        assert record["native"]["LAST_PRICE"] == 502.0

    asyncio.run(_run(body))


def test_option_l1_and_book_update_the_contract_and_report_greeks(feed):
    """The console's tick callback, as start_order_flow_stream sets it, records each tick."""
    seen: list = []

    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = time_et.now()
        bus.publish(
            f"optquote.{_CONTRACT}",
            verbatim_msg(
                symbol=_CONTRACT,
                content={"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3, "TOTAL_VOLUME": 5},
                src="schwab_options_l1",
                ts_recv=ts,
            ),
        )
        bus.publish(
            f"book.{_CONTRACT}",
            book_msg(
                symbol=_CONTRACT,
                service="OPTIONS_BOOK",
                src="schwab_book",
                ts_recv=ts,
                content={"key": _CONTRACT, "BIDS": [], "ASKS": []},
            ),
        )
        assert await _until(lambda: (_CONTRACT, ts) in seen)  # with its receive time
        assert seen.count((_CONTRACT, ts)) == 1
        assert ofs._option_contract_last_update_ts[_CONTRACT] == ts
        assert ofls.option_top(_CONTRACT) == {"bid": 1.2, "ask": 1.3}

    asyncio.run(_run(body, on_tick=lambda sym, ts: seen.append((sym, ts))))


#: every sqlite3.connect this process makes while _AUDITING is set, as Python's audit hook reports
#: it
_OPENED: list = []
_AUDITING = threading.Event()
sys.addaudithook(
    lambda event, args: (
        _OPENED.append(args) if event == "sqlite3.connect" and _AUDITING.is_set() else None
    )
)


def test_the_live_loop_never_opens_the_capture_database(feed):
    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(503.0, ts))
        assert await _until(_received(ts))

    _OPENED.clear()
    _AUDITING.set()
    try:
        asyncio.run(_run(body))
    finally:
        _AUDITING.clear()
    assert _OPENED == [], f"the live feed opened a database: {_OPENED}"


def test_no_daemon_serves_nothing_and_the_feed_starts_once_one_is_bound(feed, caplog):
    """With no daemon in the program the console's feed does not start, says why in one line, and
    nothing is served: a Schwab message on a bus no daemon of this program holds is not applied.
    Once the daemon is bound (capture.serve_console, before the web server starts), the feed
    starts and the daemon's next message is applied with its own receive time.
    """
    bus = MessageBus()

    async def run():
        with caplog.at_level("ERROR", logger=ofs.log.name):
            assert ofs.start_order_flow_stream() is False
        bus.publish("quote.SPY", _spy_trade(504.0, time_et.now()))
        await asyncio.sleep(0.3)
        assert ofls.get_content_for_symbol("SPY") == []
        ofs.bind_daemon(capture.Daemon(bus, HealthRegistry(), []))
        assert ofs.start_order_flow_stream() is True
        try:
            ts = time_et.now()
            bus.publish("quote.SPY", _spy_trade(505.0, ts))
            assert await _until(_received(ts))
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)

    asyncio.run(run())
    said = [
        r.getMessage() for r in caplog.records if r.name == ofs.log.name and r.levelname == "ERROR"
    ]
    assert said == ["no capture daemon runs in this program: the console has no data"], said


def test_a_message_missing_its_receive_time_is_dropped_whole():
    ofs._ingest_pushed("quote.ZZZNOTS", {"symbol": "ZZZNOTS", "native": {"LAST_PRICE": 1.0}})
    msg = _spy_trade(1.0, time_et.now())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("quote.ZZZNOPE", msg)
    assert (
        ofls.get_content_for_symbol("ZZZNOTS") == []
        and ofls.get_content_for_symbol("ZZZNOPE") == []
    )


def _stoppable_daemon() -> capture.Daemon:
    """A daemon whose stop is set by {"op": "stop"} (capture.Daemon.console_frame), as capture.run
    gives it one.
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), [])
    daemon.stop = asyncio.Event()
    return daemon


def test_daemon_shutdown_is_not_held_up_by_a_connected_console(feed):
    """A handler blocked waiting for its client's next frame must not keep the program's control
    route open: the program's stop asked on it (launch.py stop's connection, as a console's once
    was) with that client still attached ends the web server at once, well within uvicorn's
    graceful wait (capture.PAGES, after which it would cancel the handler), and closes the
    client's connection.
    """
    daemon = _stoppable_daemon()

    async def run():
        control = None
        try:
            async with program_routes(daemon) as (web, port):
                control = await connect(f"ws://127.0.0.1:{port}/control")
                assert await _until(lambda: len(web.server_state.connections) == 1)
                await control.send(json.dumps({"op": "stop"}))
                assert await _until(daemon.stop.is_set)  # the client still connected
                started = time_et.elapsed()
            # program_routes ended the server, as capture.serve_console ends it on the stop
            took = time_et.elapsed() - started
            await asyncio.wait_for(control.wait_closed(), timeout=3.0)
        finally:
            if control is not None:
                await control.close()
        return web, took

    web, took = asyncio.run(run())
    assert not web.server_state.connections
    assert took < capture.PAGES["timeout_graceful_shutdown"], f"the stop waited {took:.1f} s"


def test_a_stop_reaches_the_daemon_while_the_program_serves():
    """launch.ask_daemon_to_stop, the real one, at the port the program serves on: its
    {"op": "stop"} goes over /control to the daemon, whose stop is set (capture.run then ends
    every task), and the stop's connection is closed by launch.py, so the server holds none.
    """
    daemon = _stoppable_daemon()

    async def run():
        async with program_routes(daemon) as (web, port):
            await asyncio.to_thread(launch.ask_daemon_to_stop, port)
            assert await _until(daemon.stop.is_set)
            assert await _until(lambda: not web.server_state.connections)

    asyncio.run(run())


def test_a_console_frame_the_daemon_cannot_read_is_logged_with_what_arrived(caplog):
    """The program's control route reads every frame a client sends (launch.py stop's is one): one
    that is not JSON, or JSON that is not an object, is logged with what arrived, never dropped
    unseen; a request after it (the stop) still reaches the daemon.
    """
    daemon = _stoppable_daemon()

    async def go():
        async with (
            program_routes(daemon) as (_web, port),
            connect(f"ws://127.0.0.1:{port}/control", max_size=None) as ws,
        ):
            for frame in ("not json", "[1, 2]", json.dumps({"op": "stop"})):
                await ws.send(frame)
            assert await _until(daemon.stop.is_set)

    with caplog.at_level(logging.WARNING, logger=server.log.name):
        asyncio.run(go())
    warned = [r.getMessage() for r in caplog.records if r.name == server.log.name]
    assert daemon.stop.is_set()
    assert any("'not json'" in m for m in warned), warned
    assert any("'[1, 2]'" in m for m in warned), warned


def test_a_web_page_cannot_reach_the_daemons_local_socket():
    """`launch.py stop` sends no Origin and connects; a browser always sends one, and a page on
    any site is refused (403) before it asks the daemon anything (to stop). Induced test
    condition: a client sending the Origin a page's browser would."""
    daemon = _stoppable_daemon()

    async def go():
        async with program_routes(daemon) as (_web, port):
            url = f"ws://127.0.0.1:{port}/control"
            async with connect(url):
                pass
            with pytest.raises(InvalidStatus) as refused:
                async with connect(url, origin="https://example.com") as page:
                    await page.send(json.dumps({"op": "stop"}))
        return refused.value.response.status_code

    assert asyncio.run(asyncio.wait_for(go(), 30)) == 403
    assert not daemon.stop.is_set()


def test_the_control_route_is_refused_while_no_daemon_is_bound():
    """A program whose web server serves with no daemon in its app's state (before
    capture.serve_console sets it, after it ends; the browser tests' console) refuses /control
    (403) before it opens: nothing is handed a stop no daemon would take.
    """

    async def go():
        async with program_routes(None) as (_web, port):
            with pytest.raises(InvalidStatus) as refused:
                async with connect(f"ws://127.0.0.1:{port}/control"):
                    pass
        return refused.value.response.status_code

    assert asyncio.run(asyncio.wait_for(go(), 30)) == 403


def test_another_machine_cannot_reach_the_control_route():
    """The control route answers this PC's own address alone (server.CONTROL_CLIENT), as the old
    control socket did by listening on 127.0.0.1 only, though the program's port listens on every
    address for the pages: a client on another machine is refused before it opens, and the same
    request from this PC is taken. Induced test condition: the client's address, set by
    Starlette's TestClient, which runs the route through the app's own ASGI handling.
    """
    daemon = _stoppable_daemon()
    server.app.state.daemon = daemon  # as capture.serve_console sets it
    try:
        elsewhere = TestClient(server.app, client=("192.168.1.20", 50000))
        with pytest.raises(WebSocketDisconnect) as refused, elsewhere.websocket_connect("/control"):
            pass
        with TestClient(server.app, client=(server.CONTROL_CLIENT, 50000)).websocket_connect(
            "/control"
        ) as control:
            control.send_text(json.dumps({"op": "stop"}))
    finally:
        server.app.state.daemon = None
    assert refused.value.code == 1000  # closed before accept: 403 to a real client
    assert daemon.stop.is_set()


def test_a_late_console_gets_the_current_record_with_each_fields_own_time(feed):
    """Schwab LEVELONE sends only changed fields. A console whose feed starts after a trade and a
    later bid/ask tick gets the bus's current record (docs/DATA_FLOW.md §2 D3): the trade's fields
    and the bid/ask together, each stamped with the receive time the daemon gave the message
    that carried it -- the trade is not lost behind the later bid/ask-only tick, nor re-dated
    to it.
    """

    async def run():
        bus = MessageBus()
        ofs.bind_daemon(capture.Daemon(bus, HealthRegistry(), []))
        # the daemon publishes a trade, then a bid/ask-only tick -- before any console exists
        t_trade = time_et.now() - 5.0
        t_quote = time_et.now() - 1.0
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                src="schwab_l1",
                ts_recv=t_trade,
                native={"key": "SPY", "LAST_PRICE": 505.0, "CLOSE_PRICE": 500.0},
            ),
        )
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                src="schwab_l1",
                ts_recv=t_quote,
                native={"key": "SPY", "BID_PRICE": 504.9, "ASK_PRICE": 505.1},
            ),
        )
        await asyncio.sleep(0.05)
        assert ofs.start_order_flow_stream()
        try:
            assert await _until(_received(t_trade))  # the trade, at its own receive time
            assert not _received(t_quote)(), "the trade was re-dated to the later bid/ask tick"
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)

    asyncio.run(run())
