"""Schwab's messages straight from the capture daemon to the screen (and the console) over
WebSocket, each pushed by its Schwab delivery type (Streamer API §1.1).

The daemon owns the Schwab connection. This server takes every Schwab stream message from the
daemon's bus, in the order published, as Schwab sent it, and pushes it to every client that asked
for its symbol:
  LEVELONE_EQUITIES, LEVELONE_OPTIONS  Change: only the fields that changed (a client behind
                                       gets each field's newest value, merged; none lost)
  NYSE_BOOK, NASDAQ_BOOK, OPTIONS_BOOK Whole: the whole book (a client behind gets the newest)
  CHART_EQUITY                         All Sequence: each bar with its SEQUENCE, every one, in order
  NEWS_HEADLINE                        each headline as sent, every one, in order (not in
                                       Schwab's Streamer document; Schwab answers it, code 0)
On subscribe a client gets each symbol's current record: every field Schwab has sent for a Change
service, the newest book, the newest bar and headline.

No web server sits in this path, so no analytics load can delay a price. Every second the beat
carries the daemon's status and, for each symbol the client asked for, each of its services'
verdict by the one live rule (live_market_plane.feed_live_for / outage, judged here on the daemon's
own status and on what Schwab posted to the symbol on the current connection) and the equity's
last trade time and age as the screen shows them (time_et.ct_label, age_label).

Protocol (JSON text frames):
  client -> {"op": "subscribe", "symbols": ["SPY", "SPY   261120C00700000", ...]}  (replaces the set)
  server -> {"type": "symbols", "symbols": [{requested, key, display}, ...]}  (on subscribe)
  server -> {"type": "schwab", "messages": [{service, key, schwab_ts, ts_recv, content}, ...]}
  server -> {"type": "feed", "feed": {...}, "state": {key: {service: {live, outage}}},
            "trades": {key: {time_ct, age}}}  (every HEARTBEAT_SEC)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import live_market_plane as lmp
from instrument_identity import display_symbol, ticker_storage_key
from live_price_rows import with_change
from micro_structure import bar_dict, schwab_bar
from numeric_contract import schwab_number
from stream_spine import LOG, MessageBus
from time_et import age_label, ct_label

log = logging.getLogger(__name__)

#: The screen and the console connect to this port, on this computer only (operator 2026-10-14:
#: "I only use this computer")
LIVE_UI_HOST = "127.0.0.1"
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0

#: Schwab's delivery type of each stream service (Streamer API §1.1; NEWS_HEADLINE is not listed
#: there and is pushed as sent, every one), and the bus topic kind and Schwab item key it rides
CHANGE, WHOLE, SEQUENCE = "Change", "Whole", "All Sequence"
DELIVERY = {"LEVELONE_EQUITIES": CHANGE, "LEVELONE_OPTIONS": CHANGE,
            "NYSE_BOOK": WHOLE, "NASDAQ_BOOK": WHOLE, "OPTIONS_BOOK": WHOLE,
            "CHART_EQUITY": SEQUENCE, "NEWS_HEADLINE": SEQUENCE}
_TOPIC_SERVICE = {"quote": ("LEVELONE_EQUITIES", "native"), "optquote": ("LEVELONE_OPTIONS", "content"),
                  "bar1m": ("CHART_EQUITY", "native"), "news": ("NEWS_HEADLINE", "content"),
                  "book": (None, "content")}
#: a NEWS_HEADLINE item's time field (epoch ms), as measured from Schwab's own items (the service is
#: not in Schwab's Streamer document; its items carry 1 = time, 2 = id, 4 = headline, 9 = source)
NEWS_TIME = "1"
#: the services a symbol's verdict is reported for, by kind of symbol
EQUITY_SERVICES = ("LEVELONE_EQUITIES", "NYSE_BOOK", "NASDAQ_BOOK", "CHART_EQUITY", "NEWS_HEADLINE")
OPTION_SERVICES = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def schwab_message(topic: str, msg: dict) -> "dict | None":
    """A bus message as the client gets it: its Schwab service, symbol, Schwab's frame time, the
    daemon's receive time and Schwab's item as sent; None for a topic that is not a stream service."""
    kind = topic.split(".", 1)[0]
    if kind not in _TOPIC_SERVICE or not isinstance(msg, dict) or not msg.get("symbol"):
        return None
    service, item_key = _TOPIC_SERVICE[kind]
    content = msg.get(item_key)
    if not isinstance(content, dict):
        return None
    out = {"service": service if service is not None else msg.get("service"), "key": msg["symbol"],
           "schwab_ts": msg.get("schwab_ts"), "ts_recv": msg.get("ts_recv"), "content": content}
    sent = schwab_number(content.get(NEWS_TIME) if out["service"] == "NEWS_HEADLINE"
                         else content.get("BOOK_TIME") if DELIVERY.get(out["service"]) == WHOLE else None)
    if sent is not None:
        out["time_ct"] = ct_label(sent / 1000.0)        # the headline's or book's time as the screen shows it
    if out["service"] == "CHART_EQUITY":                # the bar as the chart draws it, by its one producer
        candle = schwab_bar(content.get("CHART_TIME_MILLIS"), content.get("OPEN_PRICE"), content.get("HIGH_PRICE"),
                            content.get("LOW_PRICE"), content.get("CLOSE_PRICE"), content.get("VOLUME"))
        if candle is not None:
            out["bar"] = with_change(bar_dict(candle))
            out["time_ct"] = ct_label(candle.ts)
    return out


def _services(key: str) -> tuple:
    """The services a symbol is streamed on: an option contract's (Schwab's 21-character
    contract symbol) or an equity's."""
    return OPTION_SERVICES if len(key) == 21 and " " in key else EQUITY_SERVICES


