"""A page whose connection ends is sent nothing more: the beat never sends to a closed page.

Production's log, 2026-11-20 08:53:26: a page was dropped (live_ui.PageSocket), its pump's next
send found the connection gone, and the beat, holding a copy of the pages taken before it waited
on another page, then sent to it: starlette refuses every send on a socket whose send has failed
("Cannot call "send" once a close message has been sent."), and the normal end of a page was
logged as an error with its traceback (six times that day).

Real code: live_ui.LiveUiServer serving starlette WebSockets, each over its ASGI receive and send
as uvicorn hands them to starlette; a connection uvicorn has lost raises uvicorn's own
ClientDisconnected on a send and delivers websocket.disconnect on a receive. INDUCED: the order of
events, held so it is the one production met: the beat waits on one page while the other page's
connection ends and its own send finds it gone.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from starlette.websockets import WebSocket
from uvicorn.protocols.utils import ClientDisconnected

from app.market_data.schwab.streaming import live_ui
from tests.shared_helpers import until

#: a page's connection ending: no Schwab value reaches it
pytestmark = pytest.mark.no_schwab_value


class _Connection:
    """One page's connection as uvicorn serves it to starlette: its ASGI receive and send.

    Its first beat is held until `release` (`held` set while it waits); once `lose` cuts it, a
    send raises ClientDisconnected and a receive gets websocket.disconnect, as uvicorn's do.
    """

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()
        self.inbox.put_nowait({"type": "websocket.connect"})
        self.lost = False
        self.held = asyncio.Event()
        self.release = asyncio.Event()
        self.frames: list[dict] = []
        self.ws: WebSocket | None = None

    async def receive(self) -> dict:
        return await self.inbox.get()

    async def send(self, message: dict) -> None:
        if self.lost:
            raise ClientDisconnected
        if message["type"] == "websocket.send" and json.loads(message["text"])["type"] == "feed":
            self.held.set()
            await self.release.wait()
            if self.lost:
                raise ClientDisconnected
        if message["type"] == "websocket.send":
            self.frames.append(json.loads(message["text"]))

    def lose(self) -> None:
        self.lost = True
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1006})


def test_a_page_whose_connection_ends_while_the_beat_waits_is_not_sent_the_beat(caplog):
    caplog.set_level(logging.INFO, logger=live_ui.__name__)
    stats: dict[str, int] = {}
    srv = live_ui.LiveUiServer(
        lambda _now: {"apply_failures": 0, "tick_failures": 0},
        stats,
        record_heartbeat=lambda _hb: None,
        panels={},
        on_select=lambda _tk: None,
    )

    async def serve(conn: _Connection) -> None:
        conn.ws = WebSocket(
            {"type": "websocket", "path": "/ws", "headers": []}, conn.receive, conn.send
        )
        await conn.ws.accept()
        await srv.serve_client(conn.ws)

    async def go() -> None:
        conns = [_Connection(), _Connection()]
        pages = [asyncio.create_task(serve(c)) for c in conns]
        while len(srv.clients) < 2:
            await asyncio.sleep(0)
        beats = asyncio.create_task(srv.beat_loop())
        # the beat waits on the first page it sends to
        while not any(c.held.is_set() for c in conns):
            await asyncio.sleep(0.01)
        waited = next(c for c in conns if c.held.is_set())
        gone = next(c for c in conns if c is not waited)
        gone_client = next(c for c in srv.clients if c.ws is gone.ws)
        # meanwhile the other page's connection ends, and its pump's next send (a row it was
        # owed, woken first) finds it gone
        gone_client.symbols = frozenset({"SPY"})
        gone_client.pending = {"SPY"}
        gone_client.wake.set()
        gone.lose()
        page = pages[conns.index(gone)]
        await asyncio.wait_for(asyncio.shield(page), 5)
        assert gone_client not in srv.clients and stats["clients"] == 1
        # the beat goes on: the page it waited on gets it, and the page that is gone gets nothing
        waited.release.set()
        # the next beat reached it too: the beat that waited has been through every page
        await until(lambda: sum(f["type"] == "feed" for f in waited.frames) >= 2, 5)
        beats.cancel()
        waited.lose()
        await asyncio.gather(beats, *pages, return_exceptions=True)
        assert gone.frames == []

    asyncio.run(asyncio.wait_for(go(), 15))
    refused = [r for r in caplog.records if "Cannot call" in r.getMessage()]
    assert refused == [], [r.getMessage() for r in refused]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
