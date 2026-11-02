"""The one program: the console with the capture daemon's tasks on its event loop.

    python -m uvicorn program:app  (launch.py)

The console's own start and stop run around them (server._app_lifespan). A stop ends the daemon
first: its writer writes what it holds, and only then does the event loop end.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import server
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from app.options.order_flow import streaming
from app.options.order_flow.streaming import follow


def _status(now: float) -> dict | None:
    """The daemon's status at `now`; none between its runs, when the page's feed goes OFFLINE."""
    return None if streaming._daemon is None else streaming._daemon.status(now)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with server._app_lifespan(app):
        capture.start_log()
        fd, lock = capture.acquire_owner_lock()
        stop = asyncio.Event()
        page = asyncio.create_task(serve_live_ui(stop, heartbeat_fn=_status), name="page socket")
        daemon = asyncio.create_task(capture.keep_running(stop, follow), name="capture daemon")
        daemon.add_done_callback(lambda _: capture.release_owner_lock(fd, lock))

        def stop_daemon_first() -> None:
            stop.set()
            daemon.add_done_callback(lambda _: server.interrupt())

        loop = asyncio.get_running_loop()
        server.on_stop = lambda: loop.call_soon_threadsafe(stop_daemon_first)
        yield
        stop.set()
        await daemon
        await page


app = server.app
app.router.lifespan_context = _lifespan
