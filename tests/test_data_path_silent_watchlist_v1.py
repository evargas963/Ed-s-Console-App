"""Schwab -> the watchlist on the page's socket. Each beat carries the daemon's list; a beat with
no status keeps the last list on the page, which then says the daemon is not reporting
(tests/e2e/console-watchlist-socket.spec.js).
"""

from __future__ import annotations

import asyncio
import json

from websockets.asyncio.client import connect

import live_market_plane as lmp
from app.market_data.schwab.streaming import capture
from stream_spine import HealthRegistry, MessageBus
from tests.test_live_push_channel_v1 import listener, serve_page_socket


def test_a_missing_heartbeat_keeps_the_last_watchlist():
    """The daemon holds SPY and TSLA: the page's socket carries them on a beat, as the daemon's
    own status. Then the daemon's status fails (induced: the status raises), and the next beat
    carries no status at all, never a list of its own.
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "TSLA"])
    failing = False

    def status(now: float) -> dict:
        if failing:
            raise RuntimeError("induced: the daemon's status failed")
        return daemon.status(now)

    async def beat(ws) -> dict:
        while (msg := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "feed":
            pass
        return msg

    async def go():
        nonlocal failing
        sock, url = listener()
        stop, stats = asyncio.Event(), {}
        served = asyncio.create_task(
            serve_page_socket(stop, sock, {"heartbeat_fn": status, "stats": stats})
        )
        try:
            while "clients" not in stats:
                await asyncio.sleep(0.01)
            async with connect(f"{url}/ws") as ws:
                live = await beat(ws)
                failing = True
                down = await beat(ws)
                while down["feed"] is not None:  # a beat already made before the failure
                    down = await beat(ws)
        finally:
            stop.set()
            await asyncio.wait_for(served, 5)
        return live, down

    try:
        live, down = asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        lmp.record_feed_down()
        with lmp._lock:
            lmp._feed["status"] = None
    assert live["feed"]["watchlist"] == ["SPY", "TSLA"] and live["feed"]["ts"] is not None
    assert down["feed"] is None
