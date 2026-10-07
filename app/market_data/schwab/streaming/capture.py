"""The capture daemon: the ONE Schwab streaming connection (Schwab allows one per account).

    python -m app.market_data.schwab.streaming.capture          (start_capture_daemon.bat)

It is the only part of Ed Console that talks to Schwab. Beside the loop below, its chain sweep
(run_chains) fetches full option chains on its own thread, one request at a time, without end:
every watchlist ticker, each in its turn in one rotation.

  0. WATCHLIST The one list of tickers Schwab is asked for (Watchlist): the daemon holds it,
             is its only writer, and keeps every change as a `watchlist` record (the writer
             stores it in stream_capture.db stream_watchlist; the newest is read at startup).
             The console asks for an add or a removal over the local console socket (live_push,
             ws://127.0.0.1:8799): {"op": "watchlist", "action": "add"|"remove", "ticker": T,
             "id": n}. An added ticker is checked with one /quotes request: one Schwab names in
             errors.invalidSymbols, or does not quote, is not added. The record carries the
             request's id and Schwab's answer back to the console.

It does four things, in one loop:

  1. SUBSCRIBE Once per connection, every watchlist ticker on each equity service (with the
             market context the page header shows, MARKET_CONTEXT, on LEVELONE_EQUITIES,
             CHART_EQUITY and NEWS_HEADLINE), and the option contracts the console names
             ({"op": "options", "LEVELONE_OPTIONS": [...], "OPTIONS_BOOK": [...]}). A change to
             the watchlist or the console's contracts is asked once: UNSUBS what left, then SUBS
             (a service's first request) or ADD what came. Nothing asked is asked again on this
             connection, whatever Schwab answered. Requests are split so none exceeds Schwab's
             64 KB message limit (measured 2026-09-22: a 71 KB request closed the socket).
  2. ANSWERS Every Schwab answer is matched to its own request by its requestid, logged and
             recorded (stream_subscriptions) exactly as sent -- a refused ADD is answered twice
             (code 19, then code 24 "ADD command failed"), and both are its answers.
  3. FAN-OUT Every Schwab message is published once on the bus: the database writer
             (stream_capture.db), the console socket (8799) and the browser price socket
             (8800) all read from it.
  4. HEALTH  Any frame from Schwab -- data or Schwab's own heartbeat -- proves the connection
             is alive. None for DEAD_SEC, or a request unanswered for REQUEST_TIMEOUT_SEC:
             reconnect with backoff and subscribe once again. There is nothing else to recover.

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
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import runtime_layout  # noqa: E402  (the standard library only)

#: Under pythonw there is no error output: from here until the log starts (_start_log) it is the
#: log file, so a module below that fails to load leaves its reason there.
_EARLY_ERRORS = None
if sys.stderr is None:
    _log_file = runtime_layout.logs_dir() / "stream_capture.log"
    _log_file.parent.mkdir(parents=True, exist_ok=True)
    _EARLY_ERRORS = sys.stderr = open(_log_file, "a", encoding="utf-8", buffering=1)
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} capture daemon loading (pid {os.getpid()})", file=sys.stderr)

from stream_spine import (  # noqa: E402
    LOG,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    current_key,
    bar_msg,
    book_msg,
    news_msg,
    options_quote_msg,
    quote_msg,
    resolve_stream_db_path,
    subscription_msg,
)
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT  # noqa: E402
from calibration.complete_chain_capture import ChainSweep  # noqa: E402
from instrument_identity import ticker_storage_key  # noqa: E402
from schwab_client import safe_get_quotes  # noqa: E402
from time_et import ct_label  # noqa: E402

log = logging.getLogger("capture")

#: The longest the connection reads Schwab's frames before it checks for silence and for a
#: request Schwab has not answered (a subscription to send wakes it at once).
READ_SEC = 1.0
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
#: every watchlist ticker is streamed on each of these
EQUITY_SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE", "NYSE_BOOK", "NASDAQ_BOOK")
#: the option contracts the console names are streamed on these (OPTIONS_BOOK: its own list)
OPTION_SERVICES = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")
#: the market context every page's header shows (live_push.MARKET_CONTEXT) is streamed on these,
#: whatever the watchlist holds
MARKET_CONTEXT_SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE")

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


# ---------------------------------------------------------------------------- the watchlist

#: the bus topic of the watchlist record (stream_spine writes it to stream_watchlist)
WATCHLIST_TOPIC = "watchlist"
WATCHLIST_SRC = "daemon_watchlist"
#: what a watchlist record says happened
ADDED, REMOVED, INVALID, NOT_CHECKED, ON_LIST, NOT_ON_LIST = (
    "added", "removed", "invalid", "not checked", "already on the list", "not on the list")


def stored_watchlist(db_path: "str | Path") -> "list[str]":
    """The watchlist as the newest stored record holds it (stream_watchlist, written by the
    daemon's writer), read once at startup; empty when none was ever stored."""
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='stream_watchlist'").fetchone():
            return []
        rows = conn.execute("SELECT tickers_json FROM stream_watchlist ORDER BY rowid DESC LIMIT 1").fetchall()
    finally:
        conn.close()
    return [t for (tickers,) in rows for t in json.loads(tickers)]


def watchlist_message(tickers: "list[str]", *, op: str, ticker: str, request_id, status: "int | None" = None,
                      answer=None) -> "tuple[str, dict]":
    """The watchlist after one request as its bus record: the whole list, what happened to
    `ticker` (`op`), the console's request id, and Schwab's /quotes answer to the check (an add)
    with its HTTP status, as sent."""
    return WATCHLIST_TOPIC, {"src": WATCHLIST_SRC, "ts_recv": time.time(), "tickers": list(tickers), "op": op,
                             "ticker": ticker, "request_id": request_id, "status": status, "answer": answer}


def check_ticker(client, ticker: str) -> "tuple[bool, int, object]":
    """One /quotes request for `ticker`: (Schwab quotes it, its status, its answer as sent). A
    ticker Schwab names in errors.invalidSymbols, or does not quote, or an answer other than 200,
    is not a ticker Schwab answers for."""
    resp = safe_get_quotes(client, [ticker])
    try:
        answer = resp.json()
    except ValueError:
        return False, resp.status_code, resp.text
    return resp.status_code == 200 and isinstance(answer, dict) and ticker in answer, resp.status_code, answer


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


def _dispatch(stream, msg: dict) -> None:
    """A frame's data and notifications to the services' handlers, as schwab-py's
    handle_message hands them (Schwab's heartbeats carry nothing to hand)."""
    for d in msg["data"] if "data" in msg else []:
        for handler in stream._handlers[d["service"]] if d["service"] in stream._handlers else []:
            handler(handler.label_message(d))
    for d in msg["notify"] if "notify" in msg else []:
        if "heartbeat" not in d:
            for handler in stream._handlers[d["service"]]:
                handler(d)


@dataclass(eq=False)
class _Sent:
    """One request this connection sent, and how many answers Schwab has sent to it."""
    service: str
    command: str
    symbols: "list[str]"
    sent_ts: float
    answers: int = 0


def _request_ended(task: "asyncio.Future") -> None:
    """A watchlist request's end: one that ended on an error is logged with its traceback."""
    if not task.cancelled() and task.exception() is not None:
        e = task.exception()
        log.error("watchlist request: ended on %s: %s", type(e).__name__, e, exc_info=e)


def _connection_lost(e: BaseException) -> bool:
    """The socket itself is gone (as opposed to Schwab refusing one request)."""
    from websockets.exceptions import ConnectionClosed
    return isinstance(e, (ConnectionClosed, ConnectionError, OSError, asyncio.IncompleteReadError))


# ---------------------------------------------------------------------------- the daemon


#: why Schwab is not connected while no attempt has failed since the stream last logged in: it is
#: logging in, or its connection has just ended and the reason is on its way
SCHWAB_CONNECTING = "NOT CONNECTED: the stream is logging in, or its connection has just ended"


class Daemon:
    def __init__(self, bus: MessageBus, health: HealthRegistry, watchlist: "list[str]" = ()) -> None:
        self.bus = bus
        self.health = health
        #: the one list of tickers Schwab is asked for, in its order (stored_watchlist at startup)
        self.watchlist: "list[str]" = list(watchlist)
        #: the option contracts the console names, per option service, as it last said
        self.options: "dict[str, frozenset[str]]" = {s: frozenset() for s in OPTION_SERVICES}
        #: the console connection whose contracts these are (live_push's socket)
        self.sender = None
        self.chains = None                  # the ChainSweep: its round time, its tickers
        self.writer = None                  # the CaptureWriter: its state rides the heartbeat
        self.schwab_client = None           # the daemon's one Schwab client (run): the checks
        #: what this connection has asked Schwab for, and what Schwab accepted (code 0)
        self.asked: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
        self.held: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
        #: per service, each symbol Schwab refused on this connection, with Schwab's message
        self.refused: "dict[str, dict[str, str]]" = {s: {} for s in SERVICES}
        #: requests waiting to be sent, and every request sent on this connection by requestid
        self._requests: "list[tuple[str, str, list[str]]]" = []
        self._sent: "dict[int, _Sent]" = {}
        self.wake = asyncio.Event()         # a request is waiting: the connection sends it now
        self.stream = None
        #: why Schwab is not connected, for /api/health (status()["schwab_down"], read while the
        #: socket is not open): SCHWAB_CONNECTING, or NOT CONNECTED since the first failure in a
        #: row (_down_since) with the last one's reason, as the log has it
        self.schwab_down = SCHWAB_CONNECTING
        self._down_since: "float | None" = None

    def wanted(self) -> "dict[str, frozenset[str]]":
        """What Schwab is asked for, per service: every watchlist ticker on each equity service,
        the market context on MARKET_CONTEXT_SERVICES, and the console's option contracts."""
        out = {svc: frozenset(self.watchlist) for svc in EQUITY_SERVICES}
        for svc in MARKET_CONTEXT_SERVICES:
            out[svc] |= frozenset(MARKET_CONTEXT)
        out.update(self.options)
        return out

    def ask(self) -> None:
        """Queue, once, what this connection has not asked Schwab for: per service, UNSUBS what
        left, then SUBS (its first request) or ADD what came. What is asked is never asked again
        on this connection, whatever Schwab answers. Nothing is queued while no connection is
        open: a connection asks for everything when it opens."""
        if self.stream is None:
            return
        for svc, want in self.wanted().items():
            have = self.asked[svc]
            drop, add = sorted(have - want), sorted(want - have)
            if drop:
                self._requests.append((svc, "UNSUBS", drop))
            if add:
                self._requests.append((svc, "ADD" if have - set(drop) else "SUBS", add))
            self.asked[svc] = want
        self.wake.set()

    def set_options(self, raw, sender=None) -> None:
        """The option contracts from console connection `sender` (live_push calls this for every
        {"op": "options"} frame), per option service. `raw` None: that connection ended, and
        withdraws the contracts only if they are its own (another connection's later list
        stands)."""
        if raw is None and sender is not self.sender:
            return
        self.sender = None if raw is None else sender
        new = {svc: frozenset() for svc in OPTION_SERVICES}
        if raw is not None:
            new = {svc: frozenset(str(s).strip().upper() for s in raw[svc]) for svc in OPTION_SERVICES}
        self.options = new
        self.ask()

    def console_frame(self, req: "dict | None", sender) -> None:
        """A frame from console connection `sender` (live_push): its option contracts
        ({"op": "options"}) or a watchlist request ({"op": "watchlist"}, answered on the bus);
        None: that connection ended."""
        if req is None or req["op"] == "options":
            return self.set_options(req, sender)
        if req["op"] == "watchlist":
            task = asyncio.ensure_future(self.watchlist_request(req))
            task.add_done_callback(_request_ended)

    async def watchlist_request(self, req: dict) -> None:
        """One add or removal from the console ({"op": "watchlist", "action", "ticker", "id"}),
        answered with the watchlist record (watchlist_message), which the writer stores and the
        console receives. An added ticker is checked first with one /quotes request (check_ticker)
        and added only when Schwab quotes it; on the list, Schwab is asked for it at once on every
        service and by the chain sweep, and a removed one is asked for no more."""
        ticker, rid = ticker_storage_key(str(req["ticker"])), req["id"]
        status = answer = None
        if req["action"] == "remove":
            if ticker not in self.watchlist:
                return self.bus.publish(*watchlist_message(self.watchlist, op=NOT_ON_LIST, ticker=ticker, request_id=rid))
            self.watchlist, op = [t for t in self.watchlist if t != ticker], REMOVED
        else:
            if ticker in self.watchlist:
                return self.bus.publish(*watchlist_message(self.watchlist, op=ON_LIST, ticker=ticker, request_id=rid))
            try:
                quoted, status, answer = await asyncio.to_thread(check_ticker, self.schwab_client(), ticker)
            except Exception as e:  # noqa: BLE001 -- the check could not be made: not added, and why
                log.warning("watchlist: %s not checked: %s: %s", ticker, type(e).__name__, e)
                return self.bus.publish(*watchlist_message(self.watchlist, op=NOT_CHECKED, ticker=ticker,
                                                           request_id=rid, answer=f"{type(e).__name__}: {e}"))
            if not quoted:
                log.warning("watchlist: %s not added: Schwab's /quotes answered %s: %s", ticker, status,
                            json.dumps(answer))
                return self.bus.publish(*watchlist_message(self.watchlist, op=INVALID, ticker=ticker, request_id=rid,
                                                           status=status, answer=answer))
            if ticker in self.watchlist:           # added by another request during the check
                return self.bus.publish(*watchlist_message(self.watchlist, op=ON_LIST, ticker=ticker, request_id=rid))
            self.watchlist, op = [*self.watchlist, ticker], ADDED
        log.info("watchlist: %s %s; the list: %s", ticker, op, ",".join(self.watchlist))
        if self.chains is not None:
            self.chains.watchlist = list(self.watchlist)
        self.ask()
        self.bus.publish(*watchlist_message(self.watchlist, op=op, ticker=ticker, request_id=rid, status=status,
                                            answer=answer))

    def option_record(self, symbol: str) -> "tuple[str, dict] | None":
        """`symbol`'s current LEVELONE_OPTIONS record on the bus, (topic, record), while this
        connection holds it on LEVELONE_OPTIONS; None otherwise (the chain sweep reads each
        contract's Greeks from it, and asks the quotes endpoint for every contract it returns None
        for: a record left from a connection that ended is not held)."""
        held = symbol in self.held["LEVELONE_OPTIONS"]
        return self.bus.current.get(_current_key("LEVELONE_OPTIONS", symbol)) if held else None

    def status(self) -> dict:
        """What the console and browsers are told every second (live_push / live_ui)."""
        now = time.time()
        last = self.stream.last_frame_ts if self.stream is not None else 0.0
        return {"ts": now,
                "schwab_socket_open": bool(last) and now - last < DEAD_SEC,
                "schwab_down": self.schwab_down,
                "watchlist": list(self.watchlist),
                "chain_round_sec": self.chains.round_sec if self.chains is not None else None,
                "held": {k: sorted(v) for k, v in self.held.items()},
                "refused": {k: dict(v) for k, v in self.refused.items() if v},
                "health": self.health.report(now),
                "writer": self.writer.status() if self.writer is not None else None}

    async def send_requests(self) -> None:
        """Send every queued request, each split under Schwab's message limit, without waiting
        for an answer: the reader matches each answer to its request (answered)."""
        while self._requests:
            svc, cmd, symbols = self._requests.pop(0)
            for chunk in split_request(symbols):
                params = {"keys": ",".join(chunk)}
                if cmd != "UNSUBS":
                    params["fields"] = _fields(self.stream, svc)
                req, rid = self.stream._make_request(service=svc, command=cmd, parameters=params)
                self._sent[rid] = _Sent(svc, cmd, chunk, time.time())
                await self.stream._send({"requests": [req]})
                log.info("%s %s sent: %d symbols, requestid %d", svc, cmd, len(chunk), rid)

    def answered(self, response: dict) -> None:
        """One answer from Schwab (an entry of a frame's `response`), matched to its request by
        its requestid: logged and recorded (stream_subscriptions) exactly as Schwab sent it. A
        first answer of code 0 changes what is held; a later answer to the same request is
        recorded as its own."""
        rid = int(response["requestid"])
        sent = self._sent.get(rid)
        if sent is None:
            log.warning("schwab answered requestid %d, which this connection did not send: %s", rid,
                        json.dumps(response))
            return
        sent.answers += 1
        code, msg = response["content"]["code"], response["content"]["msg"]
        log.log(logging.INFO if code == 0 else logging.WARNING, "%s %s answer %d (%d symbols, requestid %d): %s",
                sent.service, sent.command, sent.answers, len(sent.symbols), rid, json.dumps(response))
        self.bus.publish(f"sub.{sent.service}", subscription_msg(
            service=sent.service, command=sent.command, symbols=sent.symbols, code=code, reason=msg))
        if code != 0 and sent.command != "UNSUBS":       # shown on the heatmap's cells, never asked again
            for sym in sent.symbols:                     # Schwab's first refusal says why (code 19's limit)
                self.refused[sent.service].setdefault(sym, msg)
        if code != 0 or sent.answers > 1:
            return
        held = set(self.held[sent.service])
        held = held - set(sent.symbols) if sent.command == "UNSUBS" else held | set(sent.symbols)
        self.held[sent.service] = frozenset(held)
        if sent.command == "UNSUBS":                # no longer held: no longer current
            for sym in sent.symbols:
                self.bus.forget(_current_key(sent.service, sym))

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
        # a new connection has asked for nothing and holds nothing
        self.asked = {s: frozenset() for s in SERVICES}
        self.held = {s: frozenset() for s in SERVICES}
        self.refused = {s: {} for s in SERVICES}
        self._requests, self._sent = [], {}
        self.schwab_down, self._down_since = SCHWAB_CONNECTING, None
        log.info("schwab: connected")

    async def disconnect(self) -> None:
        s, self.stream = self.stream, None
        self.asked = {k: frozenset() for k in SERVICES}
        self.held = {k: frozenset() for k in SERVICES}
        if s is not None:
            try:
                await asyncio.wait_for(s.logout(), timeout=5)
            except Exception as e:  # noqa: BLE001 -- the session is dropped either way
                log.info("schwab: logout of the old session failed (%s: %s)", type(e).__name__, e)

    async def read_for(self, seconds: float) -> None:
        """Handle Schwab's frames for `seconds`, or until a request is waiting: each answer to
        its request (answered), the data to the services' handlers. One task does both reading
        and sending, and it alone reads, so every answer reaches it (websockets' recv is safe to
        cancel, so ending early never loses a frame)."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0 and not self.wake.is_set():
            frame = asyncio.ensure_future(self.stream._receive())
            change = asyncio.ensure_future(self.wake.wait())
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
                continue
            msg = frame.result()
            for response in msg["response"] if "response" in msg else []:
                self.answered(response)
            try:
                _dispatch(self.stream, msg)
            except Exception as e:  # noqa: BLE001 -- that frame is logged; the next one is read
                log.warning("schwab: skipped a frame (%s: %s)", type(e).__name__, str(e)[:250])

    async def run_connection(self, client, stop: asyncio.Event) -> None:
        """One connection's life: ask for everything once, then send what is queued and read --
        until it dies or stop is set. A request Schwab has not answered in REQUEST_TIMEOUT_SEC
        means the connection is broken."""
        await self.connect(client)
        try:
            self.ask()
            while not stop.is_set():
                now = time.time()
                if now - self.stream.last_frame_ts > DEAD_SEC:
                    raise ConnectionError(f"no frame from Schwab for {DEAD_SEC:.0f} s")
                late = [s for s in self._sent.values() if s.answers == 0 and now - s.sent_ts > REQUEST_TIMEOUT_SEC]
                if late:
                    raise ConnectionError(f"no answer to {late[0].service} {late[0].command} in "
                                          f"{REQUEST_TIMEOUT_SEC:.0f} s")
                self.wake.clear()
                await self.send_requests()
                await self.read_for(READ_SEC)
        finally:
            await self.disconnect()

    async def run(self, schwab_client, stop: asyncio.Event) -> None:
        """Connect, and reconnect with backoff whenever the connection ends, until stop, on the
        daemon's one Schwab client (`schwab_client()`), which also makes the watchlist's checks."""
        self.schwab_client = schwab_client
        failures = 0
        while not stop.is_set():
            started = time.time()
            try:
                await self.run_connection(schwab_client(), stop)
            except Exception as e:  # noqa: BLE001 -- every failure is a reconnect; its reason to the log and /api/health
                why = f"{type(e).__name__}: {str(e)[:350]}"
                log.warning("schwab: connection ended (%s)", why)
                if self._down_since is None:
                    self._down_since = time.time()
                self.schwab_down = f"NOT CONNECTED since {ct_label(self._down_since)}: {why}"
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
    """Every line, with its time to the millisecond, to <runtime>/logs/stream_capture.log, and to
    the console if any. Under pythonw the log file held as the error output since the first line
    (_EARLY_ERRORS) is closed first, so the log's handler holds the file alone and can rotate it;
    from here an error reaches the log through the handler (main logs one that ends the daemon)."""
    global _EARLY_ERRORS
    if _EARLY_ERRORS is not None:
        _EARLY_ERRORS.close()
        _EARLY_ERRORS = sys.stderr = None
    path = runtime_layout.logs_dir() / "stream_capture.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: "list[logging.Handler]" = [
        RotatingFileHandler(path, maxBytes=50 * 1024 * 1024, backupCount=1, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s.%(msecs)03d %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)    # each request's line is log_request's


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


def _worker_ended(worker: "asyncio.Future") -> None:
    """The chain sweep's end: one that ended on an error is logged with its traceback."""
    if not worker.cancelled() and worker.exception() is not None:
        e = worker.exception()
        log.error("chain sweep: ended on %s: %s", type(e).__name__, e, exc_info=e)


async def run_chains(daemon: "Daemon", db_path, schwab_client, stop: asyncio.Event, *,
                     failures: "CaptureWriter") -> None:
    """The chain sweep (calibration.complete_chain_capture.ChainSweep) on its own thread, so the
    stream never waits on a chain; each chain part is published on the event loop, and the bus
    keeps each ticker's newest whole chain (stream_spine.MessageBus._chain). The sweep reads each
    option's LEVELONE_OPTIONS record from the bus for its Greeks. A chain whose history write
    fails is kept by `failures`, the daemon's writer (its failures ride the heartbeat). A sweep
    that ends on an error is logged with it (_worker_ended): its thread has no error output of
    its own to reach."""
    loop = asyncio.get_running_loop()
    halt = threading.Event()
    sweep = ChainSweep(db_path, daemon.watchlist,
                       lambda topic, msg: loop.call_soon_threadsafe(daemon.bus.publish, topic, msg),
                       failures=failures, streamed=daemon.option_record)
    daemon.chains = sweep
    worker = loop.run_in_executor(None, sweep.work, schwab_client, halt)
    worker.add_done_callback(_worker_ended)
    try:
        await stop.wait()
    finally:
        halt.set()
        await asyncio.gather(worker, return_exceptions=True)


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
    """The whole daemon: writer, the two local sockets, the chain sweep and the Schwab
    connection."""
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
    daemon = Daemon(bus, health, stored_watchlist(writer.db_path))
    daemon.writer = writer
    wsub = bus.subscribe("", policy=LOG)                # the record of every message
    tasks = [asyncio.create_task(writer.run(wsub, stop=stop)),
             asyncio.create_task(run_chains(daemon, db_path, schwab_client, stop, failures=writer)),
             asyncio.create_task(record_feed_status(daemon, stop)),
             asyncio.create_task(serve_live_push(bus, stop, on_request=daemon.console_frame)),
             asyncio.create_task(serve_live_ui(bus, stop, heartbeat_fn=daemon.status))]
    try:
        await asyncio.sleep(0)                    # servers subscribe before the first message
        await daemon.run(schwab_client, stop)
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return 0


def main() -> int:
    if sys.argv[1:]:        # everything it needs comes from the console; no switch can move it
        print(f"the capture daemon takes no arguments (got {sys.argv[1:]})", file=sys.stderr)
        return 2
    # a worktree must not run a live daemon against production's runtime
    binding = runtime_layout.live_binding_error()
    if binding is not None:
        print(f"CAPTURE DAEMON REFUSED: {binding}", file=sys.stderr, flush=True)
        return 2
    _start_log()
    fd, lock = acquire_owner_lock()
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    except BaseException:
        log.exception("capture daemon: ended by an error")   # under pythonw, the log is the only record
        raise
    finally:
        release_owner_lock(fd, lock)


if __name__ == "__main__":
    raise SystemExit(main())
