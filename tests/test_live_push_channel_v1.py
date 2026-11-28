"""Daemon -> console in one program, end to end, with no database in the live path.

The REAL daemon (capture.Daemon on a real stream_spine.MessageBus, its market follower, and its
browser price socket live_ui.serve_live_ui on the program's web server, whose beat records the
daemon's status) and the REAL console feed
(app.options.order_flow.streaming.start_order_flow_stream: _bus_loop reading the daemon's bus,
bound with bind_daemon) run on one event loop, as capture.run runs them. These tests prove:

  * a Schwab message published on the daemon's bus reaches the console's live planes with its
    OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are applied or forwarded (any other src on the same topic is
    not);
  * a console that starts late first takes the bus's current records, then each that changes;
  * the live loop never opens the capture database;
  * a record that fails to apply is counted, logged and served on the beat, and the next applied;
  * with no daemon in the program nothing is served, and the feed starts once one is bound.
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

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture, live_push, live_ui
from feed import connection
from feed.chain_sweep import chain_messages
from option_contract import StreamedTop
from stream_spine import (
    LATEST,
    HealthRegistry,
    MessageBus,
    book_msg,
    current_key,
    quote_msg,
    verbatim_msg,
)
from tests.feed_live_helper import RTH_INSTANT, clock_from
from tests.real_chains import MRVL
from tests.shared_helpers import until

_CONTRACT = "SPY   260918C00500000"


#: SPY's LEVELONE_EQUITIES message of 2026-11-11 as Schwab sent it, the base of every SPY trade
#: here (tests/fixtures/real_premarket_first_prints_2026_11_11.json)
SPY_SENT = next(
    m["item"]
    for m in json.loads(
        (
            Path(__file__).parent / "fixtures" / "real_premarket_first_prints_2026_11_11.json"
        ).read_text(encoding="utf-8")
    )["messages"]
    if m["ticker"] == "SPY"
)
#: its last price: each test's trades are it and a cent or more from it
SPY_LAST = SPY_SENT["LAST_PRICE"]


def _spy_trade(last: float, ts: float) -> dict:
    """SPY's real message with a trade at `last` and `ts` (INDUCED: a cent's spread round it)."""
    native = {
        **SPY_SENT,
        "BID_PRICE": last - 0.01,
        "ASK_PRICE": last + 0.01,
        "LAST_PRICE": last,
        "QUOTE_TIME_MILLIS": int(ts * 1000),
        "TRADE_TIME_MILLIS": int(ts * 1000),
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


def listener() -> tuple[socket.socket, str]:
    """Open a listening socket of the test's own and return it with its address.

    Its port is the system's pick as it binds, as capture.open_sockets opens the program's.
    """
    sock = socket.create_server(("127.0.0.1", 0))
    return sock, f"ws://127.0.0.1:{sock.getsockname()[1]}"


def program_web(**settings) -> capture._PagesServer:
    """Return the program's web server with the console's startup work not run (lifespan off).

    It is capture._PagesServer with capture.PAGES, `settings` over them: its page socket, /ws,
    alone.
    """
    return capture._PagesServer(
        uvicorn.Config(server.app, **{**capture.PAGES, "lifespan": "off", **settings})
    )


async def serve_page_socket(
    stop: asyncio.Event, sock: socket.socket, prices: dict, web=None, **settings
):
    """Serve the page's price socket as the program serves it, until `stop`.

    The daemon's side (live_ui.serve_live_ui, `prices` its arguments, with the program's panels,
    server.PAGE_PANELS) and /ws on the program's web server (`web`, a test's to watch, or
    program_web with `settings`) on `sock`.
    """
    web = web if web is not None else program_web(**settings)
    serving = asyncio.create_task(web.serve(sockets=[sock]))
    try:
        await live_ui.serve_live_ui(
            stop,
            state=server.app.state,
            panels=server.PAGE_PANELS,
            priced=server.PRICED_PANELS,
            on_select=server.ticker_selected,
            **prices,
        )
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
        "apply_failures": 0,
        "tick_failures": 0,
    }


async def _run(body, heartbeat_fn=None, on_tick=None, on_chain=None):
    """Run the daemon on one bus, as capture.run runs it, with the console's real feed.

    The program's web server and its browser price socket (serve_page_socket), whose beat records
    the daemon's status (the one program's one plane), and its market follower feeding the plane
    -- with the console's real feed started on the same loop, bound to that daemon
    (start_order_flow_stream, with the tick and chain callbacks the console passes it). `body`
    takes the bus and the web server.
    """
    bus = MessageBus()
    stop = asyncio.Event()
    ui_stats: dict = {}
    daemon = capture.Daemon(bus, HealthRegistry(), [])
    web = program_web()
    ui = asyncio.create_task(
        serve_page_socket(
            stop,
            listener()[0],
            {
                "heartbeat_fn": heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat(),
                "stats": ui_stats,
            },
            web=web,
        )
    )
    follower = asyncio.create_task(daemon.follow_market(stop))
    assert await until(lambda: web.started and "clients" in ui_stats)  # both serving
    ofs.bind_daemon(daemon)  # as capture.serve_console binds it
    assert ofs.start_order_flow_stream(on_tick_callback=on_tick, on_chain_callback=on_chain)
    try:
        await body(bus, web)
    finally:
        ofs.stop_order_flow_stream()
        ofs.bind_daemon(None)
        stop.set()
        await asyncio.gather(ui, follower, return_exceptions=True)


def _received(ts):
    """Check the console applied SPY's trade that the daemon received at `ts`.

    It is on SPY's tape with that receive time.
    """
    return lambda: any(r.server_received_ts == ts for r in ofls.prints("SPY"))


@pytest.mark.usefixtures("feed")
def test_the_daemon_heartbeat_decides_liveness_end_to_end():
    """Real daemon -> real console feed, one program.

    Live only while the daemon's status beats, the Schwab socket is open and the daemon holds
    the symbol; once the program stops, its last status is past the live limit and the feed is
    down. In regular hours: the beats and the reads run from RTH_INSTANT.
    """
    clock = clock_from(RTH_INSTANT)

    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = clock()
        bus.publish("quote.SPY", _spy_trade(SPY_LAST, ts))
        assert await until(_received(ts))
        assert await until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
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

    async def body(bus, _web):
        assert await until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
        for i in range(300):
            for topic, msg in chain_messages(
                f"ZZ{i:03d}", contracts, time_et.now(), None, None, False
            ):
                bus.publish(topic, msg)
        sampler = threading.Thread(target=sample, args=(7.0,))
        sampler.start()
        await asyncio.to_thread(sampler.join)  # the loop keeps working through the chains

    asyncio.run(
        _run(
            body,
            heartbeat_fn=_daemon_heartbeat(clock=clock),
            on_chain=lambda *_chain: time.sleep(0.02),  # INDUCED: a slow reader of each chain
        )
    )
    assert samples and all(samples), (
        f"read down in {samples.count(False)} of {len(samples)} samples"
    )


def test_a_chain_fetched_before_the_one_held_never_becomes_current():
    """MRVL's captured chain (tests/real_chains.py, 2,496 contracts: five parts) fetched twice.

    INDUCED: the later fetch's parts reach the bus first. The bus holds the newest fetch of a
    ticker whole: the earlier fetch's parts, arriving after it, are never current, in part or
    whole.
    """
    bus = MessageBus()
    at = MRVL.now.timestamp()
    newer = chain_messages("MRVL", MRVL.chain, at + 60, MRVL.spot, at + 60, False)
    older = chain_messages("MRVL", MRVL.chain, at, MRVL.spot, at, False)
    assert len(newer) == len(older) == 5
    for topic, msg in newer:
        bus.publish(topic, msg)
    key = current_key(*newer[0])
    held = bus.current[key]
    for topic, msg in older:
        bus.publish(topic, msg)
        assert bus.current[key] is held
    assert [part["ts_recv"] for part in held[1]] == [at + 60] * 5


@pytest.mark.usefixtures("feed")
def test_a_closed_schwab_socket_is_not_live():
    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(SPY_LAST, ts))
        assert await until(_received(ts))
        # a heartbeat arrived: the daemon's status, its Schwab socket closed, is recorded
        assert await until(lambda: lmp.daemon_status(time_et.now()) is not None)
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time_et.now())

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


@pytest.mark.usefixtures("feed")
def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded():
    """Neither the message nor any value it carried is forwarded.

    What the console applies, and the SPY record a second reader of the daemon's bus takes as
    the console's _bus_loop does (a LATEST subscription, Schwab's records only by
    live_push.is_forwarded), hold only what Schwab sent (here, Schwab's own CLOSE_PRICE and no
    1.05 or 1.00 -- only the non-Schwab message carried them).
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
        bus.publish("quote.SPY", _spy_trade(SPY_LAST + 0.01, ts))
        assert await until(_received(ts))
        assert not any(item.price in (1.0, 1.05) for item in ofls.prints("SPY")), (
            "the console applied a non-Schwab value"
        )
        sub = bus.subscribe("", policy=LATEST)  # a second reader, as the console's _bus_loop
        try:
            while True:
                topic, record = await asyncio.wait_for(sub.get(), 5)
                if topic == "quote.SPY" and live_push.is_forwarded(topic, record):
                    break
        finally:
            bus.unsubscribe(sub)
        assert record["native"]["CLOSE_PRICE"] == SPY_SENT["CLOSE_PRICE"], (
            "a non-Schwab value was forwarded as Schwab's"
        )
        assert record["native"]["LAST_PRICE"] == SPY_LAST + 0.01

    asyncio.run(_run(body))


