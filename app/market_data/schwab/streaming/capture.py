"""The capture daemon: the ONE Schwab streaming connection (Schwab allows one per account).

    python -m app.market_data.schwab.streaming.capture          (start_capture_daemon.bat)

It is the only part of Ed Console that talks to Schwab. Beside the loop below, its chain sweep
(run_chains) fetches full option chains on its own threads, without end: the ticker on screen
first, back to back, and every universe ticker in turn.

  0. UNIVERSE Every ticker recorded, by one rule: every ticker with data stored in the
             databases (load_stored: in the universe while its lookup is pending) and every
             equity the console's screens show (its watchlist, the ticker on screen, the
             header's context: joins once listed) passes Schwab's instrument lookup (run_joins;
             the answer is recorded, so at the next start the ticker is read back as listed).
             Only Schwab's answer that does not list a ticker keeps or takes it out (its stored
             data stays as stored; the console shows the answer, status "not_joined"); an
             unknown never removes. Each is streamed on UNIVERSE_SERVICES and its chain is
             fetched in turn.

It does four things, in one loop:

  1. WANTED  The console sends everything its screens show, per Schwab service, over the
             local console socket (live_push, ws://127.0.0.1:8799):
               {"op": "wanted", "wanted": {"active": "SPY", "LEVELONE_EQUITIES": ["SPY", ...], ...}}
             `active` is its ticker on screen: the chain sweep fetches it first.
             The list lives in memory only: a daemon that starts streams the universe until
             the console says what its screens show.
  2. SYNC    When the list changes, and every SYNC_SEC, it compares wanted with what Schwab has accepted on this
             connection and sends the difference: UNSUBS for what is no longer wanted, then
             SUBS (the first request of a service) or ADD (every later one -- a repeated SUBS
             can replace the whole set). Requests are split so none exceeds Schwab's 64 KB
             message limit (measured 2026-09-22: a 71 KB request closed the socket).
             Schwab's answer to every request goes to the stream_subscriptions table: a
             refusal with Schwab's own code and message. A symbol Schwab refused is not asked
             for again until the console's list changes.
  3. FAN-OUT Every Schwab message is published once on the bus: the database writer
             (stream_capture.db), the console socket (8799) and the browser price socket
             (8800) all read from it.
  4. HEALTH  Any frame from Schwab -- data or Schwab's own heartbeat -- proves the connection
             is alive. None for DEAD_SEC: reconnect with backoff and resubscribe the wanted
             list. There is nothing else to recover.

What Schwab offers (probed live 2026-09-25): LEVELONE_EQUITIES, CHART_EQUITY, NYSE_BOOK
(exchange book), NASDAQ_BOOK (market-maker quotes), LEVELONE_OPTIONS, OPTIONS_BOOK and
NEWS_HEADLINE answer code 0; both books accepted 30 symbols. TIMESALE_* and ACTIVES_* answer
code 11 (not available) -- there is no trade-by-trade tape and no trade side.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import httpx
from authlib.common.errors import AuthlibBaseError
from schwab.streaming import UnparsableMessage

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from stream_spine import (  # noqa: E402
    LOG,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    current_key,
    bar_msg,
    book_msg,
    instrument_msg,
    news_msg,
    options_quote_msg,
    quote_msg,
    resolve_stream_db_path,
    subscription_msg,
)
from calibration.complete_chain_capture import CHAIN_WORKERS, ChainSweep  # noqa: E402
from instrument_identity import vendor_option_root  # noqa: E402
from time_et import now_et, session_label  # noqa: E402

log = logging.getLogger("capture")

#: The longest the connection reads Schwab's frames before comparing wanted with held again (a
#: change to the console's list is compared at once).
SYNC_SEC = 0.25
#: No frame at all from Schwab (data or heartbeat) for this long -> the connection is dead.
DEAD_SEC = 30.0
#: Reconnect waits, in order; the last repeats.
RECONNECT_BACKOFF_SEC = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
#: Schwab closes the socket on a request over 65,535 bytes; stay well under it.
MAX_REQUEST_BYTES = 48_000
#: A request Schwab does not answer in this long means the connection is broken.
REQUEST_TIMEOUT_SEC = 15.0

SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NYSE_BOOK", "NASDAQ_BOOK",
            "LEVELONE_OPTIONS", "OPTIONS_BOOK", "NEWS_HEADLINE")

#: LEVELONE_EQUITIES / CHART_EQUITY fields copied into the database's flat columns (the full
#: Schwab item is kept verbatim beside them in native_json).
LEVELONE_FIELDS = {"BID_PRICE": "bid", "ASK_PRICE": "ask", "LAST_PRICE": "last",
                   "BID_SIZE": "bid_size", "ASK_SIZE": "ask_size",
                   "TOTAL_VOLUME": "total_volume", "LAST_SIZE": "last_size",
                   "QUOTE_TIME_MILLIS": "quote_time_ms", "TRADE_TIME_MILLIS": "trade_time_ms"}
CHART_FIELDS = {"OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low",
                "CLOSE_PRICE": "close", "VOLUME": "volume", "CHART_TIME_MILLIS": "bar_start_ms"}
#: NEWS_HEADLINE is not in the Streamer Guide and schwab-py has no helper for it; these are
#: the fields it answered with on 2026-09-25 (time, id, ..., headline, ..., categories).
NEWS_FIELDS = tuple(range(0, 11))


# ---------------------------------------------------------------------------- the wanted list

def normalize_wanted(raw) -> "dict[str, frozenset[str]]":
    """{service: frozenset(symbols)} for the known services; anything else is ignored."""
    out: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
    if isinstance(raw, dict):
        for svc in SERVICES:
            syms = raw.get(svc)
            if isinstance(syms, list):
                out[svc] = frozenset(str(s).strip().upper() for s in syms if str(s).strip())
    return out


def wanted_active(raw) -> "str | None":
    """The console's ticker on screen, as its wanted list names it (`active`); None for none."""
    a = raw.get("active") if isinstance(raw, dict) else None
    return (a.strip().upper() or None) if isinstance(a, str) else None


