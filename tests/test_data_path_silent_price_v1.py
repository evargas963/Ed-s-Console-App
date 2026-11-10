"""Schwab -> the console's price row. A silent daemon keeps the last price and reads down."""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import pytest
from websockets.asyncio.client import connect

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import live_ui
from tests.test_live_push_channel_v1 import (
    _daemon_heartbeat,
    _run,
    _spy_trade,
    _until,
    listener,
    serve_page_socket,
)


def test_a_page_frame_the_daemon_cannot_read_is_logged_with_what_arrived(caplog):
    """The daemon's price socket reads every page frame.

    One that is not JSON (text or binary), one that is not a subscribe request with a list of
    symbols, and a symbol in it that is not a string, or is blank, are each logged with what
    arrived (its first 200 characters), never dropped unseen, and the page is still served.
    """

    async def go():
        stop, stats = asyncio.Event(), {}
        sock, url = listener()
        ui = asyncio.create_task(
            serve_page_socket(
                stop,
                sock,
                {
                    "heartbeat_fn": _daemon_heartbeat(),
                    "stats": stats,
                    "record_heartbeat": lambda _beat: None,
                },
            )
        )
        assert await _until(lambda: "clients" in stats)  # serving
        ws = await connect(f"{url}/ws", max_size=None)
        try:
            for frame in (
                "not json",
                '{"op": "hello"}',
                json.dumps({"op": "subscribe", "symbols": [7]}),
                b"\xff not text",
            ):
                await ws.send(frame)
            await _until(
                lambda: len([r for r in caplog.records if r.name.endswith("live_ui")]) >= 4
            )
            # the socket still serves the page after them
            await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
            assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "symbols"
        finally:  # a failure still closes the socket: cancelling over an open one can hang
            await ws.close()
            stop.set()
            await ui

    with caplog.at_level(logging.WARNING, logger="app.market_data.schwab.streaming.live_ui"):
        asyncio.run(go())
    warned = " | ".join(r.getMessage() for r in caplog.records if r.name.endswith("live_ui"))
    assert "'not json'" in warned and '\'{"op": "hello"}\'' in warned, warned
    assert "a subscribed symbol not a string, or blank: 7" in warned, warned
    assert "b'\\xff not text'" in warned, warned  # a binary frame, read as what it carries


def test_a_page_selecting_a_ticker_queues_its_reprice_and_its_ticks_end_with_the_page():
    """A page's own subscribe -> the pricing queue, on the program's page socket.

    The page selects SPY: one reprice of SPY waits, and still one after a tick of SPY and after
    the page sends the same subscribe again. Once the page has closed, a tick of SPY queues
    nothing (the pricing thread held throughout, the queue read as it stands).
    """
    select = json.dumps({"op": "subscribe", "symbols": ["SPY"], "ticker": "SPY", "panels": {}})
    seen: list[dict] = []

    def waiting() -> dict:
        with server._chains_waiting_lock:
            return dict(server._chains_waiting)

    async def go():
        stop, stats = asyncio.Event(), {}
        sock, url = listener()
        ui = asyncio.create_task(
            serve_page_socket(
                stop,
                sock,
                {
                    "heartbeat_fn": _daemon_heartbeat(),
                    "stats": stats,
                    "record_heartbeat": lambda _beat: None,
                },
            )
        )
        assert await _until(lambda: "clients" in stats)  # serving
        ws = await connect(f"{url}/ws", max_size=None)
        try:
            for _ in range(2):
                await ws.send(select)
                while json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] != "symbols":
                    pass  # the frame that answers the subscribe: it has been taken
                server._on_stream_tick("SPY")
                seen.append(waiting())
        finally:  # a failure still closes the socket: cancelling over an open one can hang
            await ws.close()
        assert await _until(lambda: "SPY" not in live_ui.selected(server.app.state))
        with server._chains_waiting_lock:
            server._chains_waiting.pop("SPY")
        server._on_stream_tick("SPY")
        seen.append(waiting())
        stop.set()
        await ui

    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 30)
    try:
        asyncio.run(go())
    finally:
        gate.set()
        server._chain_pricing.submit(lambda: None).result(timeout=30)
    job = {"SPY": (server.REPRICE, None, None, None)}
    assert seen == [job, job, {}]


@pytest.mark.usefixtures("feed")
def test_a_silent_daemon_keeps_the_last_price():
    """The daemon's price push goes quiet between beats.

    The last price stays, and the feed is not live while the beat is missing. The row and the
    feed are read at the time asked (`now`): now, with a beat just taken, and once the last beat
    is past the live limit with no beat after it.
    """
    missing: list = []
    quiet: list = []

    async def body(bus, web):
        assert not web.server_state.connections  # the console reads the bus: no socket client
        bus.publish("quote.SPY", _spy_trade(501.0, time_et.now()))
        assert await _until(lambda: ofs.price_row("SPY", time_et.now())["spot"] == 501.0)
        assert await _until(lambda: lmp.daemon_status(time_et.now()) is not None)  # a beat taken
        now = time_et.now()
        for at in (now, now + lmp.FEED_HEARTBEAT_MAX_AGE_SEC + live_ui.HEARTBEAT_SEC):
            row = ofs.price_row("SPY", at)
            if row["spot"] != 501.0:
                missing.append(row)
            if not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", at):
                quiet.append(at)

    asyncio.run(_run(body))
    assert missing == []
    assert quiet
