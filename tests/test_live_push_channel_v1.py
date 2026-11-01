"""Daemon -> console, end to end, with no database in the live path.

The REAL stream_spine.MessageBus and the console's REAL reader of it
(app.options.order_flow.streaming.follow), with the daemon's REAL price-row push:

  * a Schwab message published on the daemon's bus reaches the console's live-price plane
    with its OWN receive time (never the time the console processed it);
  * only Schwab-sourced messages are forwarded (any other src on the same topic is not);
  * a connecting console first receives the bus's current records, then each that changes;
  * the live loop never opens the capture database;
  * a record that fails is logged and the next one applied, and a daemon's next run is read.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.market_data.schwab.streaming import capture, live_ui
from stream_spine import HealthRegistry, MessageBus, book_msg, options_quote_msg, quote_msg
from tests.feed_live_helper import RTH_INSTANT, clock_from

_CONTRACT = "SPY   260918C00500000"


@pytest.fixture
def feed():
    """The console's state cleared before and after."""
    ofs._feed_running = False
    ofs._price_rows.clear()
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    lmp._by_ticker.clear()
    yield
    ofs._feed_running = False
    ofs._price_rows.clear()
    lmp._by_ticker.clear()


def _port(stats: dict) -> int:
    """The port a daemon server took (it was asked for port 0: the system's free pick)."""
    return int(stats["listening"].rsplit(":", 1)[1])


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
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def _daemon_heartbeat(socket_open=True, held=("SPY",), clock=time.time):
    """What capture.py's heartbeat reports for a session holding `held` on LEVELONE_EQUITIES, each
    beat stamped by `clock`."""
    return lambda _now: {
        "ts": clock(),
        "schwab_socket_open": socket_open,
        "held": {"LEVELONE_EQUITIES": list(held)},
        "health": {},
    }


async def _run(body, heartbeat_fn=None):
    """The daemon's bus and its price-row push, which beats the daemon's status, with its market
    follower feeding the plane the price rows are read from, and the console's real reader of the
    bus and real feed loop. The daemon's own record of each beat is kept out of the plane
    (record_heartbeat): what the console knows of the daemon arrives on the push or not at
    all."""
    bus = MessageBus()
    stop = asyncio.Event()
    ui_stats: dict = {}
    ui = asyncio.create_task(
        live_ui.serve_live_ui(
            stop,
            heartbeat_fn=heartbeat_fn if heartbeat_fn is not None else _daemon_heartbeat(),
            host="127.0.0.1",
            port=0,
            stats=ui_stats,
            record_heartbeat=lambda _beat: None,
        )
    )
    daemon = capture.Daemon(bus, HealthRegistry(), [])
    follower = asyncio.create_task(daemon.follow_market(stop))
    assert await _until(lambda: ui_stats.get("listening"))
    ofs._feed_running = True
    console = asyncio.create_task(ofs.follow(bus, daemon))
    client = asyncio.create_task(ofs._feed_loop(f"ws://127.0.0.1:{_port(ui_stats)}", 0.05))
    try:
        assert await _until(lambda: ofs._daemon is daemon)
        await body(bus)
    finally:
        ofs._feed_running = False
        client.cancel()
        console.cancel()
        stop.set()
        await asyncio.gather(client, console, ui, follower, return_exceptions=True)


def _received(ts):
    """The console applied SPY's trade that the daemon received at `ts`: it is on SPY's tape
    with that receive time."""
    return lambda: any(
        r.get("server_received_ts") == ts for r in ofls.get_content_for_symbol("SPY")
    )


def test_the_daemon_heartbeat_decides_liveness_end_to_end(feed):
    """Real daemon servers -> real console feed loop. Live only while the daemon's status beats
    arrive, the Schwab socket is open and the daemon holds the symbol; the feed is down the
    moment the daemon's connections end. In regular hours: the beats and the reads run from
    RTH_INSTANT."""
    clock = clock_from(RTH_INSTANT)

    async def body(bus):
        ts = clock()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
        now = clock()
        assert not lmp.feed_live_for("QQQ", "LEVELONE_EQUITIES", now)  # not held by the daemon
        assert not lmp.feed_live_for("SPY", "NYSE_BOOK", now)  # held on another service only
        assert lmp.daemon_status(now) is not None

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(clock=clock)))
    now = clock()
    assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", now)  # push ended -> feed down
    assert lmp.daemon_status(now) is None


def test_a_live_feed_stays_live_while_the_console_works_through_a_backlog_of_chains(feed):
    """Measured 2026-10-02 after the close: the console spent 79% of its event loop decoding
    chain parts and read 25 of 60 one-second samples of DELL as "feed down" on a healthy feed,
    the daemon's status waiting behind the chains. 300 chains arrive at once and each takes the
    console 20 ms to apply on its event loop (a named stand-in for pricing it: the console's chain
    callback, as start_order_flow_stream sets it, sleeps); the feed, live and holding SPY, reads
    live at every sample a route thread takes while it works through them. In regular hours: the
    beats and the reads run from RTH_INSTANT."""
    import json as _json
    import threading
    from pathlib import Path

    from calibration.complete_chain_capture import chain_messages

    contracts = _json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(
            encoding="utf-8"
        )
    )["chain"][:1]
    samples: list = []
    clock = clock_from(RTH_INSTANT)

    def sample(seconds):  # a route, on its own thread, as the console serves them
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            samples.append(lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
            time.sleep(0.05)

    async def body(bus):
        assert await _until(lambda: lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", clock()))
        for i in range(300):
            for topic, msg in chain_messages(f"ZZ{i:03d}", contracts, time.time(), None, None):
                bus.publish(topic, msg)
        sampler = threading.Thread(target=sample, args=(7.0,))
        sampler.start()
        while sampler.is_alive():
            await asyncio.sleep(0.05)

    ofs._on_chain_callback = lambda *_chain: time.sleep(0.02)
    try:
        asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(clock=clock)))
    finally:
        ofs._on_chain_callback = None
    assert samples and all(samples), (
        f"read down in {samples.count(False)} of {len(samples)} samples"
    )


