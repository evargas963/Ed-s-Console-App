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

On connect a client first receives the CURRENT STATE, then every new message live. Schwab's
LEVELONE services send only the fields that changed, so "the last message" is not the state:
it usually lacks LAST_PRICE, CLOSE_PRICE or the Greeks. For quote.* and optquote.* the server
therefore keeps, per symbol, the latest message that carried each field (FieldHistory) and
replays those messages in receive order -- every field arrives exactly as streamed, with the
receive time of the message that actually carried it, so no old value is made to look new.
book.* messages are whole books, so the last one is the state.

Wire format: one JSON text frame per message, {"topic": str, "msg": {...}}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from stream_spine import COUNT_DROPS, MessageBus

log = logging.getLogger(__name__)

LIVE_PUSH_HOST = "127.0.0.1"
#: Own port -- never shared with a web server (the e2e console used 8765). ED_LIVE_PUSH_PORT
#: overrides it; the test harnesses point it at an unused port so no test console can ever
#: receive the real daemon's live data.
LIVE_PUSH_PORT = int(os.environ.get("ED_LIVE_PUSH_PORT", "8799"))  # caps-ok: operator port config with its declared default, not market data

#: topic prefix -> the only `src` forwarded for it
_FORWARDED = {"quote.": "schwab_l1", "book.": "schwab_book", "optquote.": "schwab_options_l1"}


def is_forwarded(topic: str, msg) -> bool:
    if not isinstance(msg, dict):
        return False
    for prefix, src in _FORWARDED.items():
        if topic.startswith(prefix):
            return msg.get("src") == src
    return False


class FieldHistory:
    """Per symbol: the latest message that carried each field. `replay()` returns those
    messages (deduplicated) in receive order."""

    def __init__(self) -> None:
        self._by_topic: "dict[str, dict[str, tuple[float, int]]]" = {}
        self._msgs: "dict[int, tuple[str, dict]]" = {}
        self._seq = 0

    @staticmethod
    def payload(topic: str, msg: dict) -> "dict | None":
        body = msg.get("native") if topic.startswith("quote.") else msg.get("content")
        return body if isinstance(body, dict) else None

    def record(self, topic: str, msg: dict) -> None:
        body = self.payload(topic, msg)
        ts = msg.get("ts_recv")
        if body is None or not isinstance(ts, (int, float)):
            return
        self._seq += 1
        self._msgs[self._seq] = (topic, msg)
        fields = self._by_topic.setdefault(topic, {})
        for k in body:
            fields[k] = (float(ts), self._seq)
        live = {sid for f in self._by_topic.values() for _t, sid in f.values()}
        if len(self._msgs) > 4 * len(live) + 1024:          # drop messages no field points at
            self._msgs = {sid: m for sid, m in self._msgs.items() if sid in live}

    def replay(self) -> "list[tuple[str, dict]]":
        ids = sorted({(ts, sid) for f in self._by_topic.values() for ts, sid in f.values()})
        return [self._msgs[sid] for _ts, sid in ids if sid in self._msgs]


def is_field_delta_topic(topic: str) -> bool:
    return topic.startswith("quote.") or topic.startswith("optquote.")


def encode(topic: str, msg: dict) -> str:
    return json.dumps({"topic": topic, "msg": msg}, separators=(",", ":"))


async def _serve_client(ws, bus: MessageBus, stats: dict, history: FieldHistory) -> None:
    """Send the last values, then every live message, until the connection closes.

    The send loop runs as its own task and this handler waits on the CONNECTION: a loop
    blocked on `sub.get()` would otherwise never notice a closed socket, and server
    shutdown (which waits for every handler to return) would hang behind it."""
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=16384)
    stats["clients"] += 1

    async def _pump() -> None:
        # current state first: field-delta topics from their field history, books from
        # the bus's last value (a book message is a whole book)
        for topic, msg in history.replay():
            await ws.send(encode(topic, msg))
        for topic, msg in list(bus.snapshot().items()):
            if not is_field_delta_topic(topic) and is_forwarded(topic, msg):
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
    history = FieldHistory()
    for topic, msg in list(bus.snapshot().items()):        # whatever arrived before we started
        if is_field_delta_topic(topic) and is_forwarded(topic, msg):
            history.record(topic, msg)
    hsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=65536)

    async def _track() -> None:
        while True:
            topic, msg = await hsub.get()
            if is_field_delta_topic(topic) and is_forwarded(topic, msg):
                history.record(topic, msg)

    async def handler(ws):
        await _serve_client(ws, bus, stats, history)

    tracker = asyncio.create_task(_track())
    try:
        async with serve(handler, host, port, max_size=None, ping_interval=20, ping_timeout=20):
            stats["listening"] = f"ws://{host}:{port}"
            print(f"live push: serving Schwab stream messages on ws://{host}:{port}")
            await stop.wait()
    finally:
        tracker.cancel()
        await asyncio.gather(tracker, return_exceptions=True)
        bus.unsubscribe(hsub)