@pytest.mark.usefixtures("feed")
def test_option_l1_and_book_update_the_contract_and_report_greeks():
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
        assert await until(lambda: _CONTRACT in seen)
        assert seen.count(_CONTRACT) == 1
        assert ofls.streamed_values([_CONTRACT])[_CONTRACT].greeks.total_volume.ts_recv == ts
        assert ofls.option_top(_CONTRACT) == StreamedTop(bid=1.2, ask=1.3)

    asyncio.run(_run(body, on_tick=seen.append))


def test_the_feed_started_again_while_it_runs_stays_the_one_it_was():
    """The console's feed is started once a daemon is bound (as capture.serve_console does).

    Started again while it reads the bus, it says it runs and keeps its one task, its callbacks
    as set: a second reader of the same bus would apply every message twice.
    """

    async def body(_bus, _web):
        task = ofs.FEED.task
        assert task is not None and not task.done()
        assert ofs.start_order_flow_stream(on_tick_callback=print) is True
        assert ofs.FEED.task is task and ofs.FEED.on_tick is not print

    asyncio.run(_run(body))


def test_a_tick_callback_that_fails_is_counted_and_every_trade_is_still_applied(caplog):
    """SPY's real message, three trades of it published on the daemon's bus.

    INDUCED: the console's tick callback raises each time it is called (once for the ticks taken
    together). Each failure is counted (the feed's `tick_failures`, which rides the daemon's
    beat) and logged; every trade is still on SPY's tape with its own receive time.
    """
    before = ofs.FEED.tick_failures
    at = [time_et.now() - 3.0 + i for i in range(3)]
    calls: list[str] = []

    def failing(sym: str) -> None:
        calls.append(sym)
        raise RuntimeError("a tick callback that fails")

    async def body(bus, _web):
        for i, ts in enumerate(at):  # each once the feed reads (a late reader takes the newest)
            bus.publish("quote.SPY", _spy_trade(SPY_LAST + 0.01 * (i + 1), ts))
            assert await until(_received(ts))
        assert await until(
            lambda: calls and ofs.FEED.tick_failures == before + len(calls),
            state=lambda: (calls, before, ofs.FEED.tick_failures),
        )

    asyncio.run(_run(body, on_tick=failing))
    assert set(calls) == {"SPY"}
    assert "tick callback failed for SPY" in caplog.text
    assert "a tick callback that fails" in caplog.text


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
    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no copy over a socket
        ts = time_et.now()
        bus.publish("quote.SPY", _spy_trade(SPY_LAST + 0.02, ts))
        assert await until(_received(ts))

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
        bus.publish("quote.SPY", _spy_trade(SPY_LAST + 0.03, time_et.now()))
        # nothing runs on this loop but this test that could apply it
        assert asyncio.all_tasks() == {asyncio.current_task()}
        assert ofls.prints("SPY") == []
        ofs.bind_daemon(capture.Daemon(bus, HealthRegistry(), []))
        assert ofs.start_order_flow_stream() is True
        try:
            ts = time_et.now()
            bus.publish("quote.SPY", _spy_trade(SPY_LAST + 0.04, ts))
            assert await until(_received(ts))
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)

    asyncio.run(run())
    said = [
        r.getMessage() for r in caplog.records if r.name == ofs.log.name and r.levelname == "ERROR"
    ]
    assert said == ["no capture daemon runs in this program: the console has no data"], said