def plan(wanted: "dict[str, frozenset[str]]", held: "dict[str, frozenset[str]]",
         refused: "dict[str, dict[str, str]]") -> "list[tuple[str, str, list[str]]]":
    """The Schwab requests that turn `held` into `wanted`: [(service, command, symbols)].
    Per service: UNSUBS what is held but not wanted, then SUBS (nothing held yet) or ADD the
    wanted symbols not held and not refused. Pure function -- the whole sync decision."""
    out: "list[tuple[str, str, list[str]]]" = []
    for svc in SERVICES:
        want, have = wanted.get(svc, frozenset()), held.get(svc, frozenset())
        drop = sorted(have - want)
        add = sorted(want - have - set(refused.get(svc, {})))
        if drop:
            out.append((svc, "UNSUBS", drop))
        if add:
            out.append((svc, "ADD" if have - set(drop) else "SUBS", add))
    return out


def split_request(symbols: "list[str]", max_bytes: int = MAX_REQUEST_BYTES) -> "list[list[str]]":
    """Chunks whose comma-joined key list stays under max_bytes."""
    chunks: "list[list[str]]" = []
    cur: "list[str]" = []
    size = 0
    for s in symbols:
        n = len(s) + 1
        if cur and size + n > max_bytes:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------- Schwab messages

#: each Schwab service's bus topic kind and the source its messages carry
SERVICE_TOPIC = {"LEVELONE_EQUITIES": ("quote", "schwab_l1"), "CHART_EQUITY": ("bar1m", "schwab_chart"),
                 "LEVELONE_OPTIONS": ("optquote", "schwab_options_l1"),
                 "NEWS_HEADLINE": ("news", "schwab_news"), "NYSE_BOOK": ("book", "schwab_book"),
                 "NASDAQ_BOOK": ("book", "schwab_book"), "OPTIONS_BOOK": ("book", "schwab_book")}


def _current_key(service: str, sym: str) -> str:
    """The bus's current-record key of `sym` on `service` (stream_spine.current_key)."""
    kind, src = SERVICE_TOPIC[service]
    return current_key(f"{kind}.{sym}", {"service": service, "src": src})


def _message(service: str, sym: str, item: dict, schwab_ts: "int | None") -> "tuple[str, dict]":
    """(topic kind, bus message) for one Schwab item, with the timestamp of Schwab's frame."""
    kind, src = SERVICE_TOPIC[service]
    if service == "LEVELONE_EQUITIES":
        flat = {name: item.get(k) for k, name in LEVELONE_FIELDS.items()}
        return kind, quote_msg(symbol=sym, src=src, native=item, schwab_ts=schwab_ts, **flat)
    if service == "CHART_EQUITY":
        flat = {name: item.get(k) for k, name in CHART_FIELDS.items()}
        return kind, bar_msg(symbol=sym, src=src, native=item, schwab_ts=schwab_ts, **flat)
    if service == "LEVELONE_OPTIONS":
        return kind, options_quote_msg(symbol=sym, content=item, src=src, schwab_ts=schwab_ts)
    if service == "NEWS_HEADLINE":
        return kind, news_msg(symbol=sym, content=item, src=src, schwab_ts=schwab_ts)
    return kind, book_msg(symbol=sym, service=service, content=item, src=src, schwab_ts=schwab_ts)


def _publisher(service: str, bus: MessageBus, health: HealthRegistry):
    """schwab-py handler for one service: every item -> the bus, with the timestamp Schwab put on
    the frame. The service counts as alive only when a frame delivered data, not merely arrived."""
    def handler(msg: dict) -> None:
        published = False
        schwab_ts = msg.get("timestamp")
        for item in msg.get("content") or []:
            sym = str(item.get("key") or "").upper() if isinstance(item, dict) else ""
            if sym:
                kind, out = _message(service, sym, item, schwab_ts)
                bus.publish(f"{kind}.{sym}", out)
                published = True
        if published:
            health.beat(service)
    return handler


