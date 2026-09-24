"""Prices straight from the capture daemon to the browser over WebSocket.

The daemon owns the Schwab connection. This server keeps the latest value of every
LEVELONE_EQUITIES field (live_market_plane, fed here in the daemon's own process), knows
whether the feed is alive (the daemon's own heartbeat, applied every HEARTBEAT_SEC), and
pushes the FINISHED displayed row (live_price_rows.price_row -- the one producer) to every
browser that asked for the symbol, the moment a Schwab message changes it.

No web server sits in this path, so no analytics load can delay a price.

Protocol (JSON text frames):
  browser -> {"op": "subscribe", "symbols": ["SPY", "AAPL", ...]}   (replaces the set)
  server  -> {"type": "quotes", "rows": [price_row, ...]}            (snapshot on subscribe,
                                                                     then every change)
  server  -> {"type": "feed", "feed": {...}, "rows": [...]}           (every HEARTBEAT_SEC:
                                                                     the feed verdict and a
                                                                     fresh row per symbol, so
                                                                     a dead feed reads dead
                                                                     within FEED_HEARTBEAT_
                                                                     MAX_AGE_SEC)

Delivery is latest-value-per-symbol per client (conflation, as Lightstreamer MERGE /
LSEG conflated feeds do): a slow browser gets the newest row for each symbol it is behind
on, never a queue of stale ones, and never loses a symbol's only update.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import live_market_plane as lmp
import live_price_rows
from instrument_identity import ticker_storage_key
from stream_spine import COUNT_DROPS, MessageBus

log = logging.getLogger(__name__)

#: The browser connects to this port on the console's own host name. Binds like the console
#: (0.0.0.0): the page is served to whatever address the operator opened it on.
LIVE_UI_HOST = os.environ.get("ED_LIVE_UI_HOST", "0.0.0.0")  # caps-ok: operator bind config with its declared default, not market data
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict + row beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0
#: a browser may watch at most this many symbols (the daemon holds ~50)
MAX_SYMBOLS_PER_CLIENT = 200


class _Client:
    __slots__ = ("ws", "symbols", "pending", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.pending: set[str] = set()      # symbols changed since the last send
        self.wake = asyncio.Event()


class LiveUiServer:
    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        self.stats = stats
        self.clients: set[_Client] = set()
        stats.update(clients=0, rows_sent=0, frames_sent=0, ingest_failures=0,
                     beat_send_failures=0, listening=None, last_send_ms=None)

    # -- plane side -------------------------------------------------------------------

    def ingest(self, msg) -> None:
        """One daemon quote message -> the plane (per-field state, the daemon's receive time)."""
        if not isinstance(msg, dict):
            return
        sym, ts, item = msg.get("symbol"), msg.get("ts_recv"), msg.get("native")
        if not sym or not isinstance(ts, (int, float)) or not isinstance(item, dict):
            return
        try:
            lmp.record_from_level_one_equity(sym, item, received_ts=float(ts))
        except Exception as e:  # noqa: BLE001 -- counted; one malformed item never ends the feed
            self.stats["ingest_failures"] += 1
            log.warning("live ui ingest %s: %s: %s", sym, type(e).__name__, e)

    def on_row(self, ticker: str) -> None:
        """Plane row listener: mark the symbol changed for every browser watching it."""
        for c in self.clients:
            if ticker in c.symbols:
                c.pending.add(ticker)
                c.wake.set()

    def beat(self) -> dict:
        hb = self.heartbeat_fn()
        lmp.record_feed_heartbeat(hb, time.time())
        return {"ts": hb.get("ts"), "schwab_socket_open": hb.get("schwab_socket_open") is True,
                "equities_held": hb.get("equities_held")}

    # -- browser side -----------------------------------------------------------------

    async def _send(self, c: _Client, payload: dict) -> None:
        t0 = time.perf_counter()
        await c.ws.send(json.dumps(payload, separators=(",", ":"), default=str))
        self.stats["frames_sent"] += 1
        self.stats["rows_sent"] += len(payload.get("rows") or ())
        self.stats["last_send_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)

    async def _pump(self, c: _Client) -> None:
        while True:
            await c.wake.wait()
            c.wake.clear()
            syms, c.pending = c.pending, set()
            rows = [live_price_rows.price_row(s) for s in syms if s in c.symbols]
            if rows:
                await self._send(c, {"type": "quotes", "rows": rows})

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
            keys = []
            for s in raw[:MAX_SYMBOLS_PER_CLIENT]:
                k = ticker_storage_key(s) if isinstance(s, str) else ""
                if k and k not in keys:
                    keys.append(k)
            c.symbols = frozenset(keys)
            c.pending = set(keys)            # snapshot: the current row for each, now
            c.wake.set()

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
                rows = [live_price_rows.price_row(s) for s in sorted(c.symbols)]
                try:
                    await self._send(c, {"type": "feed", "feed": feed, "rows": rows})
                except Exception as e:  # noqa: BLE001 -- counted; that client's own handler ends it
                    # a closed browser fails its send here and its handler removes it; the
                    # other browsers' beats must still go out
                    self.stats["beat_send_failures"] += 1
                    log.debug("live ui beat to a closing client: %s: %s", type(e).__name__, e)
            await asyncio.sleep(HEARTBEAT_SEC)


async def serve_live_ui(bus: MessageBus, stop: asyncio.Event, *, heartbeat_fn,
                        host: str = LIVE_UI_HOST, port: int = LIVE_UI_PORT,
                        stats: "dict | None" = None) -> None:
    """Run until `stop` is set. Start it BEFORE the Schwab connection so the plane sees the
    first messages (Schwab sends each field once, then only changes)."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    srv = LiveUiServer(bus, heartbeat_fn, stats)
    for topic, msg in list(bus.snapshot().items()):         # whatever arrived before we started
        if topic.startswith("quote."):
            srv.ingest(msg)
    sub = bus.subscribe("quote.", policy=COUNT_DROPS, maxsize=65536, name="live_ui")
    lmp.add_row_listener(srv.on_row)

    async def _track() -> None:
        while True:
            _topic, msg = await sub.get()
            srv.ingest(msg)

    tasks = [asyncio.create_task(_track()), asyncio.create_task(srv.beat_loop())]
    try:
        async with serve(srv.serve_client, host, port, max_size=65536, compression=None,
                         ping_interval=20, ping_timeout=20):
            stats["listening"] = f"ws://{host}:{port}"
            print(f"live ui: serving price rows to browsers on ws://{host}:{port}")
            await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        lmp.remove_row_listener(srv.on_row)
        bus.unsubscribe(sub)
