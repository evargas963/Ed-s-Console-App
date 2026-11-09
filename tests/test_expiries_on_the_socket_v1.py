"""The expiry dropdown's list on the page's socket (/ws), end to end.

The program's real web server (server.app on uvicorn with capture.PAGES) serves /ws with the real
price server (live_ui.serve_live_ui, with server.PAGE_PANELS), and a real WebSocket client stands in
for the page over a real local socket. The levels producer (server._publish_levels) prices real
chains the daemon captured on 2026-10-07 (tests/real_chains.py: CRWD's 2026-10-16 expiry, MRVL's
full chain of 20 expiries), on a thread of its own as the pricing thread runs it. The expected
lists are worked out from the captured chains here: each expirationDate's day, and Schwab's
daysToExpiration as sent.

Proves:
  * a page subscribing on a ticker gets that ticker's list at once, with no GET (the route is
    gone);
  * a ticker with no chain yet gets an empty list with the levels' own reason, never an empty
    list alone;
  * a new chain pushes the new list only to the pages on that ticker; two pages on different
    tickers each get only their own;
  * switching ticker sends the new ticker's list at once and stops the old ticker's;
  * a page that drops and returns gets the list again on its subscribe.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture
from instrument_identity import ticker_storage_key
from option_contract import read_chain
from stream_spine import HealthRegistry, MessageBus
from tests.real_chains import CRWD, MRVL
from tests.test_live_push_channel_v1 import listener, serve_page_socket

A, B = ticker_storage_key(CRWD.ticker), ticker_storage_key(MRVL.ticker)


def _expected(chain) -> tuple[list[str], dict]:
    """Return the chain's listed expiries and each one's daysToExpiration, as Schwab sent them."""
    dte = {str(c["expirationDate"])[:10]: c["daysToExpiration"] for c in chain}
    return sorted(dte), dte


def _publish(real) -> None:
    """Price `real`'s chain as the stored capture it is, at the price Schwab sent with it."""
    server._publish_levels(
        ticker_storage_key(real.ticker),
        captures=[
            {
                "contracts": read_chain([dict(c) for c in real.chain]),
                "ts_utc": real.now.timestamp(),
                "spot": real.spot,
                "et_date": real.now.date().isoformat(),
                "basis": server.CAPTURE_BASIS,
                "spot_ts": None,
                "spot_from_chain": False,
            }
        ],
        now=real.now,
    )


def _forget() -> None:
    with server._terrain_cache_lock:
        for tk in (A, B):
            server._terrain_cache.pop(tk, None)
    lmp.record_feed_down()


@pytest.fixture(autouse=True)
def _no_levels():
    """Each test starts with neither ticker's levels published, and leaves none.

    Nor the daemon's heartbeat its beats recorded.
    """
    _forget()
    yield
    _forget()