class _RawHandler:
    """schwab-py handler shape for a service it has no helper for (NEWS_HEADLINE). schwab-py
    calls label_message on every handler of every frame; without it the call raised and the rest
    of the frame -- prices included -- was dropped ("skipped a frame", 2026-09-26)."""

    def __init__(self, fn) -> None:
        self.fn = fn

    def label_message(self, msg: dict) -> dict:
        return msg                                   # as sent

    def __call__(self, msg: dict):
        return self.fn(msg)


def _open_stream(client):
    """schwab-py's StreamClient, recording the time of every frame Schwab sends -- data,
    responses and Schwab's heartbeats alike. That one timestamp is the liveness test."""
    from schwab.streaming import StreamClient
    stream = StreamClient(client)
    stream.last_frame_ts = time.time()
    receive = stream._receive

    async def timed_receive():
        msg = await receive()
        stream.last_frame_ts = time.time()
        return msg
    stream._receive = timed_receive
    return stream


def _fields(stream, service: str) -> str:
    if service == "NEWS_HEADLINE":
        return ",".join(str(f) for f in NEWS_FIELDS)
    enum = {"LEVELONE_EQUITIES": stream.LevelOneEquityFields,
            "CHART_EQUITY": stream.ChartEquityFields,
            "LEVELONE_OPTIONS": stream.LevelOneOptionFields}.get(service, stream.BookFields)
    return ",".join(str(f) for f in sorted(int(x.value) for x in enum))


