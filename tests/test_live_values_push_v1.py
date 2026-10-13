"""The console's push to the page (/api/live, server.live_values), through the real app served by
uvicorn over a real WebSocket: the page sends its view (the operator's selections) and names no
route; the console pushes each panel on screen by name -- its route's own answer, the one its GET
serves -- and again when a kind of change that moves it happens. A value two panels or two pages
show is one computation; an answer the view moved on from is never sent.

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


def _view(seq, **over):
    """A page's view as ed-core.js viewOf sends it: CRWD on Options > Gamma > Heatmap, nothing
    selected, every pan following the price."""
    pan = {"centre": None, "shift": 0}
    v = {"seq": seq, "ticker": "CRWD", "workspace": "options", "subview": "gamma", "view": "heatmap",
         "expiry": None, "strike": None, "strike_expiry": None, "contract": None, "scope": "auto",
         "venue": "NYSE_BOOK", "cols": 6, "book_minutes": 60, "tfs": {"chart": "1", "liquidity": "5", "desk": "5"},
         "pans": {k: dict(pan) for k in ("heatmap", "gbs", "vanna", "charm", "migration")}}
    v.update(over)
    return json.dumps({"op": "view", "view": v})


async def _panels(ws, names):
    """The pushed answer of each of `names` (and of any other panel pushed meanwhile), by name."""
    got = {}
    while not set(names) <= set(got):
        msg = await _next(ws, "panel")
        got[msg["panel"]] = msg
    return got


def test_the_view_gets_each_panel_on_screen_with_its_routes_own_answer_and_again_on_a_change_that_moves_it(published):
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(_view(1))
            ack = await _next(ws, "view")
            assert ack["seq"] == 1 and {"gamma.surface", "gamma.terrain", "gamma.strikes", "gamma.tape"} <= set(ack["moved"])
            assert "chain" not in ack["moved"], "a panel not on screen is pushed"
            got = await _panels(ws, ack["moved"])
            async with httpx.AsyncClient(base_url=f"http://{host}") as http:
                for name in ("gamma.surface", "gamma.terrain"):
                    m = got[name]
                    assert (m["seq"], m["status"]) == (1, 200)
                    served = (await http.get(m["source"])).json()
                    assert _at_answer_time(m["body"]) == _at_answer_time(served), f"{name} is not its route's own answer"
            # a levels publication moves both again; the books move the terrain (it serves the
            # live price) but not the gamma surface
            push_changes.changed(TK, push_changes.LEVELS)
            assert {"gamma.surface", "gamma.terrain"} <= set(await _panels(ws, ["gamma.surface", "gamma.terrain"]))
            push_changes.changed(TK, push_changes.FLOW)
            moved = await _panels(ws, ["gamma.terrain"])
            assert "gamma.surface" not in moved
    _console(body)


def test_a_value_two_panels_or_two_pages_show_is_one_computation(published):
    """Key Levels and the Gamma chart both show the terrain (the call wall, the flip): one route
    answer, computed once, the same to the digit -- its ages included, which differ between two
    computations a moment apart -- on two panels of two pages."""
    async def body(host):
        chart = _view(1, view="chart")
        async with connect(f"ws://{host}/api/live", max_size=None) as a, connect(f"ws://{host}/api/live", max_size=None) as b:
            await a.send(chart)
            first = await _panels(a, (await _next(a, "view"))["moved"])
            await asyncio.sleep(1.1)              # a second computation would serve other ages
            await b.send(chart)
            second = await _panels(b, (await _next(b, "view"))["moved"])
            kl, ch = first["gamma.terrain"], first["gamma.chart.terrain"]
            assert kl["source"] == ch["source"] == TERRAIN
            assert kl["body"] == ch["body"] == second["gamma.terrain"]["body"] == second["gamma.chart.terrain"]["body"]
            assert [u for u in server._answers if u == TERRAIN] == [TERRAIN], "the terrain is held once"
    _console(body)


def test_a_route_that_raises_is_its_panels_500_and_the_push_goes_on(published):
    """The Desk's event route raises while Schwab's /markets has sent no session (its window starts
    at the session's open): that panel is answered 500, every other panel of the view still
    arrives, and the same connection takes the next view. Before, the route's error ended the
    connection: the page reconnected, sent its view again, and the Desk never drew."""
    import time_et

    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(_view(1, workspace="trade-desk", subview="desk", view=""))
            ack = await _next(ws, "view")
            got = await _panels(ws, ack["moved"])
            assert {"desk.bars", "desk.levels", "desk.events", "desk.terrain", "desk.zones", "desk.strikes",
                    "desk.forces", "desk.flow_bars", "desk.book"} <= set(got)
            if time_et.last_open(time_et.now_et()) is None:      # no session held: the route raised
                assert (got["desk.events"]["status"], got["desk.events"]["body"]) == (500, None)
            await ws.send(_view(2, workspace="trade-desk", subview="desk", view="", tfs={"chart": "1", "liquidity": "5", "desk": "15"}))
            again = await _next(ws, "view")
            assert again["seq"] == 2 and set(again["moved"]) == {"desk.bars", "desk.levels", "desk.events"}
    _console(body)


def test_an_answer_the_view_moved_on_from_is_never_sent(published):
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            await ws.send(_view(1))
            await ws.send(_view(2, subview="chain"))       # before the heatmap's answers can land
            while (msg := json.loads(await asyncio.wait_for(ws.recv(), 10)))["type"] != "view" or msg["seq"] != 2:
                pass
            assert "chain" in msg["moved"] and not any(n.startswith("gamma.") for n in msg["moved"])
            push_changes.changed(TK, push_changes.LEVELS)   # moves the heatmap's surface too
            after = await _panels(ws, ["chain"])
            await asyncio.sleep(1)                          # and whatever else would come
            while True:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.2))
                except TimeoutError:
                    break
                if m["type"] == "panel":
                    after[m["panel"]] = m
            assert after["chain"]["seq"] == 2
            assert set(after) <= {"chain", "expiries", "watchlist"}, f"a panel off screen was pushed: {sorted(after)}"
    _console(body)
