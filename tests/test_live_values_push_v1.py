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
    server._rounds.pop(TK, None)
    ofls.clear_all_live_state()
    no_daemon()
    push_changes.bind(None)


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
    """The next message of one of `types` (the beat, the symbols and the rows ride along)."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if msg["type"] in types:
            return msg


def _view(seq, **over):
    """A page's view as ed-core.js viewOf sends it: CRWD on Options > Gamma > Heatmap, nothing
    selected, every pan following the price, CRWD's price row shown."""
    pan = {"centre": None, "shift": 0}
    v = {"seq": seq, "ticker": "CRWD", "workspace": "options", "subview": "gamma", "view": "heatmap",
         "expiry": None, "strike": None, "strike_expiry": None, "contract": None, "scope": "auto",
         "venue": "NYSE_BOOK", "cols": 6, "book_minutes": 60, "tfs": {"chart": "1", "liquidity": "5", "desk": "5"},
         "pans": {k: dict(pan) for k in ("heatmap", "gbs", "vanna", "charm", "migration")}, "symbols": ["CRWD"]}
    v.update(over)
    return json.dumps({"op": "view", "view": v})


async def _panels(ws, names):
    """The pushed answer of each of `names` (and of any other panel pushed meanwhile), by name."""
    got = {}
    while not set(names) <= set(got):
        got.update(_by_name(await _next(ws, "panels")))
    return got


def _by_name(frame):
    """A frame's answers ({"type": "panels"}), each with the view it is for, by panel name."""
    return {p["panel"]: {**p, "seq": frame["seq"]} for p in frame["panels"]}


async def _quiet(ws, sec):
    """Every message the console sends in the next `sec` seconds."""
    out, end = [], asyncio.get_running_loop().time() + sec
    while (left := end - asyncio.get_running_loop().time()) > 0:
        try:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
        except TimeoutError:
            break
    return out


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
                    # an answer serves no age (its instants' ages are the push's labels)
                    assert m["body"] == served, f"{name} is not its route's own answer"
            # a levels publication moves both again; so does the live price (`flow`): every panel
            # with a value derived from it, each as it is ready -- but not the expiry list
            push_changes.changed(TK, push_changes.LEVELS)
            assert {"gamma.surface", "gamma.terrain"} <= set(await _panels(ws, ["gamma.surface", "gamma.terrain"]))
            await _quiet(ws, 0.5)
            push_changes.changed(TK, push_changes.FLOW)
            pushed = {}
            for m in await _quiet(ws, 2.0):
                if m["type"] == "panels":
                    pushed.update(_by_name(m))
            assert {"gamma.surface", "gamma.terrain", "gamma.strikes", "gamma.tape"} <= set(pushed)
            assert "expiries" not in pushed
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
                if m["type"] == "panels":
                    after.update(_by_name(m))
            assert after["chain"]["seq"] == 2
            assert set(after) <= {"chain", "expiries", "watchlist"}, f"a panel off screen was pushed: {sorted(after)}"
    _console(body)


def test_each_panel_is_pushed_when_its_value_is_ready_never_waiting_for_another(published):
    """Ed, design A item 1: panels don't wait for each other. The Desk's event queue is held
    unanswered (2026-09-29 14:52 CT, deployed: it took 1.34 s while the levels took 28 ms) -- its
    producer waits on the level crosses, held by a cross being recorded (server._crosses_lock):
    every other Desk panel arrives meanwhile, and the queue when it is ready."""
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as ws:
            server._crosses_lock.acquire()
            try:
                await ws.send(_view(1, workspace="trade-desk", subview="desk", view=""))
                ack = await _next(ws, "view")
                got = await _panels(ws, [n for n in ack["moved"] if n != "desk.events"])
                assert "desk.levels" in got and "desk.events" not in got
            finally:
                server._crosses_lock.release()
            assert "desk.events" in await _panels(ws, ["desk.events"])
    _console(body)


class _Page:
    """The page's end of /api/live, for server.live_values called directly (STAND-IN, named: the
    transport only -- what the page sends and what it is sent)."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        await self.sent.put(json.loads(text))

    async def iter_text(self):
        while (m := await self.inbox.get()) is not None:
            yield m

    async def next(self, kind: str) -> dict:
        while (m := await asyncio.wait_for(self.sent.get(), 10))["type"] != kind:
            pass
        return m


def _row(symbol: str, now: float) -> dict:
    """`symbol`'s price row at `now`, read in its current change's round (as every panel of the
    change reads its spot)."""
    _change, rnd = server._round(symbol)
    token = server._ROUND.set(rnd)
    try:
        return server.price_row(symbol, now)
    finally:
        server._ROUND.reset(token)


def test_a_change_no_page_shows_begins_a_new_round(published):
    """Every change is counted, shown or not: a round is current only until the next change of its
    symbol. A new trade while no page shows CRWD, then a page: it reads the new trade, never the
    old round's."""
    import time

    async def go():
        push_changes.bind(asyncio.get_running_loop())
        daemon_holds(time.time(), {"LEVELONE_EQUITIES": [TK]})
        _change, rnd = server._round(TK)
        assert _row(TK, time.time())["spot"] == CRWD.spot
        price_sent(TK, CRWD.spot + 2.0, time.time())
        assert _row(TK, time.time())["spot"] == CRWD.spot, "a round reads its quote once"
        push_changes.changed(TK, push_changes.FLOW)            # no page is open on CRWD
        await asyncio.sleep(0.05)
        assert server._round(TK)[1] is not rnd
        assert _row(TK, time.time())["spot"] == CRWD.spot + 2.0
    try:
        asyncio.run(go())
    finally:
        server._rounds.pop(TK, None)