async def _request(stream, service: str, command: str, symbols: "list[str]") -> dict:
    """One Schwab request and Schwab's answer to it: the `content` of the response whose
    `requestid` is this request's ({"code": ..., "msg": ...}, as sent). Every service goes
    through this one path, including NEWS_HEADLINE. Raises only when the connection fails or
    Schwab does not answer in REQUEST_TIMEOUT_SEC."""
    params = {"keys": ",".join(symbols)}
    if command != "UNSUBS":
        params["fields"] = _fields(stream, service)
    req, rid = stream._make_request(service=service, command=command, parameters=params)

    async def send_and_wait() -> dict:
        async with stream._lock:
            await stream._send({"requests": [req]})
            return await _answer(stream, rid)
    try:
        return await asyncio.wait_for(send_and_wait(), timeout=REQUEST_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise ConnectionError(f"no answer to {service} {command} in {REQUEST_TIMEOUT_SEC:.0f} s") from None


async def _answer(stream, request_id: int) -> dict:
    """Read Schwab's frames until the response to request `request_id`; return its `content`.
    A response to another request is not this request's answer: it is logged and passed over.
    Data frames read meanwhile are handed back to schwab-py's queue for handle_message, in
    order. A frame that is not JSON is logged with its text and passed over (schwab-py:
    "This often happens with unknown symbols"); it never ends the connection."""
    deferred = []
    try:
        while True:
            try:
                frame = await stream._receive()
            except UnparsableMessage as e:
                log.warning("schwab: a frame that is not JSON, passed over: %s", str(e.raw_msg)[:300])
                continue
            if "response" not in frame:
                deferred.append(frame)
                continue
            for answer in frame["response"]:
                if int(answer["requestid"]) == request_id:
                    return answer["content"]
                log.info("schwab: an answer to request %s (not %d), passed over: %s",
                         answer["requestid"], request_id, json.dumps(answer)[:300])
    finally:
        stream._overflow_items.extendleft(deferred)


def _connection_lost(e: BaseException) -> bool:
    """The socket itself is gone (as opposed to Schwab refusing one request)."""
    from websockets.exceptions import ConnectionClosed
    return isinstance(e, (ConnectionClosed, ConnectionError, OSError, asyncio.IncompleteReadError))


# ---------------------------------------------------------------------------- the daemon

#: The services every universe ticker is streamed on, beside whatever the console's screens
#: show: the equity services. A ticker the console's list names on one of them, or as its
#: ticker on screen, is looked up to join the universe.
UNIVERSE_SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE", "NYSE_BOOK", "NASDAQ_BOOK")


#: Schwab's streamer code for a SUBS or ADD that reached the service's symbol limit (Streamer Guide
#: §1.4 Response Codes: 19 REACHED_SYMBOL_LIMIT, connection not severed). Schwab keeps up to its
#: limit and discards the rest without naming which (2026-10-04: "LEVELONE_OPTIONS=3000,
#: DISCARDED=1363"), so the request's symbols are held -- unsubscribed when no longer wanted --
#: and Schwab's message is the service's state, not a refusal of each symbol.
REACHED_SYMBOL_LIMIT = 19


class Daemon:
    def __init__(self, bus: MessageBus, health: HealthRegistry, universe: "tuple[str, ...] | list[str]" = ()) -> None:
        """`universe`: tickers to stream from the start (a test's; the daemon's own come from
        load, once the stored tickers are read)."""
        self.bus = bus
        self.health = health
        #: what the console's screens show, as it last said (none until it says)
        self.wanted = normalize_wanted(None)
        #: the console's ticker on screen: its chain is fetched first (ChainSweep.set_active)
        self.active: "str | None" = None
        #: the console connection whose list this is (live_push's socket)
        self.sender = None
        self.wanted_changed = asyncio.Event()
        #: the universe: every ticker streamed on UNIVERSE_SERVICES and fetched in turn (every
        #: ticker with data stored, from load; every ticker a screen shows once Schwab lists it);
        #: the chain sweep reads this same list
        self.universe: "list[str]" = sorted(set(universe))
        #: the tickers Schwab's instrument answer lists (recorded, or answered this run), and the
        #: ones an answer this run did not list
        self.listed: "set[str]" = set()
        self.not_listed: "set[str]" = set()
        #: the tickers to look up (run_joins takes them), each put once: `asked` holds every
        #: ticker put, until a lookup that got no answer from Schwab (then `unanswered`, asked
        #: again on the next connection to Schwab)
        self.joins: "asyncio.Queue[str]" = asyncio.Queue()
        self.asked: "set[str]" = set()
        self.unanswered: "set[str]" = set()
        #: {ticker: Schwab's answer} for each ticker looked up that is not in the universe
        self.not_joined: "dict[str, str]" = {}
        self.chains = None                  # the ChainSweep: its round time, its active ticker
        self.held: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
        self.refused: "dict[str, dict[str, str]]" = {s: {} for s in SERVICES}
        #: {service: Schwab's message} for a service whose symbol limit Schwab reported
        #: (REACHED_SYMBOL_LIMIT), on this connection
        self.limits: "dict[str, str]" = {}
        self.stream = None
        #: the market session the last sync ran in (time_et.session_label): a new one is a new try
        self.session: "str | None" = None

    def load(self, listed: "list[str]", unconfirmed: "list[str]") -> None:
        """The stored tickers (recorded_tickers), read after the daemon started: every one is in
        the universe from now -- its record goes on while its lookup is pending -- and each no
        recorded answer of Schwab's lists is looked up. Only Schwab's answer that does not list
        a ticker takes it out (answered); one already answered so this run stays out."""
        self.listed.update(listed)
        for ticker in sorted((set(listed) | set(unconfirmed)) - self.not_listed):
            self.join(ticker)
        self.ask(unconfirmed)

    def ask(self, tickers) -> None:
        """Put each of `tickers` Schwab has not listed and not already asked to Schwab's
        instrument lookup (run_joins takes them in order)."""
        for ticker in sorted(set(tickers) - self.listed - self.asked):
            self.asked.add(ticker)
            self.joins.put_nowait(ticker)

    def reconnected(self) -> None:
        """A new connection to Schwab: every lookup that got no answer is asked again."""
        unanswered, self.unanswered = self.unanswered, set()
        self.ask(unanswered)

    def new_session(self, label: str) -> None:
        """The market session is `label` (time_et.session_label, read by the connection's loop):
        when it changes, every symbol Schwab refused is asked for again -- every ticker gets the
        same services, every session."""
        if label == self.session:
            return
        self.session = label
        self.refused = {s: {} for s in SERVICES}
        self.wanted_changed.set()

    def set_wanted(self, raw, sender=None) -> None:
        """The console's list from connection `sender` (live_push calls this for every
        {"op": "wanted"} frame): what its screens show, and `active`, its ticker on screen, which
        the chain sweep fetches first. `raw` None: that connection ended, and withdraws the list
        only if the list is its own (another connection's later list stands)."""
        if raw is None and sender is not self.sender:
            return
        self.sender = None if raw is None else sender
        new, active = normalize_wanted(raw), wanted_active(raw)
        if new == self.wanted and active == self.active:
            return
        for svc in SERVICES:                       # a changed list gets one fresh try
            if new[svc] != self.wanted[svc]:
                self.refused[svc] = {}
        self.wanted, self.active = new, active
        self.wanted_changed.set()                  # the connection syncs now
        if self.chains is not None:
            self.chains.set_active(active)
        self.ask(set().union(*(new[svc] for svc in UNIVERSE_SERVICES)) | ({active} if active else set()))

    def answered(self, msg: dict) -> None:
        """Schwab's instrument answer for a ticker looked up (instrument_answer), recorded.
        Listed: the ticker is in the universe for good. An `instruments` list without it:
        Schwab does not list it -- it leaves the universe (its stored data stays as stored) and
        the answer is what the console shows for it. Anything else (`listed` None: another
        status, a body that is not JSON or carries no `instruments` list) is no answer
        (no_answer): nothing changes."""
        ticker = msg["symbol"]
        self.bus.publish(f"instrument.{ticker}", msg)
        if msg["listed"] is None:
            self.no_answer(ticker, f"Schwab's instrument lookup did not answer for {ticker} "
                                   f"(HTTP {msg['http_status']}: {msg['body'][:300]})")
        elif msg["listed"]:
            self.listed.add(ticker)
            self.not_listed.discard(ticker)
            self.not_joined.pop(ticker, None)
            self.join(ticker)
        else:
            self.not_listed.add(ticker)
            self.not_joined[ticker] = (f"Schwab's instrument lookup does not list {ticker} "
                                       f"(HTTP {msg['http_status']}: {msg['body'][:300]})")
            self.leave(ticker)

    def no_answer(self, ticker: str, reason: str) -> None:
        """The lookup of `ticker` got no answer from Schwab: an unknown, so nothing changes -- a
        ticker in the universe stays, one outside stays out with `reason` shown -- and it is
        asked again on the next connection to Schwab (reconnected)."""
        self.asked.discard(ticker)
        self.unanswered.add(ticker)
        if ticker not in self.universe:
            self.not_joined[ticker] = reason

    def join(self, ticker: str) -> None:
        """`ticker` is in the universe: streamed on UNIVERSE_SERVICES (each gets one fresh try)
        and fetched in turn by the chain sweep (while Closed, once)."""
        if ticker in self.universe:
            return
        self.universe.append(ticker)
        for svc in UNIVERSE_SERVICES:
            self.refused[svc].pop(ticker, None)
        if self.chains is not None:
            self.chains.joined(ticker)
        self.wanted_changed.set()                  # the connection streams it now

    def leave(self, ticker: str) -> None:
        """Schwab does not list `ticker`: it leaves the universe -- unsubscribed on the next sync
        unless a screen still shows it, and out of the chain sweep."""
        if ticker not in self.universe:
            return
        self.universe.remove(ticker)
        if self.chains is not None:
            self.chains.left(ticker)
        self.wanted_changed.set()

    def all_wanted(self) -> "dict[str, frozenset[str]]":
        """Everything streamed: the console's list, and every universe ticker on UNIVERSE_SERVICES."""
        out = dict(self.wanted)
        for svc in UNIVERSE_SERVICES:
            out[svc] = out[svc] | frozenset(self.universe)
        return out

    def status(self) -> dict:
        """What the console and browsers are told every second (live_push / live_ui)."""
        now = time.time()
        last = self.stream.last_frame_ts if self.stream is not None else 0.0
        return {"ts": now,
                "schwab_socket_open": bool(last) and now - last < DEAD_SEC,
                "universe": sorted(self.universe),
                "not_joined": dict(self.not_joined),
                "chain_round_sec": self.chains.round_sec if self.chains is not None else None,
                "held": {k: sorted(v) for k, v in self.held.items()},
                "refused": {k: dict(v) for k, v in self.refused.items() if v},
                "limits": dict(self.limits),
                "health": self.health.report(now)}

    async def sync(self) -> None:
        for svc, cmd, symbols in plan(self.all_wanted(), self.held, self.refused):
            for chunk in split_request(symbols):
                answer = await _request(self.stream, svc, cmd, chunk)   # Schwab's code, its message
                code, reason = answer["code"], answer["msg"]
                self.bus.publish(f"sub.{svc}", subscription_msg(
                    service=svc, command=cmd, symbols=chunk, code=code, reason=reason))
                if code == 0 or (code == REACHED_SYMBOL_LIMIT and cmd != "UNSUBS"):
                    held = set(self.held[svc])
                    held = held - set(chunk) if cmd == "UNSUBS" else held | set(chunk)
                    self.held[svc] = frozenset(held)
                    if cmd == "UNSUBS":             # no longer held: no longer current
                        for sym in chunk:
                            self.bus.forget(_current_key(svc, sym))
                    if code == REACHED_SYMBOL_LIMIT:  # Schwab kept some, not saying which
                        log.warning("%s %s (%d symbols): Schwab's symbol limit: %s", svc, cmd, len(chunk), reason)
                        self.limits[svc] = f"code {code}: {reason}"
                else:
                    log.warning("%s %s refused (%d symbols): code %s: %s", svc, cmd, len(chunk), code, reason)
                    if cmd != "UNSUBS":
                        self.refused[svc].update({sym: f"code {code}: {reason}" for sym in chunk})

    async def connect(self, client) -> None:
        stream = _open_stream(client)
        # every message Schwab sends, whatever its size: the websockets library caps a received
        # message at 1 MiB by default, and nothing of ours does
        await stream.login(websocket_connect_args={"max_size": None})
        for svc, add in (("LEVELONE_EQUITIES", stream.add_level_one_equity_handler),
                         ("CHART_EQUITY", stream.add_chart_equity_handler),
                         ("NYSE_BOOK", stream.add_nyse_book_handler),
                         ("NASDAQ_BOOK", stream.add_nasdaq_book_handler),
                         ("OPTIONS_BOOK", stream.add_options_book_handler),
                         ("LEVELONE_OPTIONS", stream.add_level_one_option_handler)):
            add(_publisher(svc, self.bus, self.health))
        stream._handlers["NEWS_HEADLINE"].append(_RawHandler(_publisher("NEWS_HEADLINE", self.bus, self.health)))
        self.stream = stream
        self.held = {s: frozenset() for s in SERVICES}    # a new connection holds nothing
        self.limits = {}
        log.info("schwab: connected")
        self.reconnected()

    async def disconnect(self) -> None:
        s, self.stream = self.stream, None
        self.held = {k: frozenset() for k in SERVICES}
        if s is not None:
            try:
                await asyncio.wait_for(s.logout(), timeout=5)
            except Exception as e:  # noqa: BLE001 -- the session is dropped either way
                log.info("schwab: logout of the old session failed (%s: %s)", type(e).__name__, e)

    async def read_for(self, seconds: float) -> None:
        """Handle Schwab frames for `seconds`, or until the console's list changes. One task does
        both reading and requesting, so a request never waits behind a reader holding schwab-py's
        lock (websockets' recv is safe to cancel, so ending early never loses a frame)."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0 and not self.wanted_changed.is_set():
            frame = asyncio.ensure_future(self.stream.handle_message())
            change = asyncio.ensure_future(self.wanted_changed.wait())
            await asyncio.wait({frame, change}, timeout=left, return_when=asyncio.FIRST_COMPLETED)
            change.cancel()
            if not frame.done():
                frame.cancel()
                await asyncio.gather(frame, return_exceptions=True)
                return
            e = frame.exception()
            if e is not None:
                if _connection_lost(e):
                    raise e
                log.warning("schwab: skipped a frame (%s: %s)", type(e).__name__, str(e)[:250])

    async def run_connection(self, client, stop: asyncio.Event) -> None:
        """One connection's life: sync, read, repeat -- until it dies or stop is set."""
        await self.connect(client)
        try:
            while not stop.is_set():
                if time.time() - self.stream.last_frame_ts > DEAD_SEC:
                    raise ConnectionError(f"no frame from Schwab for {DEAD_SEC:.0f} s")
                self.wanted_changed.clear()
                self.new_session(session_label(now_et()))
                await self.sync()
                await self.read_for(SYNC_SEC)
        finally:
            await self.disconnect()

    async def run(self, schwab_client, stop: asyncio.Event) -> None:
        """Connect, and reconnect with backoff whenever the connection ends, until stop, on the
        daemon's one Schwab client (`schwab_client()`)."""
        failures = 0
        while not stop.is_set():
            started = time.time()
            try:
                await self.run_connection(schwab_client(), stop)
            except Exception as e:  # noqa: BLE001 -- every failure is a reconnect
                log.warning("schwab: connection ended (%s: %s)", type(e).__name__, str(e)[:350])
            if stop.is_set():
                break
            # a connection that lasted 5 minutes starts the backoff over
            failures = 1 if time.time() - started > 300 else failures + 1
            wait = RECONNECT_BACKOFF_SEC[min(failures, len(RECONNECT_BACKOFF_SEC)) - 1]
            log.info("schwab: reconnecting in %.0f s", wait)
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


# ---------------------------------------------------------------------------- process

def owner_lock_path(db_path: "str | Path | None" = None) -> Path:
    """Beside the stream database, so a worktree and production can never both stream."""
    return resolve_stream_db_path(db_path).with_name("stream_capture.lock")


#: Exit code when another daemon already owns the stream (start_capture_daemon.bat stops its
#: restart loop on it). 2 is the live-binding refusal (runtime_layout).
EXIT_OWNER_LOCK_HELD = 3


def acquire_owner_lock(db_path: "str | Path | None" = None) -> "tuple[int, Path]":
    """Exclusive pidfile: one daemon at a time; a lock left by a dead process is reclaimed."""
    import psutil
    lock = owner_lock_path(db_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return fd, lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)  # caps-ok: an empty pidfile is not a live owner
            except (OSError, ValueError):
                pid = 0
            if pid and psutil.pid_exists(pid):
                print(f"FATAL: another capture daemon holds {lock} (pid {pid}).", file=sys.stderr)
                raise SystemExit(EXIT_OWNER_LOCK_HELD) from None
            if attempt == 1:
                lock.unlink(missing_ok=True)
    raise SystemExit(f"FATAL: could not acquire {lock}")


def release_owner_lock(fd: int, lock: Path) -> None:
    try:
        os.close(fd)
    finally:
        lock.unlink(missing_ok=True)


def _start_log() -> None:
    """Every line to <runtime>/logs/stream_capture.log (kept: under pythonw there is no console,
    and 2026-09-23's 42 socket deaths left no reason on disk), and to the console if any."""
    from logging.handlers import RotatingFileHandler
    from runtime_layout import logs_dir
    path = logs_dir() / "stream_capture.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: "list[logging.Handler]" = [RotatingFileHandler(path, maxBytes=50 * 1024 * 1024,
                                                             backupCount=1, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


FEED_STATUS_EVERY_SEC = 60.0


async def record_feed_status(daemon: "Daemon", stop: asyncio.Event) -> None:
    """Once a minute, per Schwab feed: checked at X (the same X for every feed), is the socket
    open, when Schwab last sent anything, how many symbols are subscribed, and when this feed
    last carried data -- so a quiet feed and a dead one read differently in the database."""
    while True:
        now = time.time()
        try:
            last_frame = daemon.stream.last_frame_ts if daemon.stream is not None else None
            st = daemon.status()
            for svc in SERVICES:
                daemon.bus.publish(f"feedstatus.{svc}", {
                    "ts": now, "service": svc, "socket_open": st["schwab_socket_open"],
                    "schwab_last_frame_ts": last_frame or None,
                    "held": len(daemon.held.get(svc) or ()),
                    "last_data_ts": daemon.health.last(svc)})
        except Exception as e:  # noqa: BLE001 -- this round's rows are missing and the log says
            # why; the next round still runs (the console's status line reports the record's age)
            log.warning("feed status round failed: %s: %s", type(e).__name__, e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=FEED_STATUS_EVERY_SEC)
            return
        except asyncio.TimeoutError:
            pass


async def run_chains(daemon: "Daemon", db_path, schwab_client, stop: asyncio.Event) -> None:
    """The chain sweep (calibration.complete_chain_capture.ChainSweep) on its own threads, so the
    stream never waits on a chain; each chain part is published on the event loop, and the bus
    keeps each ticker's newest whole chain (stream_spine.MessageBus._chain)."""
    loop = asyncio.get_running_loop()
    halt = threading.Event()
    sweep = ChainSweep(db_path, daemon.universe,
                       lambda topic, msg: loop.call_soon_threadsafe(daemon.bus.publish, topic, msg))
    daemon.chains = sweep
    sweep.set_active(daemon.active)                 # the ticker on screen, if the console said one
    workers = [loop.run_in_executor(None, sweep.work, schwab_client, halt) for _ in range(CHAIN_WORKERS)]
    try:
        await stop.wait()
    finally:
        halt.set()
        await asyncio.gather(*workers, return_exceptions=True)


def recorded_tickers(*db_paths: "Path | str") -> "tuple[list[str], list[str]]":
    """(listed, unconfirmed), read-only from the databases `db_paths`. `listed`: every ticker
    whose newest recorded instrument answer (stream_instruments_raw) lists it -- the universe at
    start. `unconfirmed`: every other ticker with data stored -- the distinct values of every
    table's `ticker` or `symbol` column, each read through its index one value at a time,
    quarantine tables included (Records stand keeps them; their tickers pass the lookup like
    every other) -- each to be looked up. Left out: an option contract's symbol (OSI form: a
    contract, not a ticker) and the `world_` tables (public datasets from other sources, not
    data recorded for a ticker). A database that does not exist yet holds none."""
    stored: "set[str]" = set()
    newest: "dict[str, int]" = {}
    for db in db_paths:
        if not Path(db).is_file():
            log.warning("universe: %s does not exist yet: no ticker stored there", db)
            continue
        conn = sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                 "AND name NOT LIKE 'world\\_%' ESCAPE '\\'")]
            for table in tables:
                if table == "stream_instruments_raw":
                    newest.update(conn.execute("SELECT symbol, listed FROM stream_instruments_raw ORDER BY ts"))
                    continue
                for (col,) in conn.execute(f'SELECT name FROM pragma_table_info("{table}") '
                                           "WHERE name IN ('ticker', 'symbol')").fetchall():
                    stored.update(v for (v,) in conn.execute(
                        f'WITH RECURSIVE s(v) AS (SELECT MIN("{col}") FROM "{table}" '
                        f'UNION ALL SELECT (SELECT MIN("{col}") FROM "{table}" WHERE "{col}" > s.v) '
                        "FROM s WHERE s.v IS NOT NULL) SELECT v FROM s WHERE v IS NOT NULL"))
        finally:
            conn.close()
    listed = {t for t, yes in newest.items() if yes}
    stored = {t for t in stored | set(newest) if isinstance(t, str) and t and not vendor_option_root(t)}
    return sorted(listed), sorted(stored - listed)


