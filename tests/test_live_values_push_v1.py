"""The console's push to the page (/api/live, server.live_values), through the real app served by
uvicorn over a real WebSocket: the page names its ticker and each route a panel shows; the console
sends each route's answer at once -- the route's own answer, the one its GET serves -- and again
when a kind of change that moves it happens, then the kind; a route a panel stops showing is
pushed no more. The page fetches nothing.

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py), its
levels published at its capture. STAND-IN (named): the daemon's status and CRWD's last trade at the
capture (tests/feed_live_helper.py).
"""
from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect

import app.options.order_flow.state as ofls
import push_changes
import server
from tests.feed_live_helper import daemon_holds, forget_price, ledger_round, no_daemon, price_sent
from tests.real_chains import CRWD

TK = server.ticker_storage_key("CRWD")
_AT = CRWD.now
SURFACE = f"/api/options/gamma-surface?ticker={TK}"
TERRAIN = f"/api/terrain?ticker={TK}"


@pytest.fixture
def published():
    """CRWD's levels published from its real chain, at its capture (no event loop bound yet: the
    app binds its own when it starts)."""
    push_changes.bind(None)
    daemon_holds(_AT.timestamp(), {"LEVELONE_EQUITIES": [TK]})
    price_sent(TK, CRWD.spot, _AT.timestamp())
    ledger_round(TK, CRWD.chain, _AT.timestamp(), now=_AT)
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    forget_price(TK)
    ofls.clear_all_live_state()
    no_daemon()
    push_changes.bind(None)


def _at_answer_time(body):
    """`body` but each age it serves (`*age_sec`: seconds from a value's time to the answer's time,
    so two answers a moment apart differ there and only there)."""
    if isinstance(body, dict):
        return {k: _at_answer_time(v) for k, v in body.items() if not k.endswith("age_sec")}
    if isinstance(body, list):
        return [_at_answer_time(v) for v in body]
    return body


def _console(body) -> None:
    """The console's app served by uvicorn on a free port, `body(base_url)` run against it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def go():
        srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(srv.serve())
        while not srv.started:
            await asyncio.sleep(0.02)
        try:
            await body(f"127.0.0.1:{port}")
        finally:
            srv.should_exit = True
            await asyncio.wait_for(task, 30)
    asyncio.run(go())


async def _next(ws, *types):
    """The next message of one of `types` (the session label rides along with the rest)."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if msg["type"] in types:
            return msg


def test_each_route_is_answered_with_its_own_answer_and_again_on_a_change_that_moves_it(published):
    async def body(host):
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            served = {url: (await http.get(url)).json() for url in (SURFACE, TERRAIN)}
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(json.dumps({"op": "ticker", "ticker": "CRWD"}))
            assert (await _next(ws, "session"))["label"]
            for url in (SURFACE, TERRAIN):
                await ws.send(json.dumps({"op": "route", "url": url}))
                answer = await _next(ws, "route")
                assert (answer["url"], answer["status"]) == (url, 200)
                assert _at_answer_time(answer["body"]) == _at_answer_time(served[url]), \
                    "the push is not the route's own answer"
            # a levels publication moves both: each answered again, then the kind
            push_changes.changed(TK, push_changes.LEVELS)
            again = {(await _next(ws, "route"))["url"], (await _next(ws, "route"))["url"]}
            assert again == {SURFACE, TERRAIN}
            assert await _next(ws, "changed", "route") == {"type": "changed", "kind": "levels"}
            # the books move the terrain (it serves the live price) but not the gamma surface
            push_changes.changed(TK, push_changes.FLOW)
            moved = await _next(ws, "route", "changed")
            assert moved["type"] == "route" and moved["url"] == TERRAIN
            assert await _next(ws, "changed", "route") == {"type": "changed", "kind": "flow"}
    _console(body)


def test_a_route_a_panel_stops_showing_is_pushed_no_more(published):
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(json.dumps({"op": "ticker", "ticker": "CRWD"}))
            await ws.send(json.dumps({"op": "route", "url": SURFACE}))
            assert (await _next(ws, "route"))["url"] == SURFACE
            await ws.send(json.dumps({"op": "drop", "url": SURFACE}))
            await ws.send(json.dumps({"op": "route", "url": TERRAIN}))      # the drop is read before this
            assert (await _next(ws, "route"))["url"] == TERRAIN
            push_changes.changed(TK, push_changes.LEVELS)
            assert (await _next(ws, "route", "changed"))["url"] == TERRAIN
            assert await _next(ws, "changed", "route") == {"type": "changed", "kind": "levels"}
    _console(body)


def test_only_the_consoles_own_get_routes_are_answered():
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(json.dumps({"op": "ticker", "ticker": "CRWD"}))
            for url in ("/api/live", "http://elsewhere.example/api/terrain", "/static/index.html"):
                await ws.send(json.dumps({"op": "route", "url": url}))
                answer = await _next(ws, "route")
                assert (answer["status"], answer["body"]) == (404, None), url
    _console(body)
