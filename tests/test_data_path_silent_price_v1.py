"""Schwab -> the console's price row. A silent daemon keeps the last price and reads down."""

from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.client import connect

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import time_et
from app.market_data.schwab.streaming import live_ui
from tests.test_live_push_channel_v1 import (
    _daemon_heartbeat,
    _run,
    _spy_trade,
    _until,
    listener,
)
from tests.test_live_push_channel_v1 import (
    feed as feed,
)


def test_a_page_frame_the_daemon_cannot_read_is_logged_with_what_arrived(caplog):
    """The daemon's price socket reads every page frame: one that is not JSON, one that is not a
    subscribe request with a list of symbols, and a symbol in it that is not a string, or is blank,
    are each logged with what arrived (its first 200 characters), never dropped unseen.
    """

    async def go():
        stop, stats = asyncio.Event(), {}
        sock, url = listener()
        ui = asyncio.create_task(
            live_ui.serve_live_ui(
                stop,
                sock,
                heartbeat_fn=_daemon_heartbeat(),
                stats=stats,
                record_heartbeat=lambda _beat: None,
            )
        )
        assert await _until(lambda: "clients" in stats)  # serving
        ws = await connect(url, max_size=None)
        try:
            for frame in (
                "not json",
                '{"op": "hello"}',
                json.dumps({"op": "subscribe", "symbols": [7]}),
            ):
                await ws.send(frame)
            await _until(
                lambda: len([r for r in caplog.records if r.name.endswith("live_ui")]) >= 3
            )
        finally:  # a failure still closes the socket: cancelling over an open one can hang
            await ws.close()
            stop.set()
            await ui

    with caplog.at_level(logging.WARNING, logger="app.market_data.schwab.streaming.live_ui"):
        asyncio.run(go())
    warned = " | ".join(r.getMessage() for r in caplog.records if r.name.endswith("live_ui"))
    assert "'not json'" in warned and '\'{"op": "hello"}\'' in warned, warned
    assert "a subscribed symbol not a string, or blank: 7" in warned, warned


def test_a_silent_daemon_keeps_the_last_price(feed):
    """The daemon's price push goes quiet between beats. The last price stays, and the feed is
    not live while the beat is missing.
    """
    age, beat = lmp.FEED_HEARTBEAT_MAX_AGE_SEC, live_ui.HEARTBEAT_SEC
    lmp.FEED_HEARTBEAT_MAX_AGE_SEC = 0.15
    live_ui.HEARTBEAT_SEC = 0.4
    missing: list = []
    quiet: list = []

    async def body(bus, stats):
        assert stats["clients"] == 0  # the console reads the bus: no socket client
        bus.publish("quote.SPY", _spy_trade(501.0, time_et.now()))
        assert await _until(lambda: ofs.price_row("SPY", time_et.now())["spot"] == 501.0)
        end = time_et.elapsed() + 1.2
        while time_et.elapsed() < end:
            row = ofs.price_row("SPY", time_et.now())
            if row["spot"] != 501.0:
                missing.append(row)
            if not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time_et.now()):
                quiet.append(True)
            await asyncio.sleep(0.02)

    try:
        asyncio.run(_run(body))
    finally:
        lmp.FEED_HEARTBEAT_MAX_AGE_SEC = age
        live_ui.HEARTBEAT_SEC = beat
    assert missing == []
    assert quiet