def instrument_answer(client, symbol: str, now: float) -> dict:
    """Schwab's instrument lookup of `symbol` on the daemon's one client (schwab-py
    Client.get_instruments, projection SYMBOL_SEARCH: GET /marketdata/v1/instruments), as its
    instrument message: the HTTP status and body as sent, and `listed`: True when the answer's
    `instruments` list of objects holds one whose `symbol` is exactly `symbol`, False when it is
    such a list without it (Schwab does not list it), None for every other answer -- a list
    holding anything but objects (not the shape Schwab answers), another
    status, a body that is not JSON, or JSON without an `instruments` list: no answer."""
    resp = client.get_instruments(symbol, client.Instrument.Projection.SYMBOL_SEARCH)
    body = None
    if resp.status_code == 200:
        try:
            body = json.loads(resp.text)
        except ValueError as e:                    # recorded as sent; no answer
            log.warning("universe: Schwab's instrument answer for %s is not JSON: %s", symbol, e)
    instruments = body.get("instruments") if isinstance(body, dict) else None
    answered = isinstance(instruments, list) and all(isinstance(i, dict) for i in instruments)
    listed = any(i.get("symbol") == symbol for i in instruments) if answered else None
    return instrument_msg(symbol=symbol, http_status=resp.status_code, body=resp.text, listed=listed, ts=now)


