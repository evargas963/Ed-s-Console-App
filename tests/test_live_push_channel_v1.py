"""Daemon -> console in one program, end to end, with no database in the live path.

The REAL daemon (capture.Daemon on a real stream_spine.MessageBus, its market follower, its
browser price socket live_ui.serve_live_ui, whose beat records the daemon's status, and its local
socket live_push.serve_live_push) and the REAL console feed
(app.options.order_flow.streaming.start_order_flow_stream: _bus_loop reading the daemon's bus,
bound with bind_daemon) run on one event loop, as capture.run runs them. These tests prove:

  * a Schwab message published on the daemon's bus reaches the console's live planes with its
    OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are applied or forwarded (any other src on the same topic is
    not);
  * a console that starts late first takes the bus's current records, then each that changes;
  * the live loop never opens the capture database;
  * with no daemon in the program nothing is served, and the feed starts once one is bound;
  * the daemon's local socket does not hold its stop behind a connected client.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from websockets.asyncio.client import connect

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
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


@pytest.fixture
def feed():
    """Clear the console's state before and after, and leave no daemon bound after."""
    ofs.stop_order_flow_stream()
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    lmp._by_ticker.clear()
    yield
    ofs.stop_order_flow_stream()
    ofs.bind_daemon(None)
    lmp._by_ticker.clear()
    lmp.record_feed_down()


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


async def serve_page_socket(stop: asyncio.Event, sock: socket.socket, prices: dict, **settings):
    """Serve the page's price socket as the program serves it, until `stop`.

    The daemon's side (live_ui.serve_live_ui, `prices` its arguments) and /ws on the program's
    web server (capture._PagesServer with capture.PAGES, `settings` over them) on `sock`. The
    console's startup work is not run (lifespan off): the page socket alone.
    """
    web = capture._PagesServer(
        uvicorn.Config(server.app, **{**capture.PAGES, "lifespan": "off", **settings})
    )
    serving = asyncio.create_task(web.serve(sockets=[sock]))
    try:
        await live_ui.serve_live_ui(stop, **prices)
    finally:
        web.should_exit = True
        await serving


def _daemon_heartbeat(socket_open=True, held=("SPY",), clock=time_et.now):
    """Return what capture.py's heartbeat reports for a session holding `held`.

    Held on LEVELONE_EQUITIES, each beat stamped by `clock`.
    """
    return lambda _now: {
        "ts": clock(),
        "schwab_socket_open": socket_open,
        "held": {"LEVELONE_EQUITIES": list(held)},
        "health": {},
    }


async def _run(body, heartbeat_fn=None, on_tick=None, on_chain=None):
    """Run the daemon on one bus, as capture.run runs it, with the console's real feed.

    Its local socket (live push), its browser price socket, whose beat records the daemon's
    status (the one program's one plane), and its market follower feeding the plane -- with the
    console's real feed started on the same loop, bound to that daemon (start_order_flow_stream,
    with the tick and chain callbacks the console passes it).
    """
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    ui_stats: dict = {}
    daemon = capture.Daemon(bus, HealthRegistry(), [])
    server = asyncio.create_task(
        live_push.serve_live_push(stop, daemon.console_frame, listener()[0], stats=stats)
    )
    ui = asyncio.create_task(
        live_ui.serve_live_ui(
            stop,
            heartbeat_fn=heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat(),
            stats=ui_stats,
        )
    )
    follower = asyncio.create_task(daemon.follow_market(stop))
    assert await _until(lambda: "clients" in stats and "clients" in ui_stats)  # both serving
    ofs.bind_daemon(daemon)
    assert ofs.start_order_flow_stream(on_tick_callback=on_tick, on_chain_callback=on_chain)
    try:
        await body(bus, stats)
    finally:
        ofs.stop_order_flow_stream()
        ofs.bind_daemon(None)
        stop.set()
        await asyncio.gather(server, ui, follower, return_exceptions=True)


def _received(ts):
    """Check the console applied SPY's trade that the daemon received at `ts`.

    It is on SPY's tape with that receive time.
    """
    return lambda: any(
        r.get("server_received_ts") == ts for r in ofls.get_content_for_symbol("SPY")
    )


