"""Prices and chart bars straight from the capture daemon to the browser over WebSocket.

The daemon owns the Schwab connection. This server keeps the latest value of every
LEVELONE_EQUITIES field (live_market_plane, fed here in the daemon's own process), knows
whether the feed is alive (the daemon's own heartbeat, applied every HEARTBEAT_SEC), and
pushes the FINISHED displayed row (live_price_rows.price_row -- the one producer) to every
browser that asked for the symbol, the moment a Schwab message changes it. It keeps each
symbol's 1-minute bars of the day (Schwab CHART_EQUITY, live_price_rows.minute_bar; the day's
stored minutes of its symbols are loaded once, at startup) and pushes, for each new bar,
the chart bar it completes or extends at every chart timeframe (live_price_rows.bar_update).

No web server sits in this path, so no analytics load can delay a price.

Protocol (JSON text frames):
  browser -> {"op": "subscribe", "symbols": ["SPY", "AAPL", ...]}   (replaces the set; after a
             "disconnected_since": the last beat's feed.ts, when the   drop, the gap it has in
             browser comes back after a drop)                          its live bars is named)
  server  -> {"type": "bars_gap", "gap": {from_ts, to_ts, note}}     (on a subscribe after a
                                                                     drop: no bar is resent;
                                                                     the charts say they have
                                                                     no live bars for that time)
  server  -> {"type": "symbols", "symbols": [{requested, key, display}, ...]}  (on subscribe:
                                                                     what each asked-for symbol
                                                                     is -- "SPX" is key "$SPX",
                                                                     shown "SPX")
  server  -> {"type": "quotes", "rows": [price_row, ...]}            (snapshot on subscribe,
                                                                     then every change)
  server  -> {"type": "feed", "feed": {...}, "rows": [...]}           (every HEARTBEAT_SEC:
                                                                     the feed verdict and a
                                                                     fresh row per symbol, so
                                                                     a dead feed reads dead
                                                                     within FEED_HEARTBEAT_
                                                                     MAX_AGE_SEC)
  server  -> {"type": "bars", "bars": [bar_update, ...]}             (each completed minute of
                                                                     a subscribed symbol: its
                                                                     chart bar at every
                                                                     timeframe)

Rows are delivered latest-value-per-symbol per client (conflation, as Lightstreamer MERGE /
LSEG conflated feeds do): a slow browser gets the newest row for each symbol it is behind
on, never a queue of stale ones, and never loses a symbol's only update. Bars are not
conflated: every bar update is sent, in arrival order.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
from instrument_identity import display_symbol, ticker_storage_key
from stream_spine import COUNT_DROPS, MessageBus
from time_et import ET, ct_label

log = logging.getLogger(__name__)

#: The browser connects to this port on the console's own host name. Binds like the console
#: (0.0.0.0): the page is served to whatever address the operator opened it on.
LIVE_UI_HOST = os.environ.get("ED_LIVE_UI_HOST", "0.0.0.0")  # caps-ok: operator bind config with its declared default, not market data
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict + row beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0
#: a browser may watch at most this many symbols (the daemon holds ~50)
MAX_SYMBOLS_PER_CLIENT = 200


def _et_day_start(t: float) -> float:
    return datetime.fromtimestamp(t, ET).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def day_minutes(db_path: "str | Path", now: float) -> dict[str, tuple[float, dict[float, dict]]]:
    """The minutes the daemon starts with: the stored 1-minute bars (price_bars_1m) of every symbol
    with minutes on `now`'s ET day, as {symbol: (that day's start, {bar start: chart bar})} --
    every symbol, not only the ones streamed at startup, so a symbol the operator streams later
    in the day already holds the day the store holds. Read once, at the daemon's startup
    (capture.run), read-only; a read that fails stops the startup."""
    day = _et_day_start(now)
    con = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        rows = con.execute("SELECT ticker, bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
                           "WHERE bar_start_ts_utc>=?", (day,)).fetchall()
    finally:
        con.close()
    out: dict[str, tuple[float, dict[float, dict]]] = {}
    for tk, t, o, h, lo, c, v in rows:
        out.setdefault(tk, (day, {}))[1][t] = {"t": t, "o": o, "h": h, "l": lo, "c": c, "v": v}
    return out


class _Client:
    __slots__ = ("ws", "symbols", "pending", "bars", "gap", "identity", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.pending: set[str] = set()      # symbols changed since the last send
        self.bars: list[dict] = []          # the bar updates not yet sent, in arrival order
        self.gap: dict | None = None        # its live bars' gap after a drop, not yet sent
        self.identity: list[dict] | None = None   # the last subscribe's answer, not yet sent
        self.wake = asyncio.Event()


class LiveUiServer:
    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict, *, clock,
                 minutes: "dict[str, tuple[float, dict[float, dict]]] | None" = None) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        #: the entry point's clock (epoch seconds): every row, beat and gap is judged at its time
        self.clock = clock
        self.stats = stats
        self.clients: set[_Client] = set()
        #: each symbol's minutes of one ET day: (that day's start, {bar start: bar}); the day's
        #: stored minutes as loaded at startup, then only the ones Schwab streams
        self.minutes: dict[str, tuple[float, dict[float, dict]]] = minutes if minutes is not None else {}
        stats.update(clients=0, rows_sent=0, frames_sent=0, ingest_failures=0,
                     beat_send_failures=0, listening=None, last_send_ms=None, bars_sent=0)

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

    def on_bar(self, msg) -> None:
        """One daemon bar message -> the symbol's minutes of the day -> the chart bar it makes at
        every timeframe, for every browser watching the symbol. Held minutes are kept for the day
        whether the symbol is streamed or not (every symbol's stored minutes were loaded at
        startup); a new day starts empty. No stored minute is read here."""
        if not isinstance(msg, dict) or not msg.get("symbol"):
            return
        bar = live_price_rows.minute_bar(msg)
        if bar is None:
            return
        sym, day = ticker_storage_key(msg["symbol"]), _et_day_start(bar["t"])
        held = self.minutes.get(sym)
        if held is None or held[0] != day:
            held = self.minutes[sym] = (day, {})
        held[1][bar["t"]] = bar
        update = live_price_rows.bar_update(sym, sorted(held[1].values(), key=lambda m: m["t"]), bar,
                                            float(msg["ts_recv"]))
        for c in self.clients:
            if sym in c.symbols:
                c.bars.append(update)
                c.wake.set()

    @staticmethod
    def bars_gap(since: float, now: float) -> dict:
        """The gap in a browser's live bars after a drop: from the last beat it had (`since`),
        less two beats (a bar and a beat go out on their own tasks, so a bar received just before
        that beat may not have reached it), to `now`. Live bars are only the ones Schwab sends
        while the browser is connected: none received in the gap is resent."""
        start = since - 2 * HEARTBEAT_SEC
        return {"from_ts": start, "to_ts": now,
                "note": f"No live bars from {ct_label(start)} to {ct_label(now)}: this page was "
                        f"disconnected from the price feed, and bars completed then are not drawn. "
                        f"Reopening the chart loads the stored history."}

    def beat(self, now: float) -> dict:
        hb = self.heartbeat_fn()
        lmp.record_feed_heartbeat(hb, now)
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
            if c.identity is not None:
                identity, c.identity = c.identity, None
                await self._send(c, {"type": "symbols", "symbols": identity})
            syms, c.pending = c.pending, set()
            now = self.clock()
            rows = [live_price_rows.price_row(s, now) for s in syms if s in c.symbols]
            if rows:
                await self._send(c, {"type": "quotes", "rows": rows})
            if c.gap is not None:
                gap, c.gap = c.gap, None
                await self._send(c, {"type": "bars_gap", "gap": gap})
            bars, c.bars = c.bars, []
            bars = [b for b in bars if b["ticker"] in c.symbols]
            if bars:
                await self._send(c, {"type": "bars", "bars": bars})
                self.stats["bars_sent"] += len(bars)

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
            keys, identity = [], []
            for s in raw[:MAX_SYMBOLS_PER_CLIENT]:
                k = ticker_storage_key(s) if isinstance(s, str) else ""
                if not k:
                    continue
                identity.append({"requested": s, "key": k, "display": display_symbol(k)})
                if k not in keys:
                    keys.append(k)
            c.symbols = frozenset(keys)
            c.identity = identity            # what each asked-for symbol is, before its rows
            c.pending = set(keys)            # snapshot: the current row for each, now
            since = req.get("disconnected_since")   # a browser back from a drop
            if isinstance(since, (int, float)) and not isinstance(since, bool):
                c.gap = self.bars_gap(float(since), self.clock())
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
            now = self.clock()
            try:
                feed = self.beat(now)
            except Exception as e:  # noqa: BLE001 -- a failed beat leaves the feed unproven (it ages out)
                log.warning("live ui heartbeat: %s: %s", type(e).__name__, e)
                feed = None
            for c in list(self.clients):
                # one browser can neither stop the beat nor hold it: an error is logged and the
                # next browser still gets its beat; a browser that does not take its beat within
                # a beat is not reading and is closed (2026-09-26: the beat stopped for every
                # browser and the whole screen read "no live feed" on a healthy Schwab socket)
                try:
                    rows = [live_price_rows.price_row(s, now) for s in sorted(c.symbols)]
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


async def serve_live_ui(bus: MessageBus, stop: asyncio.Event, *, heartbeat_fn, clock,
                        host: str = LIVE_UI_HOST, port: int = LIVE_UI_PORT,
                        stats: "dict | None" = None,
                        minutes: "dict[str, tuple[float, dict[float, dict]]] | None" = None) -> None:
    """Run until `stop` is set. Start it BEFORE the Schwab connection so the plane sees the
    first messages (Schwab sends each field once, then only changes). `clock`: the entry
    point's clock (epoch seconds), the time every row, beat and gap is judged at. `minutes`:
    the day's stored minutes the daemon read at startup (day_minutes); after them a symbol's
    minutes are only the ones Schwab streams. Nothing here reads the database."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    srv = LiveUiServer(bus, heartbeat_fn, stats, clock=clock, minutes=minutes)
    for topic, msg in list(bus.snapshot().items()):         # whatever arrived before we started
        if topic.startswith("quote."):
            srv.ingest(msg)
    sub = bus.subscribe("quote.", policy=COUNT_DROPS, maxsize=65536, name="live_ui")
    bsub = bus.subscribe("bar1m.", policy=COUNT_DROPS, maxsize=8192, name="live_ui_bars")
    lmp.add_row_listener(srv.on_row)

    async def _track() -> None:
        while True:
            _topic, msg = await sub.get()
            srv.ingest(msg)

    async def _track_bars() -> None:
        while True:
            _topic, msg = await bsub.get()
            try:
                srv.on_bar(msg)
            except Exception as e:  # noqa: BLE001 -- counted; one bad bar never ends the feed
                srv.stats["ingest_failures"] += 1
                log.warning("live ui bar %s: %s: %s", msg.get("symbol") if isinstance(msg, dict) else None,
                            type(e).__name__, e)

    tasks = [asyncio.create_task(_track()), asyncio.create_task(_track_bars()),
             asyncio.create_task(srv.beat_loop())]
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
        bus.unsubscribe(bsub)