#: what a lookup that got no answer from Schwab raises: the network (httpx), no client
#: (one_schwab_client: ConnectionError), the token refused (authlib). Anything else is ours and
#: ends run_joins with its traceback in the log.
NO_ANSWER = (httpx.HTTPError, ConnectionError, AuthlibBaseError)


async def run_joins(daemon: "Daemon", schwab_client, stop: asyncio.Event) -> None:
    """The universe's joins: each ticker put to the lookup (Daemon.ask: a stored ticker no
    recorded answer lists, at start and each session; a ticker the console's list names), looked
    up with Schwab as it is put, on the daemon's one client (`schwab_client()`), until stop. A
    lookup Schwab gave no answer to (NO_ANSWER) is logged, shown as the ticker's reason, and
    tried again later (Daemon.answered)."""
    while not stop.is_set():
        took = asyncio.ensure_future(daemon.joins.get())
        stopped = asyncio.ensure_future(stop.wait())
        await asyncio.wait({took, stopped}, return_when=asyncio.FIRST_COMPLETED)
        stopped.cancel()
        if not took.done():
            took.cancel()
            return
        ticker = took.result()
        try:
            daemon.answered(await asyncio.to_thread(instrument_answer, schwab_client(), ticker, time.time()))
        except NO_ANSWER as e:
            log.warning("universe: no instrument answer for %s: %s: %s", ticker, type(e).__name__, e)
            daemon.no_answer(ticker, f"Schwab's instrument lookup did not answer for {ticker}: "
                                     f"{type(e).__name__}: {e}")


