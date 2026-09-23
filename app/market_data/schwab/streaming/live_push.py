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

On connect a client first receives the bus's last-value cache for those topics -- each
message exactly as the stream delivered it, with its own `ts_recv`, so the consumer's
freshness checks judge it by when it actually arrived -- then every new message live.

Wire format: one JSON text frame per message, {"topic": str, "msg": {...}}.
"""
from __future__ import annotations

import asyncio
import json
import logging

from stream_spine import COUNT_DROPS, MessageBus

log = logging.getLogger(__name__)

LIVE_PUSH_HOST = "127.0.0.1"
LIVE_PUSH_PORT = 8765

#: topic prefix -> the only `src` forwarded for it
_FORWARDED = {"quote.": "schwab_l1", "book.": "schwab_book", "optquote.": "schwab_options_l1"}


def is_forwarded(topic: str, msg) -> bool:
    if not isinstance(msg, dict):
        return False
    for prefix, src in _FORWARDED.items():
        if topic.startswith(prefix):
            return msg.get("src") == src
    return False


def encode(topic: str, msg: dict) -> str:
    return json.dumps({"topic": topic, "msg": msg}, separators=(",", ":"))


async def _serve_client(ws, bus: MessageBus, stats: dict) -> None:
    """Send the last values, then every live message, until the connection closes.

    The send loop runs as its own task and this handler waits on the CONNECTION: a loop
    blocked on `sub.get()` would otherwise never notice a closed socket, and server
    shutdown (which waits for every handler to return) would hang behind it."""
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=16384)
    stats["clients"] += 1

    async def _pump() -> None:
        for topic, msg in list(bus.snapshot().items()):
            if is_forwarded(topic, msg):
                await ws.send(encode(topic, msg))
        while True:
            topic, msg = await sub.get()
            if is_forwarded(topic, msg):
                await ws.send(encode(topic, msg))
                stats["sent"] += 1

    pump = asyncio.create_task(_pump())
    closed = asyncio.create_task(ws.wait_closed())
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
        stats["dropped"] += sub.dropped


async def serve_live_push(bus: MessageBus, stop: asyncio.Event, *,
                          host: str = LIVE_PUSH_HOST, port: int = LIVE_PUSH_PORT,
                          stats: "dict | None" = None) -> None:
    """Run the push server until `stop` is set. `stats` (mutated) reports clients/sent/dropped."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    stats.update(clients=0, sent=0, dropped=0, listening=None)

    async def handler(ws):
        await _serve_client(ws, bus, stats)

    async with serve(handler, host, port, max_size=None, ping_interval=20, ping_timeout=20):
        stats["listening"] = f"ws://{host}:{port}"
        print(f"live push: serving Schwab stream messages on ws://{host}:{port}")
        await stop.wait()
