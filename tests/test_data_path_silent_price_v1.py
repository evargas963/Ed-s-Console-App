"""Schwab -> the console's price row. A silent daemon keeps the last price and reads down."""

from __future__ import annotations

import asyncio
import time

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.market_data.schwab.streaming import live_ui
from tests.test_live_push_channel_v1 import _run, _spy_trade, _until, feed as feed


def test_a_silent_daemon_keeps_the_last_price(feed):
    """The daemon's price push goes quiet between beats. The last price stays, and the feed is
    not live while the beat is missing."""
    age, beat = lmp.FEED_HEARTBEAT_MAX_AGE_SEC, live_ui.HEARTBEAT_SEC
    lmp.FEED_HEARTBEAT_MAX_AGE_SEC = 0.15
    live_ui.HEARTBEAT_SEC = 0.4
    missing: list = []
    quiet: list = []

    async def body(bus, stats):
        assert await _until(lambda: stats["clients"] == 1)
        bus.publish("quote.SPY", _spy_trade(501.0, time.time()))
        assert await _until(lambda: (ofs.price_row("SPY") or {}).get("spot") == 501.0)
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            row = ofs.price_row("SPY")
            if row is None or row.get("spot") != 501.0:
                missing.append(row)
            if not lmp.feed_live_for("SPY", "LEVELONE_EQUITIES", time.time()):
                quiet.append(True)
            await asyncio.sleep(0.02)

    try:
        asyncio.run(_run(body))
    finally:
        lmp.FEED_HEARTBEAT_MAX_AGE_SEC = age
        live_ui.HEARTBEAT_SEC = beat
    assert missing == []
    assert quiet
