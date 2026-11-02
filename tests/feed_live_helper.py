"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

import live_market_plane as lmp
from app.market_data.schwab.streaming import live_ui

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@contextlib.asynccontextmanager
async def page_socket():
    """The page's socket on a real server, as the program serves it (/ws); its address."""
    app = FastAPI()
    app.add_api_websocket_route("/ws", live_ui.page_socket)
    config = uvicorn.Config(
        app, log_level="warning", ws_per_message_deflate=False, timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    listening = socket.create_server(("127.0.0.1", 0))
    serving = asyncio.create_task(server.serve([listening]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        yield f"ws://127.0.0.1:{listening.getsockname()[1]}/ws"
    finally:
        server.should_exit = True
        await serving


async def takes_a_beat(page) -> None:
    """`page` reads frames until the daemon's beat comes."""
    async for frame in page:
        if json.loads(frame)["type"] == "feed":
            return


async def reads_to_the_close(page) -> None:
    """`page` reads everything still on its way, until its connection closes."""
    try:
        while True:
            await page.recv()
    except ConnectionClosed:
        return


async def refused(url: str) -> bool:
    """Whether the socket at `url` refuses a page's handshake."""
    try:
        async with connect(url):
            return False
    except InvalidStatus:
        return True


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """The capture daemon's recorded receipts of Schwab's CHART_EQUITY bars in fixture `name`
    (tests/fixtures/real_daemon_bars_*.json), of `symbols` (every symbol when none is named)."""
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def stream_daemon_bars(rows: list[dict]) -> None:
    """What the capture daemon pushes of Schwab's bars: each captured receipt, in the order the
    daemon received them, through the console's own streamed-bar writer
    (server._write_streamed_bar), so each minute holds Schwab's newest bar for it."""
    import server

    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        server._write_streamed_bar(r)


def price_history(symbol: str, series: str) -> dict:
    """Schwab's captured /pricehistory answer for `symbol`'s `series` ("1m", "15m", "1d")
    (tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json): {params, status, date, sent_utc,
    answered_utc, body}."""
    fx = json.loads(
        (_FIXTURES / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8")
    )
    return next(a for a in fx["answers"] if a["symbol"] == symbol and a["series"] == series)


#: Wednesday 2026-09-30, 11:00 ET: regular hours in Schwab's /markets answer held for that date
#: (tests/conftest.py MARKETS_ANSWERS), the instant a live-feed test is judged at, whatever day it
#: runs
RTH_INSTANT = 1790780400.0


def clock_from(start: float):
    """A clock running from `start`, time still passing: what a test hands the code it calls as
    `now`."""
    began = time.monotonic()
    return lambda: start + time.monotonic() - began


def mark_feed_live(*tickers: str, now: float | None = None) -> None:
    """The daemon's heartbeat stamped `now` (the wall clock when not given), holding `tickers` on
    LEVELONE_EQUITIES."""
    lmp.record_feed_heartbeat(
        {
            "ts": time.time() if now is None else now,
            "schwab_socket_open": True,
            "held": {"LEVELONE_EQUITIES": list(tickers)},
        }
    )


def mark_feed_down() -> None:
    lmp.record_feed_down()


def hold_price(ticker: str, price: float, trade_ts: float) -> None:
    """Schwab's LEVELONE_EQUITIES last trade of `ticker`, received at its trade time, in the plane
    every price is read from."""
    item = {"LAST_PRICE": price, "TRADE_TIME_MILLIS": int(trade_ts * 1000)}
    lmp.record_from_level_one_equity(ticker, item, received_ts=trade_ts)


def forget_price(ticker: str) -> None:
    """The plane holds nothing of `ticker`."""
    lmp._by_ticker.pop(ticker, None)
    lmp._fields_by_ticker.pop(ticker, None)


def feed_live_during(monkeypatch, *tickers: str) -> None:
    """For route tests that start the app (TestClient): the app's own push feed loop cannot
    reach a daemon in CI and marks the feed down on every retry, racing the test. Hold the
    feed live for this test by stubbing that mark-down; the feed loop's own behaviour is
    covered end-to-end in tests/test_live_push_channel_v1.py."""
    mark_feed_live(*tickers)
    monkeypatch.setattr(lmp, "record_feed_down", lambda: None)
    # importing/starting the app can take longer than the 3 s heartbeat bound on a loaded CI
    # worker; heartbeat AGE is not what these tests exercise (it has its own tests)
    monkeypatch.setattr(lmp, "FEED_HEARTBEAT_MAX_AGE_SEC", 3600.0)
