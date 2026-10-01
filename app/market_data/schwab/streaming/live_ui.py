"""Prices straight from the capture daemon to the browser over WebSocket.

The daemon owns the Schwab connection. This server keeps the latest value of every
LEVELONE_EQUITIES field (live_market_plane, fed here in the daemon's own process), knows
whether the feed is alive (the daemon's own heartbeat, applied every HEARTBEAT_SEC), and
pushes the FINISHED displayed row (live_price_rows.price_row -- the one producer) to every
browser that asked for the symbol, the moment a Schwab message changes it.

No web server sits in this path, so no analytics load can delay a price.

Protocol (JSON text frames). Every page gets every board ticker; there is no per-page list.
  server  -> {"type": "board", "board": [{key, display}, ...]}       (on connect and on every
                                                                     change of the board)
  browser -> {"op": "board_add" | "board_remove", "symbol": "SPX"}  (edits the one board; from
                                                                     this computer only)
  server  -> {"type": "board_edit", op, requested, key, display, error}  (that page's answer:
                                                                     "SPX" is key "$SPX",
                                                                     shown "SPX")
  server  -> {"type": "quotes", "rows": [price_row, ...]}            (snapshot on connect,
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
from instrument_identity import display_symbol
from stream_spine import COUNT_DROPS, MessageBus

log = logging.getLogger(__name__)

#: The browser connects to this port on the console's own host name. Binds like the console
#: (0.0.0.0): the page is served to whatever address the operator opened it on.
LIVE_UI_HOST = os.environ.get("ED_LIVE_UI_HOST", "0.0.0.0")  # caps-ok: operator bind config with its declared default, not market data
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict + row beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0
#: a board edit is accepted only from the console's own page on this computer: a connection from
#: this computer whose page came from the console (a browser sends its page's origin; any other
#: page open in the browser could otherwise edit the board through ws://127.0.0.1)
LOCAL_ADDRESSES = ("127.0.0.1", "::1")
CONSOLE_PORT = int(os.environ.get("ED_CONSOLE_PORT", "8000"))  # caps-ok: operator port config with its declared default (start_ed_console.bat), not market data
CONSOLE_ORIGINS = (f"http://127.0.0.1:{CONSOLE_PORT}", f"http://localhost:{CONSOLE_PORT}")


class _Client:
    __slots__ = ("ws", "pending", "notes", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.pending: set[str] = set()      # board symbols changed since the last send
        self.notes: list[dict] = []         # board messages not yet sent
        self.wake = asyncio.Event()


def board_message(board: "list[str]") -> dict:
    """The board as every page shows it: each ticker's key (its rows carry it) and display name."""
    return {"type": "board", "board": [{"key": k, "display": display_symbol(k)} for k in board]}


class LiveUiServer:
    """Every page gets the board and the price row of every board ticker; the board is the
    daemon's (`board()`), edited through `edit(op, symbol, now)`."""

    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict, board, edit) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        self.stats = stats
        self.board = board
        self.edit = edit
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
        """Plane row listener: mark a board symbol changed for every browser."""
        if ticker not in self.board():
            return
        for c in self.clients:
            c.pending.add(ticker)
            c.wake.set()

    def on_board(self, board: "list[str]") -> None:
        """The board changed: every browser gets it, and the row of every ticker on it."""
        for c in self.clients:
            c.notes.append(board_message(board))
            c.pending |= set(board)
            c.wake.set()

    def beat(self) -> dict:
        hb = self.heartbeat_fn()
        lmp.record_feed_heartbeat(hb, time.time())
        return {"ts": hb.get("ts"), "schwab_socket_open": hb.get("schwab_socket_open") is True}

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
            notes, c.notes = c.notes, []
            for note in notes:
                await self._send(c, note)
            board = set(self.board())
            syms, c.pending = c.pending, set()
            rows = [live_price_rows.price_row(s) for s in syms if s in board]
            if rows:
                await self._send(c, {"type": "quotes", "rows": rows})

    async def _read(self, c: _Client) -> None:
        """A page's board edits: {"op": "board_add" | "board_remove", "symbol": ...}, accepted from
        the console's page on this computer only (CONSOLE_ORIGINS; the socket serves prices to any
        address the operator opens the page on). The answer goes to that page ({"type":
        "board_edit", requested, key, error}); the new board to every page (on_board)."""
        request = getattr(c.ws, "request", None)
        origin = request.headers.get("Origin") if request is not None else None
        local = ((getattr(c.ws, "remote_address", None) or ("",))[0] in LOCAL_ADDRESSES
                 and origin in CONSOLE_ORIGINS)
        async for frame in c.ws:
            try:
                req = json.loads(frame)
            except (TypeError, ValueError):
                continue
            if not isinstance(req, dict) or req.get("op") not in ("board_add", "board_remove"):
                continue
            if local:
                key, error = await self.edit(req["op"], req.get("symbol"), time.time())
            else:
                key, error = None, ("the board is edited only from the console's page on the "
                                    "computer running Ed Console (http://127.0.0.1:"
                                    f"{CONSOLE_PORT}/)")
            c.notes.append({"type": "board_edit", "op": req["op"], "requested": req.get("symbol"),
                            "key": key, "display": display_symbol(key) if key else None,
                            "error": error})
            c.wake.set()

    async def serve_client(self, ws) -> None:
        c = _Client(ws)
        c.notes.append(board_message(self.board()))
        c.pending = set(self.board())        # snapshot: the current row of every board ticker
        c.wake.set()
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
                # one browser can neither stop the beat nor hold it: an error is logged and the
                # next browser still gets its beat; a browser that does not take its beat within
                # a beat is not reading and is closed (2026-09-26: the beat stopped for every
                # browser and the whole screen read "no live feed" on a healthy Schwab socket)
                try:
                    rows = [live_price_rows.price_row(s) for s in self.board()]
                    await asyncio.wait_for(
                        self._send(c, {"type": "feed", "feed": feed, "rows": rows}),
                        timeout=HEARTBEAT_SEC)
                except asyncio.TimeoutError:
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui: a browser stopped reading; closing it")
                    asyncio.create_task(c.ws.close())
                except Exception as e:  # noqa: BLE001 -- logged; the other browsers' beats go out
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui beat to one browser: %s: %s", type(e).__name__, e)
            await asyncio.sleep(HEARTBEAT_SEC)


async def serve_live_ui(bus: MessageBus, stop: asyncio.Event, *, heartbeat_fn, daemon,
                        host: str = LIVE_UI_HOST, port: int = LIVE_UI_PORT,
                        stats: "dict | None" = None) -> None:
    """Run until `stop` is set. Start it BEFORE the Schwab connection so the plane sees the
    first messages (Schwab sends each field once, then only changes). `daemon` holds the board
    (capture.Daemon: .board, .edit_board, .board_listeners)."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    srv = LiveUiServer(bus, heartbeat_fn, stats, lambda: daemon.board, daemon.edit_board)
    daemon.board_listeners.append(srv.on_board)
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
            log.info("live ui: serving price rows to browsers on ws://%s:%s", host, port)
            await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        lmp.remove_row_listener(srv.on_row)
        bus.unsubscribe(sub)
