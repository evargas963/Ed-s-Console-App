"""The program's local control socket, and which bus records are Schwab's.

Ed Console is one program: the console reads the daemon's bus in memory (app.options.order_flow.
streaming._bus_loop), never a copy over a socket. This module serves a WebSocket on 127.0.0.1
that hands each request it receives to the daemon (capture.Daemon.console_frame): launch.py's
clean stop ({"op": "stop"}).

The bus records the console takes -- Schwab only, by each message's `src` (anything else
published on the same topics is refused, is_forwarded):
  quote.SYM    src "schwab_l1"          LEVELONE_EQUITIES
  book.SYM     src "schwab_book"        NASDAQ_BOOK / NYSE_BOOK / OPTIONS_BOOK (by `service`)
  optquote.SYM src "schwab_options_l1"  LEVELONE_OPTIONS
  news.SYM     src "schwab_news"        NEWS_HEADLINE
  bar1m.SYM    src "schwab_chart"       CHART_EQUITY
  chain.TK     src "schwab_chain"       the REST option chain, in parts (the daemon's chain sweep)
  pricehistory.TK.SERIES src "schwab_pricehistory"  Schwab's 1-minute bars, 15-minute and daily
               candles of the ticker (the chain sweep's /pricehistory requests)
  markets.DATE src "schwab_markets"     Schwab's /markets answer for the market date (the chain
               sweep's requests), with its status
  watchlist    src "daemon_watchlist"   the watchlist after each add or removal the console asked
               for, with Schwab's /quotes answer to an add's check (capture.watchlist_message)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket

from websockets.asyncio.server import serve

log = logging.getLogger(__name__)

LIVE_PUSH_HOST = "127.0.0.1"
#: Own port -- never shared with a web server (the e2e console used 8765). ED_LIVE_PUSH_PORT
#: overrides it; the test harnesses point it at an unused port so no test console can ever
#: receive the real daemon's live data.
LIVE_PUSH_PORT = int(
    os.environ.get("ED_LIVE_PUSH_PORT", "8799")
)  # caps-ok: operator port config with its declared default, not market data

#: The market context every page's header shows beside the selected ticker (Trade Desk): the
#: daemon streams it whatever the watchlist holds.
MARKET_CONTEXT = ("$SPX", "$NDX", "$VIX")

#: topic prefix -> the only `src` forwarded for it
_FORWARDED = {
    "quote.": "schwab_l1",
    "book.": "schwab_book",
    "optquote.": "schwab_options_l1",
    "news.": "schwab_news",
    "bar1m.": "schwab_chart",
    "chain.": "schwab_chain",
    "pricehistory.": "schwab_pricehistory",
    "markets.": "schwab_markets",
    "watchlist": "daemon_watchlist",
}


def is_forwarded(topic: str, msg) -> bool:
    """A record that came from Schwab (a chain: its parts)."""
    if isinstance(msg, list) and msg:
        msg = msg[0]
    if not isinstance(msg, dict):
        return False
    for prefix, src in _FORWARDED.items():
        if topic.startswith(prefix):
            return msg.get("src") == src
    return False


async def _serve_client(ws, stats: dict, on_request) -> None:
    """Each frame of one connection handed to `on_request` (capture.Daemon.console_frame), until
    the connection closes. A frame that is not a JSON object is logged with what arrived."""
    stats["clients"] += 1
    try:
        async for frame in ws:
            try:
                req = json.loads(frame)
            except (TypeError, ValueError) as e:
                log.warning("live push: a frame that is not JSON (%s): %r", e, frame)
                continue
            if not isinstance(req, dict):
                log.warning("live push: a frame that is not a JSON object: %r", frame)
            else:
                on_request(req)
    finally:
        stats["clients"] -= 1


async def serve_live_push(
    stop: asyncio.Event,
    on_request,
    sock: socket.socket,
    *,
    stats: dict | None = None,
) -> None:
    """Run the control socket on the listening `sock` until `stop` is set.

    Each request is handed to `on_request`; `stats` (mutated) reports clients.
    """
    stats = stats if stats is not None else {}
    stats.update(clients=0)

    async def handler(ws):
        await _serve_client(ws, stats, on_request)

    async with serve(
        handler,
        sock=sock,
        max_size=None,
        ping_interval=20,
        ping_timeout=20,
        origins=[None],  # no browser: a page always sends an Origin, this program's clients none
    ):
        log.info("live push: the control socket listens on ws://%s:%s", *sock.getsockname()[:2])
        await stop.wait()