def test_a_closed_schwab_socket_is_not_live(feed):
    async def body(bus):
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(501.0, ts))
        assert await _until(_received(ts))
        await asyncio.sleep(1.3)  # at least one heartbeat arrived
        assert not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time())

    asyncio.run(_run(body, heartbeat_fn=_daemon_heartbeat(socket_open=False)))


def test_a_non_schwab_message_on_the_same_topic_is_never_forwarded(feed):
    """The console applies only what Schwab sent: the non-Schwab record is not taken."""

    async def body(bus):
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                bid=1.0,
                ask=1.1,
                last=1.05,
                src="not_schwab",
                ts_recv=time.time(),
                native={"LAST_PRICE": 1.05, "CLOSE_PRICE": 1.0},
            ),
        )
        ts = time.time()
        bus.publish("quote.SPY", _spy_trade(502.0, ts))
        assert await _until(_received(ts))
        applied = ofls.get_content_for_symbol("SPY")
        assert [r["server_received_ts"] for r in applied] == [ts], "only Schwab's was applied"

    asyncio.run(_run(body))


def test_option_l1_and_book_update_the_contract_and_report_greeks(feed):
    """The console's tick callback, as start_order_flow_stream sets it, records each tick."""
    seen: list = []

    async def body(bus):
        ts = time.time()
        bus.publish(
            f"optquote.{_CONTRACT}",
            options_quote_msg(
                symbol=_CONTRACT,
                content={"key": _CONTRACT, "BID_PRICE": 1.2, "ASK_PRICE": 1.3, "GAMMA": 0.05},
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
        assert await _until(lambda: _CONTRACT in seen)  # (SPY's price row ticks too)
        assert seen.count(_CONTRACT) == 1
        assert ofs._option_contract_last_update_ts[_CONTRACT] == ts
        assert ofls.option_top(_CONTRACT) == {"bid": 1.2, "ask": 1.3}

    ofs._on_tick_callback = seen.append
    try:
        asyncio.run(_run(body))
    finally:
        ofs._on_tick_callback = None


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
    async def body(bus):
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


def test_a_record_that_fails_is_logged_and_a_daemons_next_run_is_read(feed, caplog):
    """Induced test condition: a /markets record with no status. The record after it is applied,
    and the reader of a daemon's next run, on its new bus, applies what that bus carries."""

    async def run():
        bus = MessageBus()
        console = asyncio.create_task(ofs.follow(bus, capture.Daemon(bus, HealthRegistry(), [])))
        assert await _until(lambda: ofs._daemon is not None)
        bus.publish("markets.2026-10-07", {"src": "schwab_markets", "date": "2026-10-07"})
        first = time.time()
        bus.publish("quote.SPY", _spy_trade(503.0, first))
        assert await _until(_received(first))
        console.cancel()
        await asyncio.gather(console, return_exceptions=True)
        assert ofs._daemon is None
        bus = MessageBus()
        console = asyncio.create_task(ofs.follow(bus, capture.Daemon(bus, HealthRegistry(), [])))
        try:
            assert await _until(lambda: ofs._daemon is not None)
            second = first + 1
            bus.publish("quote.SPY", _spy_trade(504.0, second))
            assert await _until(_received(second))
        finally:
            console.cancel()

    asyncio.run(run())
    assert any("markets.2026-10-07 not applied" in r.getMessage() for r in caplog.records)


def test_a_message_missing_its_receive_time_is_dropped_whole():
    ofs._ingest_pushed("quote.ZZZNOTS", {"symbol": "ZZZNOTS", "native": {"LAST_PRICE": 1.0}})
    msg = _spy_trade(1.0, time.time())
    msg["symbol"] = "ZZZNOPE"
    del msg["ts_recv"]
    ofs._ingest_pushed("quote.ZZZNOPE", msg)
    assert (
        ofls.get_content_for_symbol("ZZZNOTS") == []
        and ofls.get_content_for_symbol("ZZZNOPE") == []
    )


def test_a_late_console_gets_the_current_record_with_each_fields_own_time(feed):
    """Schwab LEVELONE sends only changed fields. A console connecting after a trade and a
    later bid/ask tick gets the current record (docs/DATA_FLOW.md §2 D3): the trade's fields
    and the bid/ask together, each stamped with the receive time the daemon gave the message
    that carried it -- the trade is not lost behind the later bid/ask-only tick, nor re-dated
    to it."""

    async def run():
        bus = MessageBus()
        # the daemon publishes a trade, then a bid/ask-only tick -- before any console exists
        t_trade = time.time() - 5.0
        t_quote = time.time() - 1.0
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
        console = asyncio.create_task(ofs.follow(bus, capture.Daemon(bus, HealthRegistry(), [])))
        try:
            assert await _until(_received(t_trade))  # the trade, at its own receive time
            assert not _received(t_quote)(), "the trade was re-dated to the later bid/ask tick"
        finally:
            console.cancel()

    asyncio.run(run())