async def _run(body) -> None:
    """Serve /ws with the daemon's own heartbeat (capture.Daemon.status); run `body` on its URL."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), [])
    sock, url = listener()
    stop, stats = asyncio.Event(), {}
    served = asyncio.create_task(
        serve_page_socket(stop, sock, {"heartbeat_fn": daemon.status, "stats": stats})
    )
    end = time_et.elapsed() + 5
    while "clients" not in stats and time_et.elapsed() < end:
        await asyncio.sleep(0.01)
    assert "clients" in stats  # serving
    try:
        await asyncio.wait_for(body(f"{url}/ws"), 30)
    finally:
        stop.set()
        await asyncio.wait_for(served, 5)


async def _subscribe(ws, ticker) -> list[dict]:
    """Subscribe the page on `ticker`; return the frames up to and including its answer.

    The answer is the `symbols` frame. Every frame the server sent before it is in the list: a
    frame the page was owed before this subscribe arrives ahead of the answer.
    """
    await ws.send(json.dumps({"op": "subscribe", "symbols": [], "ticker": ticker}))
    return await _until(ws, lambda m: m["type"] == "symbols")


async def _until(ws, pred, timeout=5.0) -> list[dict]:
    """Return every frame up to and including the first that `pred` accepts."""
    seen, end = [], time_et.elapsed() + timeout
    while time_et.elapsed() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time_et.elapsed())))
        seen.append(msg)
        if pred(msg):
            return seen
    raise AssertionError(f"no matching frame within {timeout}s: {seen}")


def _lists(frames) -> list[dict]:
    return [m for m in frames if m["type"] == "expiries"]


async def _next_list(ws) -> dict:
    return (await _until(ws, lambda m: m["type"] == "expiries"))[-1]


def _assert_lists(frame, ticker, real) -> None:
    exps, dte = _expected(real.chain)
    assert frame["ticker"] == ticker
    assert frame["expiries"] == exps and frame["dte"] == dte and frame["reason"] is None
    for e in exps:
        y, m, d = e.split("-")
        assert frame["labels"][e] == f"{m}/{d}/{y} · {dte[e]:g}DTE"


def test_a_page_gets_its_tickers_list_at_once_with_no_get():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _subscribe(ws, CRWD.ticker.lower())  # as typed: the key is the server's
            _assert_lists(await _next_list(ws), A, CRWD)

    asyncio.run(_run(body))
    assert "/api/expiries" not in {getattr(r, "path", None) for r in server.app.routes}


def test_a_ticker_with_no_chain_yet_reads_unknown_with_the_levels_reason():
    async def body(url):
        async with connect(url) as ws:
            await _subscribe(ws, CRWD.ticker)
            frame = await _next_list(ws)
            reason = server.terrain_staleness(None, A, now=time_et.now())["levels_stale_reason"]
            assert frame["ticker"] == A and frame["expiries"] == [] and frame["labels"] == {}
            assert frame["reason"] == reason and reason

    asyncio.run(_run(body))


def test_a_new_chain_reaches_only_the_pages_on_its_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b:
            await _subscribe(on_a, A)
            await _subscribe(on_b, B)
            assert (await _next_list(on_a))["expiries"] == []  # no chain of either yet
            assert (await _next_list(on_b))["expiries"] == []
            await asyncio.to_thread(_publish, CRWD)  # the pricing thread prices A's chain
            _assert_lists(await _next_list(on_a), A, CRWD)
            # nothing for B: a frame owed before B's next subscribe arrives ahead of its answer
            assert _lists(await _subscribe(on_b, B)) == []
            assert (await _next_list(on_b))["expiries"] == []  # the subscribe's own list
            await asyncio.to_thread(_publish, MRVL)
            _assert_lists(await _next_list(on_b), B, MRVL)
            assert _lists(await _subscribe(on_a, A)) == []
            _assert_lists(await _next_list(on_a), A, CRWD)

    asyncio.run(_run(body))


def test_switching_ticker_sends_the_new_list_at_once_and_stops_the_old():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _subscribe(ws, A)
            _assert_lists(await _next_list(ws), A, CRWD)
            await _subscribe(ws, B)
            _assert_lists(await _next_list(ws), B, MRVL)
            await asyncio.to_thread(_publish, CRWD)  # the ticker the page left
            assert _lists(await _subscribe(ws, B)) == []
            _assert_lists(await _next_list(ws), B, MRVL)

    asyncio.run(_run(body))


def test_a_page_that_drops_and_returns_gets_the_list_again():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _subscribe(ws, A)
            _assert_lists(await _next_list(ws), A, CRWD)
        async with connect(url) as ws:  # the page's reconnect, then its subscribe
            await _subscribe(ws, A)
            _assert_lists(await _next_list(ws), A, CRWD)

    asyncio.run(_run(body))


def test_a_page_with_no_ticker_gets_no_list():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            assert _lists(await _subscribe(ws, None)) == []
            await asyncio.to_thread(_publish, CRWD)
            assert _lists(await _subscribe(ws, None)) == []

    asyncio.run(_run(body))
