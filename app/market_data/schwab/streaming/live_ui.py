"""Schwab's LEVELONE_EQUITIES messages straight from the capture daemon to the console over
WebSocket, by their Schwab delivery type (Streamer API §1.1: Change), with the daemon's status
every second. The console's price record is built from them (streaming._rows_loop), and the
console pushes the page its price rows (server.live_values); no page connects here.

The daemon owns the Schwab connection. This server takes every LEVELONE_EQUITIES message from the
daemon's bus as Schwab sent it and pushes it to every client that asked for its symbol: only the
fields that changed (a client behind gets each field's newest value, merged; none lost). On
subscribe a client gets each symbol's current record: every field Schwab has sent for it.

Protocol (JSON text frames):
  client -> {"op": "subscribe", "symbols": ["SPY", "$SPX", ...]}  (replaces the set)
  server -> {"type": "schwab", "messages": [{service, key, schwab_ts, ts_recv, content}, ...]}
  server -> {"type": "feed", "feed": {...}}  (every HEARTBEAT_SEC: the daemon's whole status)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from instrument_identity import ticker_storage_key
from stream_spine import LOG, MessageBus

log = logging.getLogger(__name__)

#: The console connects to this port (streaming.LIVE_UI_URL), on this computer only (operator
#: 2026-10-14: "I only use this computer")
LIVE_UI_HOST = "127.0.0.1"
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0
SERVICE = "LEVELONE_EQUITIES"


def schwab_message(topic: str, msg: dict) -> "dict | None":
    """A bus quote as the client gets it: its Schwab service, symbol, Schwab's frame time, the
    daemon's receive time and Schwab's item as sent; None for any other topic."""
    if topic.split(".", 1)[0] != "quote" or not isinstance(msg, dict) or not msg.get("symbol"):
        return None
    content = msg.get("native")
    if not isinstance(content, dict):
        return None
    return {"service": SERVICE, "key": msg["symbol"], "schwab_ts": msg.get("schwab_ts"),
            "ts_recv": msg.get("ts_recv"), "content": content}


class _Client:
    __slots__ = ("ws", "symbols", "change", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.change: dict[str, dict] = {}         # key -> the changed fields not yet sent
        self.wake = asyncio.Event()

    def take(self, m: dict) -> None:
        """One Schwab message for this client, merged with any not yet sent (Change)."""
        held = self.change.get(m["key"])
        if held is None:
            self.change[m["key"]] = {**m, "content": dict(m["content"])}
        else:                     # newest value of each field; Schwab's newest frame time
            held["content"].update(m["content"])
            held["schwab_ts"], held["ts_recv"] = m["schwab_ts"], m["ts_recv"]
        self.wake.set()

    def drain(self) -> list[dict]:
        out, self.change = list(self.change.values()), {}
        return out


class LiveUiServer:
    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        self.stats = stats
        self.clients: set[_Client] = set()
        stats.update(clients=0, messages_sent=0, frames_sent=0, beat_send_failures=0, listening=None,
                     last_send_ms=None)

    def route(self, topic: str, msg) -> None:
        """One Schwab message from the bus to every client that asked for its symbol."""
        m = schwab_message(topic, msg)
        if m is None:
            return
        for c in self.clients:
            if m["key"] in c.symbols:
                c.take(m)

    def snapshot(self, c: _Client, keys: "list[str]") -> None:
        """Each symbol's current record on the bus, for a client that just asked for it."""
        for topic, record in list(self.bus.current.values()):
            m = schwab_message(topic, record)
            if m is not None and m["key"] in keys:
                c.take(m)

    def beat(self) -> dict:
        """The daemon's whole status (Schwab socket, symbols held and refused per service, the
        watchlist, health), sent with every beat: the console's one record of it."""
        return self.heartbeat_fn()

    # -- client side ------------------------------------------------------------------

    async def _send(self, c: _Client, payload: dict) -> None:
        t0 = time.perf_counter()
        await c.ws.send(json.dumps(payload, separators=(",", ":"), default=str))
        self.stats["frames_sent"] += 1
        if payload["type"] == "schwab":             # the frame that carries Schwab's messages
            self.stats["messages_sent"] += len(payload["messages"])
        self.stats["last_send_ms"] = (time.perf_counter() - t0) * 1000.0

    async def _pump(self, c: _Client) -> None:
        while True:
            await c.wake.wait()
            c.wake.clear()
            messages = c.drain()
            if messages:
                await self._send(c, {"type": "schwab", "messages": messages})

    async def _read(self, c: _Client) -> None:
        async for frame in c.ws:
            try:
                req = json.loads(frame)
            except (TypeError, ValueError):
                continue
            if not isinstance(req, dict) or req.get("op") != "subscribe":
                continue
            raw = req.get("symbols")
            if not isinstance(raw, list):
                continue
            keys = list(dict.fromkeys(k for k in (ticker_storage_key(s) if isinstance(s, str) else "" for s in raw) if k))
            added = [k for k in keys if k not in c.symbols]
            c.symbols = frozenset(keys)
            self.snapshot(c, added)

    async def serve_client(self, ws) -> None:
        c = _Client(ws)
        self.clients.add(c)
        self.stats["clients"] = len(self.clients)
        pump = asyncio.create_task(self._pump(c))
        read = asyncio.create_task(self._read(c))
        try:
            await asyncio.wait({pump, read}, return_when=asyncio.FIRST_COMPLETED)
            for t in (pump, read):
                if t.done() and not t.cancelled() and t.exception() is not None:
                    e = t.exception()
                    log.info("live ui client ended: %s: %s", type(e).__name__, e)
        finally:
            for t in (pump, read):
                t.cancel()
            await asyncio.gather(pump, read, return_exceptions=True)
            self.clients.discard(c)
            self.stats["clients"] = len(self.clients)

    async def beat_loop(self) -> None:
        while True:
            try:
                feed = self.beat()
            except Exception as e:  # noqa: BLE001 -- a failed beat leaves the feed unproven (it ages out)
                log.warning("live ui heartbeat: %s: %s", type(e).__name__, e)
                feed = None
            for c in list(self.clients):
                # one client can neither stop the beat nor hold it: an error is logged and the
                # next client still gets its beat; a client that does not take its beat within
                # a beat is not reading and is closed, and gets no more beats while it closes
                # (2026-09-26: the beat stopped for every client and the whole screen read "no
                # live feed" on a healthy Schwab socket)
                try:
                    await asyncio.wait_for(self._send(c, {"type": "feed", "feed": feed}), timeout=HEARTBEAT_SEC)
                except asyncio.TimeoutError:
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui: a client stopped reading; closing it")
                    self.clients.discard(c)
                    asyncio.create_task(c.ws.close())
                except Exception as e:  # noqa: BLE001 -- logged; the other clients' beats go out
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui beat to one client: %s: %s", type(e).__name__, e)
            await asyncio.sleep(HEARTBEAT_SEC)


async def serve_live_ui(bus: MessageBus, stop: asyncio.Event, *, heartbeat_fn,
                        host: str = LIVE_UI_HOST, port: int = LIVE_UI_PORT,
                        stats: "dict | None" = None) -> None:
    """Run until `stop` is set. Start it BEFORE the Schwab connection so no message is missed."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    srv = LiveUiServer(bus, heartbeat_fn, stats)
    sub = bus.subscribe("quote.", policy=LOG)           # every quote, as published

    async def _route() -> None:
        while True:
            topic, msg = await sub.get()
            srv.route(topic, msg)

    tasks = [asyncio.create_task(_route()), asyncio.create_task(srv.beat_loop())]
    try:
        async with serve(srv.serve_client, host, port, max_size=None, compression=None,
                         ping_interval=20, ping_timeout=20) as server:
            bound = server.sockets[0].getsockname()[1]  # the port taken (port 0: the system's pick)
            stats["listening"] = f"ws://{host}:{bound}"
            log.info("live ui: serving Schwab's quotes to the console on ws://%s:%s", host, bound)
            await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bus.unsubscribe(sub)