def one_schwab_client(build) -> "callable":
    """The daemon's one Schwab client, for the stream and every chain request, as a function
    that returns it: built (`build()`, a SchwabClientState) when first asked for, then kept for
    the daemon's life. Its session is the one owner of the token: it refreshes it (one refresh
    at a time, schwab_client.OneRefreshSession) and writes it to the token file. A build that
    fails raises, and the next ask builds again; a built client is never replaced."""
    built: list = []
    building = threading.Lock()

    def schwab_client():
        with building:
            if not built:
                state = build()
                if not state.ok or state.client is None:
                    raise ConnectionError(f"no Schwab client ({state.message})")
                built.append(state.client)
            return built[0]
    return schwab_client


async def run() -> int:
    """The whole daemon: writer, the two local sockets, the chain sweep, the universe's joins
    and the Schwab connection."""
    from app.market_data.schwab.streaming.live_push import serve_live_push
    from app.market_data.schwab.streaming.live_ui import serve_live_ui
    from config import build_config, load_dotenv_file
    from db_authority import canonical_console_db_path
    from schwab_client import build_client_from_token
    load_dotenv_file()
    cfg = build_config()
    schwab_client = one_schwab_client(lambda: build_client_from_token(
        api_key=cfg.api_key, app_secret=cfg.app_secret, token_path=cfg.token_path))
    stop = asyncio.Event()
    bus, health = MessageBus(), HealthRegistry()
    writer = CaptureWriter()
    db_path = canonical_console_db_path()
    daemon = Daemon(bus, health)
    wsub = bus.subscribe("", policy=LOG)                # the record of every message
    return await supervise(stop, [
        writer.run(wsub, stop=stop),
        serve_live_push(bus, stop, on_wanted=daemon.set_wanted),
        serve_live_ui(bus, stop, heartbeat_fn=daemon.status),
        run_chains(daemon, db_path, schwab_client, stop),
        run_joins(daemon, schwab_client, stop),
        record_feed_status(daemon, stop),
        load_stored(daemon, db_path, writer.db_path),
        daemon.run(schwab_client, stop)])