@pytest.mark.usefixtures("feed")
def test_the_daemon_heartbeat_decides_liveness_end_to_end():
    """Real daemon -> real console feed, one program.

    Live only while the daemon's status beats, the Schwab socket is open and the daemon holds
    the symbol; once the program stops, its last status is past the live limit and the feed is
    down. In regular hours: the beats and the reads run from RTH_INSTANT.
    """
    clock = clock_from(RTH_INSTANT)

    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no copy over the socket
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


@pytest.mark.usefixtures("feed")
def test_a_live_feed_stays_live_while_the_console_works_through_a_backlog_of_chains():
    """Measured 2026-10-02 after the close: chains held the loop and a live feed read down.

    The console spent 79% of its event loop decoding chain parts and read 25 of 60 one-second
    samples of DELL as "feed down" on a healthy feed, the daemon's status waiting behind the
    chains. 300 chains arrive at once and each takes the console 20 ms to apply on its event
    loop (a named stand-in for pricing it: the console's chain callback, as
    start_order_flow_stream sets it, sleeps); the feed, live and holding SPY, reads live at every
    sample a route thread takes while it works through them. In regular hours: the beats and the
    reads run from RTH_INSTANT.
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

    async def body(bus, _stats):
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


@pytest.mark.usefixtures("feed")
def test_a_closed_schwab_socket_is_not_live():
    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no copy over the socket
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)  # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time_et.now())

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


@pytest.mark.usefixtures("feed")
def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded():
    """Neither the message nor any value it carried is forwarded.

    What the console applies, and the SPY record a second reader of the daemon's bus takes as
    the console's _bus_loop does (a LATEST subscription, Schwab's records only by
    live_push.is_forwarded), hold only what Schwab sent (here, no CLOSE_PRICE and no 1.05 --
    only the non-Schwab message carried them).
    """

    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no copy over the socket
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


@pytest.mark.usefixtures("feed")
def test_option_l1_and_book_update_the_contract_and_report_greeks():
    """The console's tick callback, as start_order_flow_stream sets it, records each tick."""
    seen: list = []

    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no copy over the socket
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


@pytest.mark.usefixtures("feed")
def test_the_live_loop_never_opens_the_capture_database():
    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no copy over the socket
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


@pytest.mark.usefixtures("feed")
def test_no_daemon_serves_nothing_and_the_feed_starts_once_one_is_bound(caplog):
    """With no daemon in the program the console's feed does not start, and says why in one line.

    Nothing is served: a Schwab message on a bus no daemon of this program holds is not applied.
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


@pytest.mark.usefixtures("feed")
def test_daemon_shutdown_is_not_held_up_by_a_connected_console():
    """A handler blocked waiting for its client's next frame must not keep the socket open.

    The daemon's local socket: stopping the daemon with a client attached (launch.py stop's
    connection, as a console's once was) hung forever before the fix.
    """

    async def run():
        stop = asyncio.Event()
        stats: dict = {}
        sock, url = listener()
        server = asyncio.create_task(live_push.serve_live_push(stop, [].append, sock, stats=stats))
        assert await _until(lambda: "clients" in stats)  # serving
        try:
            async with connect(url):
                assert await _until(lambda: stats["clients"] == 1)
                stop.set()  # the client still connected
                await asyncio.wait_for(asyncio.shield(server), timeout=3.0)
                assert stats["clients"] == 0
        finally:
            stop.set()
            await asyncio.gather(server, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.usefixtures("feed")
def test_a_late_console_gets_the_current_record_with_each_fields_own_time():
    """Schwab LEVELONE sends only changed fields.

    A console whose feed starts after a trade and a later bid/ask tick gets the bus's current
    record (docs/DATA_FLOW.md §2 D3): the trade's fields and the bid/ask together, each stamped
    with the receive time the daemon gave the message that carried it -- the trade is not lost
    behind the later bid/ask-only tick, nor re-dated to it.
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