class _Client:
    __slots__ = ("ws", "symbols", "change", "whole", "sequence", "identity", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.change: dict[tuple, dict] = {}       # (service, key) -> the changed fields not yet sent
        self.whole: dict[tuple, dict] = {}        # (service, key) -> the newest book not yet sent
        self.sequence: list[dict] = []            # every bar and headline not yet sent, in order
        self.identity: "list[dict] | None" = None   # the last subscribe's answer, not yet sent
        self.wake = asyncio.Event()

    def take(self, m: dict) -> None:
        """One Schwab message for this client, held by its delivery type until the next send."""
        kind = DELIVERY[m["service"]]
        k = (m["service"], m["key"])
        if kind == CHANGE:
            held = self.change.get(k)
            if held is None:
                self.change[k] = {**m, "content": dict(m["content"])}
            else:                     # newest value of each field; Schwab's newest frame time
                held["content"].update(m["content"])
                held["schwab_ts"], held["ts_recv"] = m["schwab_ts"], m["ts_recv"]
        elif kind == WHOLE:
            self.whole[k] = m
        else:
            self.sequence.append(m)
        self.wake.set()

    def drain(self) -> list[dict]:
        out = [*self.change.values(), *self.whole.values(), *self.sequence]
        self.change, self.whole, self.sequence = {}, {}, []
        return out


class LiveUiServer:
    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict, clock=time.time) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        self.clock = clock                           # each beat's instant (the verdicts are judged at it)
        self.stats = stats
        self.clients: set[_Client] = set()
        #: each equity's last trade time (Schwab's TRADE_TIME_MILLIS, as sent)
        self.trade_ms: dict[str, float] = {}
        stats.update(clients=0, messages_sent=0, frames_sent=0, beat_send_failures=0, listening=None,
                     last_send_ms=None)

    def route(self, topic: str, msg) -> None:
        """One Schwab message from the bus to every client that asked for its symbol, and noted as
        posted to the symbol on its service (the one live rule's "posted on this connection")."""
        m = schwab_message(topic, msg)
        if m is None:
            return
        if isinstance(m["ts_recv"], (int, float)):
            lmp.note_posted(m["key"], m["service"], m["ts_recv"])
        trade = schwab_number(m["content"].get("TRADE_TIME_MILLIS")) if m["service"] == "LEVELONE_EQUITIES" else None
        if trade is not None:
            self.trade_ms[m["key"]] = trade
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
        watchlist, health), recorded in the daemon's own live record (what each verdict is judged
        on) and sent with every beat."""
        hb = self.heartbeat_fn()
        lmp.record_feed_heartbeat(hb)
        return hb

    def state(self, c: _Client, now: float) -> dict:
        """For each symbol the client asked for, each of its services' verdict at `now`: live, and
        when not, why (live_market_plane: the one live rule)."""
        return {k: {svc: {"live": lmp.feed_live_for(k, svc, now), "outage": lmp.outage(k, svc, now)}
                    for svc in _services(k)} for k in sorted(c.symbols)}

    def trades(self, c: _Client, now: float) -> dict:
        """Each asked-for equity's last trade time and age at `now`, as the screen shows them."""
        return {k: {"time_ct": ct_label(self.trade_ms[k] / 1000.0), "age": age_label(now - self.trade_ms[k] / 1000.0)}
                for k in sorted(c.symbols) if k in self.trade_ms}

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
            if c.identity is not None:
                identity, c.identity = c.identity, None
                await self._send(c, {"type": "symbols", "symbols": identity})
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
            keys, identity = [], []
            for s in raw:
                k = ticker_storage_key(s) if isinstance(s, str) else ""
                if not k:
                    continue
                identity.append({"requested": s, "key": k, "display": display_symbol(k)})
                if k not in keys:
                    keys.append(k)
            added = [k for k in keys if k not in c.symbols]
            c.symbols = frozenset(keys)
            c.identity = identity            # what each asked-for symbol is, before its messages
            self.snapshot(c, added)
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
            now = self.clock()
            for c in list(self.clients):
                # one client can neither stop the beat nor hold it: an error is logged and the
                # next client still gets its beat; a client that does not take its beat within
                # a beat is not reading and is closed, and gets no more beats while it closes
                # (2026-09-26: the beat stopped for every client and the whole screen read "no
                # live feed" on a healthy Schwab socket)
                try:
                    await asyncio.wait_for(self._send(c, {"type": "feed", "feed": feed, "state": self.state(c, now),
                                                          "trades": self.trades(c, now)}), timeout=HEARTBEAT_SEC)
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
                        stats: "dict | None" = None, clock=time.time) -> None:
    """Run until `stop` is set. Start it BEFORE the Schwab connection so no message is missed."""
    from websockets.asyncio.server import serve

    stats = stats if stats is not None else {}
    srv = LiveUiServer(bus, heartbeat_fn, stats, clock)
    sub = bus.subscribe("", policy=LOG)                 # every message, in the order published

    async def _route() -> None:
        while True:
            topic, msg = await sub.get()
            try:
                srv.route(topic, msg)
            except Exception:  # noqa: BLE001 -- logged with the message; the next one is still delivered
                log.exception("live ui: a %s message was not delivered: %r", topic, msg)

    tasks = [asyncio.create_task(_route()), asyncio.create_task(srv.beat_loop())]
    try:
        async with serve(srv.serve_client, host, port, max_size=None, compression=None,
                         ping_interval=20, ping_timeout=20) as server:
            bound = server.sockets[0].getsockname()[1]  # the port taken (port 0: the system's pick)
            stats["listening"] = f"ws://{host}:{bound}"
            log.info("live ui: serving Schwab's messages on ws://%s:%s", host, bound)
            await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bus.unsubscribe(sub)
