"""Pages on the program's socket server, as a browser's subscribe leaves them (live_ui)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import server
from app.market_data.schwab.streaming.live_ui import LiveUiServer, _Client


class Pages:
    """The program's socket server (live_ui.LiveUiServer) and the pages a test opens on it.

    Served from the program's app state (server.app.state.prices) until `stop`.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.server = LiveUiServer(
            lambda _now: {}, {}, panels=server.PAGE_PANELS, priced=server.PRICED_PANELS
        )
        self.server.loop = self.loop
        self.before = server.app.state.prices
        server.app.state.prices = self.server

    def stop(self) -> None:
        """Close every page and stop serving."""
        server.app.state.prices = self.before
        self.loop.close()

    def open(self, ticker: str, *panels: str) -> _Client:
        """Open a page with `ticker` (its key) selected, showing `panels`."""
        page = _Client(None)
        page.ticker = ticker
        page.shown = {name: {} for name in panels}
        self.server.clients.add(page)
        return page

    def close(self, page: _Client) -> None:
        """Close `page`."""
        self.server.clients.discard(page)

    def told(self, page: _Client, within: float = 0.0) -> set[str]:
        """Return the panels marked changed for `page` since the last call.

        The marks made so far, from any thread, and those that arrive up to `within` seconds
        later while there are none.
        """

        async def marks() -> None:
            end = self.loop.time() + within
            await asyncio.sleep(0)
            while not page.panels and self.loop.time() < end:
                await asyncio.sleep(0.01)

        self.loop.run_until_complete(marks())
        told = set(page.panels)
        page.panels.clear()
        return told


@contextmanager
def pages() -> Iterator[Pages]:
    """Serve pages for the block."""
    served = Pages()
    try:
        yield served
    finally:
        served.stop()