def test_a_heartbeat_received_after_a_round_began_reads_live(published):
    """The clock is read fresh, never pinned to the round: the daemon's heartbeat received after
    a round began (its receive time after the round's start) is live in that round."""
    import time

    _change, rnd = server._round(TK)
    time.sleep(0.05)
    daemon_holds(time.time(), {"LEVELONE_EQUITIES": [TK]})
    try:
        assert server._round(TK)[1] is rnd
        assert _row(TK, time.time())["feed_live"] is True
    finally:
        server._rounds.pop(TK, None)


def test_a_symbol_a_page_begins_to_show_is_not_pushed_again_by_the_next_liveness_pass(published):
    """The console's feed loop marks a shown symbol whose feed verdict changed
    (streaming._mark_liveness). A symbol first shown was marked on that pass, unchanged: every
    panel of the ticker was computed and pushed again about a second after the page chose it
    (the full suite's ticker-switch test caught AAPL's flow panels read after the switch). Its
    verdict is taken as its first answers read it, so only a real change is marked."""
    import time

    from app.options.order_flow import streaming as ofs

    async def go():
        push_changes.bind(asyncio.get_running_loop())
        daemon_holds(time.time(), {"LEVELONE_EQUITIES": [TK]})
        ofs._verdicts.clear()                           # no page has shown CRWD
        page = _Page()
        console = asyncio.create_task(server.live_values(page))
        try:
            await page.inbox.put(_view(1))
            await page.next("view")
            before = push_changes.generation(TK, {push_changes.FLOW})
            ofs._mark_liveness(time.time())
            await asyncio.sleep(0.05)
            assert push_changes.generation(TK, {push_changes.FLOW}) == before
        finally:
            await page.inbox.put(None)
            await asyncio.wait_for(console, 10)
            ofs._verdicts.clear()
    asyncio.run(go())


def test_a_value_read_from_the_price_stands_marked_not_live_when_the_feed_goes_down(published):
    """Operator 2026-10-14: "During a Schwab outage in an open session, the last values stand,
    marked not live, on the header and every derived value, from the one liveness judgment." The
    heatmap with CRWD's feed live carries no mark (the expiry list, read from no price, never
    does); the feed goes down: the console's liveness pass pushes it again with its last spot,
    marked with the one judgment's reason (live_market_plane.outage). Before, the spot was blanked
    and nothing said why."""
    import time

    import live_market_plane as lmp
    from app.options.order_flow import streaming as ofs
    from time_et import now_et, session_label

    async def go():
        push_changes.bind(asyncio.get_running_loop())
        daemon_holds(time.time(), {"LEVELONE_EQUITIES": [TK]})
        price_sent(TK, CRWD.spot, time.time())
        ofs._verdicts.clear()
        page = _Page()
        console = asyncio.create_task(server.live_values(page))
        try:
            await page.inbox.put(_view(1))
            got: dict = {}
            while not {"gamma.surface", "expiries"} <= set(got):
                got.update(_by_name(await page.next("panels")))
            assert got["gamma.surface"]["not_live"] is None and got["expiries"]["not_live"] is None
            lmp.record_feed_down()                          # the daemon's feed is gone
            ofs._mark_liveness(time.time())
            while "gamma.surface" not in (frame := _by_name(await page.next("panels"))):
                pass
            marked = frame["gamma.surface"]
            outage = lmp.outage(TK, "LEVELONE_EQUITIES", time.time())
            assert marked["not_live"] == (None if outage is None else [outage])
            if session_label(now_et()) != "Closed":
                assert marked["not_live"] is not None
            assert marked["body"]["spot"] == CRWD.spot, "the last spot stands"
        finally:
            await page.inbox.put(None)
            await asyncio.wait_for(console, 10)
            ofs._verdicts.clear()
    asyncio.run(go())


def test_a_value_read_from_a_book_is_marked_by_its_own_feed(published):
    """Operator 2026-10-14: "every derived value". The Order Flow heatmap is read from CRWD's
    NYSE_BOOK, which the daemon does not hold: its frame is marked by that feed's one judgment
    (not the price's, which is live); the expiry list, read from no feed, is never marked."""
    import time

    import live_market_plane as lmp
    from time_et import now_et, session_label

    async def go():
        push_changes.bind(asyncio.get_running_loop())
        daemon_holds(time.time(), {"LEVELONE_EQUITIES": [TK]})
        price_sent(TK, CRWD.spot, time.time())
        page = _Page()
        console = asyncio.create_task(server.live_values(page))
        try:
            await page.inbox.put(_view(1, workspace="order-flow", subview="heatmap", view=""))
            got: dict = {}
            while not {"book.heatmap", "expiries"} <= set(got):
                got.update(_by_name(await page.next("panels")))
            now = time.time()
            outage = lmp.outage(TK, "NYSE_BOOK", now)
            assert got["book.heatmap"]["not_live"] == (None if outage is None else [outage])
            if session_label(now_et()) != "Closed":
                assert "NYSE_BOOK" in got["book.heatmap"]["not_live"][0]
            assert lmp.outage(TK, "LEVELONE_EQUITIES", now) is None and got["expiries"]["not_live"] is None
        finally:
            await page.inbox.put(None)
            await asyncio.wait_for(console, 10)
    asyncio.run(go())
