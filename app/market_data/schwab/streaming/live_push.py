"""Local push channel: the capture daemon -> the console, in memory, no database.

The daemon owns the ONE Schwab streaming connection (Schwab allows one per account). Every
message it receives is published on its in-memory MessageBus. This module serves a local
WebSocket on 127.0.0.1 that forwards the Schwab-sourced messages to the console the moment
they are published, so the console's live values never wait on a database write or a poll.
SQLite (stream_capture.db) stays the permanent record, written by the writer thread; it is
not in the live path.

What is forwarded -- Schwab only, by each message's `src` (anything else published on
the same topics is refused):
  quote.SYM    src "schwab_l1"          LEVELONE_EQUITIES
  book.SYM     src "schwab_book"        NASDAQ_BOOK / NYSE_BOOK / OPTIONS_BOOK (by `service`)
  optquote.SYM src "schwab_options_l1"  LEVELONE_OPTIONS
  news.SYM     src "schwab_news"        NEWS_HEADLINE
  bar1m.SYM    src "schwab_chart"       CHART_EQUITY
  chain.TK     src "schwab_chain"       the REST option chain, in parts (the daemon's chain sweep)

A client receives the CURRENT RECORD of each topic as the daemon's bus keeps it (the newest by
Schwab's time; a LEVELONE record merged field by field, each field's times in `field_ts`; a
chain whole): first every record the bus holds, then each record that changes, the moment the
socket can take it. Nothing old waits in line behind a newer value (docs/DATA_FLOW.md §2 D1, D3).

Wire format: one JSON text frame per record, {"topic": str, "msg": {...}}; a chain is one frame
per part.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from stream_spine import LATEST, MessageBus

log = logging.getLogger(__name__)

LIVE_PUSH_HOST = "127.0.0.1"
#: Own port -- never shared with a web server (the e2e console used 8765). ED_LIVE_PUSH_PORT
#: overrides it; the test harnesses point it at an unused port so no test console can ever
#: receive the real daemon's live data.
LIVE_PUSH_PORT = int(os.environ.get("ED_LIVE_PUSH_PORT", "8799"))  # caps-ok: operator port config with its declared default, not market data

#: topic prefix -> the only `src` forwarded for it
_FORWARDED = {"quote.": "schwab_l1", "book.": "schwab_book", "optquote.": "schwab_options_l1",
              "news.": "schwab_news", "bar1m.": "schwab_chart", "chain.": "schwab_chain"}


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


def frames(topic: str, record) -> "list[str]":
    """The wire frames of one current record: a chain's parts arrive with their frames already
    built, off the event loop (complete_chain_capture.chain_messages)."""
    if topic.startswith("chain."):
        return [part["frame"] for part in record]
    return [json.dumps({"topic": topic, "msg": record}, separators=(",", ":"))]


async def _serve_client(ws, bus: MessageBus, stats: dict, on_wanted=None) -> None:
    """Send every current record, then each one that changes, until the connection closes.

    The send loop runs as its own task and this handler waits on the CONNECTION: a loop
    blocked on `sub.get()` would otherwise never notice a closed socket, and server
    shutdown (which waits for every handler to return) would hang behind it."""
    sub = bus.subscribe("", policy=LATEST)
    stats["clients"] += 1

    async def _pump() -> None:
        while True:
            topic, record = await sub.get()
            if is_forwarded(topic, record):
                for frame in frames(topic, record):
                    await ws.send(frame)
                stats["sent"] += 1

    async def _read() -> None:
        """The console's frames: {"op": "wanted", "wanted": {service: [symbols]}} -- the books
        and option contracts its screens show, from this connection (capture.Daemon.set_wanted).
        Ends when the socket closes."""
        async for frame in ws:
            try:
                req = json.loads(frame)
            except (TypeError, ValueError):
                continue
            if isinstance(req, dict) and req.get("op") == "wanted" and on_wanted is not None:
                on_wanted(req.get("wanted"), ws)

    pump = asyncio.create_task(_pump())
    closed = asyncio.create_task(_read())
    try:
        await asyncio.wait({pump, closed}, return_when=asyncio.FIRST_COMPLETED)
        if pump.done() and not pump.cancelled() and pump.exception() is not None:
            e = pump.exception()
            log.info("live push client ended: %s: %s", type(e).__name__, e)
    finally:
        for t in (pump, closed):
            t.cancel()
        await asyncio.gather(pump, closed, return_exceptions=True)
        bus.unsubscribe(sub)
        stats["clients"] -= 1
        if on_wanted is not None:   # this connection is gone: its list (if it holds one) is withdrawn
            on_wanted(None, ws)


async def serve_live_push(bus: MessageBus, stop: asyncio.Event, *,
                          host: str = LIVE_PUSH_HOST, port: int = LIVE_PUSH_PORT,
                          stats: "dict | None" = None, on_wanted=None) -> None:
    """Run the push server until `stop` is set. `stats` (mutated) reports clients and sent."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    stats.update(clients=0, sent=0, listening=None)

    async def handler(ws):
        await _serve_client(ws, bus, stats, on_wanted)

    async with serve(handler, host, port, max_size=None, ping_interval=20, ping_timeout=20):
        stats["listening"] = f"ws://{host}:{port}"
        log.info("live push: serving Schwab stream messages on ws://%s:%s", host, port)
        await stop.wait()