@pytest.mark.usefixtures("feed")
def test_a_message_missing_its_receive_time_is_dropped_whole(caplog):
    """A record that fails to apply is counted and logged, and the console's loop goes on.

    INDUCED: SPY's real quote with no receive time, on topics of their own (ZZZNOPE0, ...), which
    the daemon's constructor (stream_spine.quote_msg) never makes. Each fails to apply: its trade
    has no receive time to be stamped with (each field's is none), so nothing of it reaches a
    tape, each is counted (Feed.apply_failures) and the daemon's status beat carries the count,
    the failure the count reaches a power of two at is logged with its traceback, and SPY's
    trade published after them is applied.
    """
    before = ofs.FEED.apply_failures
    failing = 1 << before.bit_length()  # the count's next power of two: that failure is logged
    bad = [f"ZZZNOPE{i}" for i in range(failing - before)]
    clock = clock_from(RTH_INSTANT)

    async def body(bus, _web):
        for sym in bad:
            msg = _spy_trade(SPY_LAST, clock())
            msg["symbol"] = sym
            del msg["ts_recv"]
            bus.publish(f"quote.{sym}", msg)
        ts = clock()
        bus.publish("quote.SPY", _spy_trade(SPY_LAST, ts))
        assert await until(_received(ts))  # the loop went on past them

    with caplog.at_level("WARNING", logger=ofs.log.name):
        asyncio.run(_run(body))
    assert all(ofls.prints(sym) == [] for sym in bad)
    assert ofs.FEED.apply_failures == failing
    beat = capture.Daemon(MessageBus(), HealthRegistry(), []).status(clock())
    assert beat["apply_failures"] == failing
    logged = [
        r
        for r in caplog.records
        if r.name == ofs.log.name and f"record not applied ({failing} failures)" in r.getMessage()
    ]
    assert len(logged) == 1 and logged[0].exc_info is not None, logged
    # the record is named, and the receive times its trade's fields hold are none
    assert "quote.ZZZNOPE" in logged[0].getMessage() and "NoneType" in logged[0].getMessage()