async def load_stored(daemon: "Daemon", *db_paths) -> None:
    """The stored tickers (recorded_tickers: 5-20 s on production, 2026-10-05), read off the
    event loop while the connection already streams what the console shows; then the daemon
    streams and looks them up (Daemon.load)."""
    listed, unconfirmed = await asyncio.to_thread(recorded_tickers, *db_paths)
    daemon.load(listed, unconfirmed)
    log.info("universe: %d tickers stored (%d listed by a recorded answer of Schwab's; %d to look up)",
             len(listed) + len(unconfirmed), len(listed), len(unconfirmed))


async def supervise(stop: asyncio.Event, parts: list) -> int:
    """Run the daemon's parts until `stop` is set or one of them fails. A part that ends with an
    error is ours: its traceback is logged, every part is stopped, and the daemon exits 1, so
    start_capture_daemon.bat starts it again. 0 after a stop."""
    tasks = [asyncio.ensure_future(p) for p in parts]
    failed = 0
    try:
        await asyncio.sleep(0)                    # servers subscribe before the first message
        pending = set(tasks)
        while pending and not stop.is_set():
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.cancelled() and t.exception() is not None:
                    log.error("daemon: a part ended with an error; the daemon exits",
                              exc_info=t.exception())
                    failed = 1
            if failed:
                break
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return failed


def main() -> int:
    if sys.argv[1:]:        # everything it needs comes from the console; no switch can move it
        print(f"the capture daemon takes no arguments (got {sys.argv[1:]})", file=sys.stderr)
        return 2
    # A worktree must not run a live daemon against production's runtime
    # (runtime_layout.live_binding_error, 2026-09-25).
    from runtime_layout import live_binding_error
    binding = live_binding_error()
    if binding is not None:
        print(f"CAPTURE DAEMON REFUSED: {binding}", file=sys.stderr, flush=True)
        return 2
    _start_log()
    fd, lock = acquire_owner_lock()
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    finally:
        release_owner_lock(fd, lock)


if __name__ == "__main__":
    raise SystemExit(main())
