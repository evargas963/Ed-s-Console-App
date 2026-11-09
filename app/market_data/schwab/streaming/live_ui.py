"""Prices straight from the capture daemon to the browser over the page's socket.

The daemon owns the Schwab connection. This server reads the latest value of every
LEVELONE_EQUITIES field (live_market_plane, fed by capture.Daemon.follow_market), knows
whether the feed is alive (the daemon's own heartbeat, applied every HEARTBEAT_SEC), and
pushes the FINISHED displayed row (live_price_rows.price_row -- the one producer) to every
browser that asked for the symbol, the moment a Schwab message changes it.

The page's socket is /ws on the program's own web server (server.app, page_socket), the one
address the page talks to. A page that stops reading is dropped (PageSocket).

Protocol (JSON text frames):
  browser -> {"op": "subscribe", "symbols": ["SPY", "AAPL", ...],   (replaces the set and the
              "ticker": "SPY"}                                      page's selected ticker, or
                                                                     null for none)
  server  -> {"type": "symbols", "symbols": [{requested, key, display}, ...]}  (on subscribe:
                                                                     what each asked-for symbol
                                                                     is -- "SPX" is key "$SPX",
                                                                     shown "SPX")
  server  -> {"type": "quotes", "rows": [price_row, ...]}            (snapshot on subscribe,
                                                                     then every change)
  server  -> {"type": <kind>, "ticker": key, ...body}                (each panel of the selected
                                                                     ticker, its producer's body
                                                                     (`panels`, server.PAGE_
                                                                     PANELS): on subscribe, then
                                                                     each time it changes)
  server  -> {"type": "feed", "feed": {...}, "rows": [...]}           (every HEARTBEAT_SEC:
                                                                     the daemon's whole status
                                                                     and a fresh row per symbol,
                                                                     so a dead feed reads dead
                                                                     within FEED_HEARTBEAT_
                                                                     MAX_AGE_SEC; the console
                                                                     takes its status from here)

Delivery is latest-value-per-symbol per client (conflation, as Lightstreamer MERGE /
LSEG conflated feeds do): a slow browser gets the newest row for each symbol it is behind
on, never a queue of stale ones, and never loses a symbol's only update.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from starlette.websockets import WebSocket, WebSocketDisconnect
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol

import live_market_plane as lmp
import live_price_rows
import time_et
from instrument_identity import display_symbol, ticker_storage_key

log = logging.getLogger(__name__)

#: The console's pages and routes (server.app) and the page's socket (/ws), served by the program
#: on every address: the page is served to whatever address the operator opened it on;
#: ED_CONSOLE_PORT points a test's program at a free port of its own
CONSOLE_HOST = "0.0.0.0"
CONSOLE_PORT = int(os.environ.get("ED_CONSOLE_PORT", "8000"))
#: feed verdict + row beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0


class PageSocket(WebSocketsSansIOProtocol):
    """uvicorn's WebSocket protocol for the program's web server.

    A page that stops reading is dropped: its connection aborted, because a close frame cannot
    reach a page that does not read and asyncio's close waits for the bytes it never takes.

    A page has stopped reading when asyncio's flow control keeps writing paused (its buffers full)
    for HEARTBEAT_SEC, or when it does not answer uvicorn's keepalive ping in time.
    """

    _stalled: asyncio.TimerHandle | None = None

    def pause_writing(self) -> None:
        super().pause_writing()
        self._stalled = self.loop.call_later(HEARTBEAT_SEC, self._drop, "a beat unread")

    def resume_writing(self) -> None:
        super().resume_writing()
        self._stalled.cancel()

    def keepalive_timeout(self) -> None:
        self._drop("the keepalive ping unanswered")

    def connection_lost(self, exc: Exception | None) -> None:
        if self._stalled is not None:
            self._stalled.cancel()
        super().connection_lost(exc)

    def _drop(self, why: str) -> None:
        log.warning("live ui: a page stopped reading (%s); dropping it", why)
        self.transport.abort()


class _Client:
    __slots__ = ("ws", "symbols", "pending", "identity", "ticker", "panels", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.pending: set[str] = set()  # symbols changed since the last send
        self.identity: list[dict] | None = None  # the last subscribe's answer, not yet sent
        self.ticker: str | None = None  # the page's selected ticker (its key); None: none
        self.panels: set[str] = set()  # the selected ticker's panels changed since the last send
        self.wake = asyncio.Event()


class LiveUiServer:
    #: the event loop it serves on (serve_live_ui), where a producer's change is marked (changed)
    loop: asyncio.AbstractEventLoop

    def __init__(
        self,
        heartbeat_fn,
        stats: dict,
        record_heartbeat=lmp.record_feed_heartbeat,
        clock=time_et.now,
        *,
        panels: dict,
    ) -> None:
        self.heartbeat_fn = heartbeat_fn
        self.panels = panels  # each panel's producer, (ticker, now) -> its body
        self.clock = clock  # the time each row is finished at, and each beat
        self.record_heartbeat = (
            record_heartbeat  # where the daemon keeps its own record of each beat
        )
        self.stats = stats
        self.clients: set[_Client] = set()
        stats.update(
            clients=0,
            rows_sent=0,
            frames_sent=0,
            beat_send_failures=0,
            last_send_ms=None,
        )

    # -- plane side -------------------------------------------------------------------

    def on_row(self, ticker: str) -> None:
        """Plane row listener: mark the symbol changed for every browser watching it."""
        for c in self.clients:
            if ticker in c.symbols:
                c.pending.add(ticker)
                c.wake.set()

    def on_change(self, ticker: str, kind: str) -> None:
        """Mark panel `kind` changed for every browser whose selected ticker is `ticker`."""
        for c in self.clients:
            if c.ticker == ticker:
                c.panels.add(kind)
                c.wake.set()

    def beat(self) -> dict:
        """Return the daemon's whole status, recorded here and sent with every beat.

        The status covers the Schwab socket, symbols held and refused per service, the watchlist
        and health; this is the console's one record of it.
        """
        hb = self.heartbeat_fn(self.clock())
        self.record_heartbeat(hb)
        return hb

    # -- browser side -----------------------------------------------------------------

    async def _send(self, c: _Client, payload: dict) -> None:
        t0 = time_et.elapsed()
        await c.ws.send_text(json.dumps(payload, separators=(",", ":"), default=str))
        self.stats["frames_sent"] += 1
        if "rows" in payload:  # a symbols frame carries none
            self.stats["rows_sent"] += len(payload["rows"])
        self.stats["last_send_ms"] = (time_et.elapsed() - t0) * 1000.0

    async def _pump(self, c: _Client) -> None:
        while True:
            await c.wake.wait()
            c.wake.clear()
            if c.identity is not None:
                identity, c.identity = c.identity, None
                await self._send(c, {"type": "symbols", "symbols": identity})
            now = self.clock()
            kinds, c.panels = c.panels, set()
            for kind in sorted(kinds):
                body = self.panels[kind](c.ticker, now)
                await self._send(c, {"type": kind, "ticker": c.ticker, **body})
            syms, c.pending = c.pending, set()
            rows = [live_price_rows.price_row(s, now) for s in syms if s in c.symbols]
            if rows:
                await self._send(c, {"type": "quotes", "rows": rows})

    async def _read(self, c: _Client) -> None:
        while (msg := await c.ws.receive())["type"] == "websocket.receive":
            frame = msg["text"] if "text" in msg else msg["bytes"]
            try:
                req = json.loads(frame)
            except (TypeError, ValueError) as e:
                log.warning("live ui: a page frame that is not JSON (%s): %.200r", e, frame)
                continue
            subscribe = isinstance(req, dict) and req.get("op") == "subscribe"
            raw = req.get("symbols") if subscribe else None
            if not isinstance(raw, list):
                log.warning(
                    "live ui: a page frame that is not a subscribe with symbols: %.200r", frame
                )
                continue
            keys, identity = [], []
            for s in raw:
                k = ticker_storage_key(s) if isinstance(s, str) else ""
                if not k:
                    log.warning("live ui: a subscribed symbol not a string, or blank: %.200r", s)
                    continue
                identity.append({"requested": s, "key": k, "display": display_symbol(k)})
                if k not in keys:
                    keys.append(k)
            c.symbols = frozenset(keys)
            c.identity = identity  # what each asked-for symbol is, before its rows
            c.pending = set(keys)  # snapshot: the current row for each, now
            selected = req.get("ticker")
            c.ticker = None
            c.panels = set()
            if isinstance(selected, str) and selected.strip():
                c.ticker = ticker_storage_key(selected)
                c.panels = set(self.panels)  # snapshot: each panel's current body, now
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
            except Exception as e:  # a failed beat leaves the feed unproven (it ages out)
                log.warning("live ui heartbeat: %s: %s", type(e).__name__, e, exc_info=True)
                feed = None
            now = self.clock()
            for c in list(self.clients):
                # one browser can neither stop the beat nor hold it past a beat: an error is
                # logged and the next browser still gets its beat; a browser that does not take
                # its beat within a beat is not reading, and PageSocket drops it, which ends this
                # send
                try:
                    rows = [live_price_rows.price_row(s, now) for s in sorted(c.symbols)]
                    await self._send(c, {"type": "feed", "feed": feed, "rows": rows})
                except WebSocketDisconnect:  # its connection ended (a drop is PageSocket's log
                    # line), and its handler ends with it (serve_client's)
                    self.stats["beat_send_failures"] += 1
                except Exception as e:  # logged; the other browsers' beats go out
                    self.stats["beat_send_failures"] += 1
                    log.warning(
                        "live ui beat to one browser: %s: %s", type(e).__name__, e, exc_info=True
                    )
            await asyncio.sleep(HEARTBEAT_SEC)


#: the price server while the program serves the pages' socket (serve_live_ui); None before and
#: after
_serving: LiveUiServer | None = None


def changed(ticker: str, kind: str) -> None:
    """Mark panel `kind` of `ticker` (its key) changed for the pages on it.

    Callable from any thread: the pricing thread's producer calls it.
    """
    srv = _serving
    if srv is not None:
        srv.loop.call_soon_threadsafe(srv.on_change, ticker, kind)


async def page_socket(ws: WebSocket) -> None:
    """Serve the page's socket, /ws on the program's web server (server.app).

    Served while the program serves prices (serve_live_ui); refused before and after, and the
    page's reconnect keeps its schedule.
    """
    if _serving is None:
        await ws.close()
        return
    await ws.accept()
    await _serving.serve_client(ws)


async def serve_live_ui(
    stop: asyncio.Event,
    *,
    heartbeat_fn,
    panels: dict,
    stats: dict | None = None,
    record_heartbeat=lmp.record_feed_heartbeat,
    clock=time_et.now,
) -> None:
    """Serve the pages' price socket (page_socket) until `stop` is set.

    Each beat is recorded with `record_heartbeat` (the daemon's own plane); `panels` are the
    selected ticker's panels (server.PAGE_PANELS). The pages' connections end with the program's
    web server (capture.serve_console).
    """
    global _serving
    stats = stats if stats is not None else {}
    srv = LiveUiServer(heartbeat_fn, stats, record_heartbeat, clock, panels=panels)
    lmp.add_row_listener(srv.on_row)
    beats = asyncio.create_task(srv.beat_loop())
    srv.loop = asyncio.get_running_loop()
    _serving = srv
    log.info("live ui: serving price rows to the pages on /ws")
    try:
        await stop.wait()
    finally:
        _serving = None
        beats.cancel()
        await asyncio.gather(beats, return_exceptions=True)
        lmp.remove_row_listener(srv.on_row)