#: production's stream of 2026-10-05 14:00:00-14:00:03 CT (RTH): every LEVELONE_OPTIONS item
#: Schwab sent, in receive order, as stored, as the daemon publishes each
_OPTION_BURST = [
    connection._message(m["service"], m["item"]["key"], m["item"], m["schwab_ts"], m["ts_recv"])
    for m in json.loads(
        (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
            encoding="utf-8"
        )
    )["messages"]
    if m["service"] == "LEVELONE_OPTIONS"
]


def _has_bid(symbol: str, bid: float) -> bool:
    """Whether the console's top of book for `symbol` holds `bid`."""
    return ofls.option_top(symbol).bid == bid


@pytest.mark.usefixtures("feed")
def test_the_console_takes_its_records_many_to_a_turn_of_its_loop():
    """Each turn of the loop waits to take back the interpreter lock from the program's threads.

    Up to 5 ms each while one is busy, so a turn per record left a contract behind a pass of
    every other one changed: the chain ladder showed Schwab's bids a median 4.2 s late
    (2026-11-19). Three seconds of production's option stream, every contract's newest record on
    the daemon's bus when the console starts, are all applied in a turn per RECORDS_PER_TURN
    records, not one per contract: each contract's bid is the last Schwab sent for it.
    """
    newest: dict[str, float] = {}
    for _kind, msg in _OPTION_BURST:
        if "BID_PRICE" in msg["content"]:
            newest[msg["symbol"]] = msg["content"]["BID_PRICE"]

    async def run():
        bus = MessageBus()
        ofs.bind_daemon(capture.Daemon(bus, HealthRegistry(), []))
        for kind, msg in _OPTION_BURST:
            bus.publish(f"{kind}.{msg['symbol']}", msg)
        turns = 0

        async def count():
            nonlocal turns
            while True:
                turns += 1
                await asyncio.sleep(0)

        counting = asyncio.create_task(count())
        assert ofs.start_order_flow_stream()
        try:
            while not all(_has_bid(s, b) for s, b in newest.items()):
                await asyncio.sleep(0)
        finally:
            counting.cancel()
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
        return turns

    turns = asyncio.run(run())
    contracts = len({msg["symbol"] for _kind, msg in _OPTION_BURST})
    assert len(newest) > 2 * ofs.RECORDS_PER_TURN, "a burst of several turns' records"
    assert turns <= 2 * (contracts // ofs.RECORDS_PER_TURN + 1), (
        f"{turns} turns of the loop for {contracts} contracts' records"
    )


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
                # the real message's trade fields alone, as Schwab sends a change
                native={k: SPY_SENT[k] for k in ("key", "LAST_PRICE", "CLOSE_PRICE")},
            ),
        )
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                src="schwab_l1",
                ts_recv=t_quote,
                native={k: SPY_SENT[k] for k in ("key", "BID_PRICE", "ASK_PRICE")},
            ),
        )  # publish is synchronous: both are the bus's current record now
        assert ofs.start_order_flow_stream()
        try:
            assert await until(_received(t_trade))  # the trade, at its own receive time
            assert not _received(t_quote)(), "the trade was re-dated to the later bid/ask tick"
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)

    asyncio.run(run())
