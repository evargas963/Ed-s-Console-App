"""Feed's one Schwab stream connection (Schwab allows one per account).

Connection logs in, asks Schwab for what the daemon wants on each service, matches each answer
to its request, hands every frame's data to the bus, and reconnects with backoff when the
connection breaks:

  SUBSCRIBE  What the daemon wants (its `wanted`), per service, cut at the symbol limit Schwab
             stated for the service on this connection. No number of ours caps a service: when
             Schwab refuses with its symbol limit (code 19) the service is asked again once, a
             SUBS of the first that many. A change is asked once: UNSUBS what left, then SUBS (a
             service's first request) or ADD what came. Any other refusal is not asked again on
             this connection. Requests are split so none exceeds Schwab's 64 KB message limit (a
             larger request closes the socket).
  ANSWERS    Every Schwab answer is matched to its own request by its requestid, logged and
             recorded (stream_subscriptions) exactly as sent -- a refused ADD is answered twice
             (code 19, then code 24 "ADD command failed"), and both are its answers.
  FAN-OUT    Every Schwab message is published once on the bus: the database writer
             (the one database), the console and the pages' price socket all read from it.
  HEALTH     Any frame from Schwab -- data or Schwab's own heartbeat -- proves the connection is
             alive. None for DEAD_SEC, or a request unanswered while Schwab's stream, by the time
             Schwab put on the frames read, moved on REQUEST_TIMEOUT_SEC past it: reconnect with
             backoff and subscribe once again. There is nothing else to recover.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from schwab.streaming import UnparsableMessage

import live_market_plane as lmp
import time_et
from feed.stream import TimedStream, label
from stream_spine import (
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    current_key,
    quote_msg,
    subscription_msg,
    verbatim_msg,
)
from time_et import ct_label

log = logging.getLogger("capture")

#: How often the connection checks for silence and for a request Schwab has not answered
#: (Connection.watch); its frames are read and its requests sent as they come.
READ_SEC = 1.0
#: No frame at all from Schwab (data or heartbeat) for this long -> the connection is dead.
DEAD_SEC = 30.0
#: Reconnect waits, in order; the last repeats.
RECONNECT_BACKOFF_SEC = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
#: Schwab closes the socket on a request over 65,535 bytes; stay well under it.
MAX_REQUEST_BYTES = 48_000
#: A request Schwab does not answer in this long, by Schwab's time on the frames read, means the
#: connection is broken. Schwab's time, not the reader's: an answer Schwab sent waits behind the
#: frames before it until the reader takes them, and a reader running behind is not Schwab silent.
REQUEST_TIMEOUT_SEC = 15.0

SERVICES = (
    "LEVELONE_EQUITIES",
    "CHART_EQUITY",
    "NYSE_BOOK",
    "NASDAQ_BOOK",
    "LEVELONE_OPTIONS",
    "OPTIONS_BOOK",
    "NEWS_HEADLINE",
)
#: Schwab's answer code for a request past its symbol limit (Schwab Streamer API, response
#: codes: 19 REACHED_SYMBOL_LIMIT)
SYMBOL_LIMIT = 19

#: LEVELONE_EQUITIES / CHART_EQUITY fields copied into the database's flat columns (the full
#: Schwab item is kept verbatim beside them in native_json).
LEVELONE_FIELDS = {
    "BID_PRICE": "bid",
    "ASK_PRICE": "ask",
    "LAST_PRICE": "last",
    "BID_SIZE": "bid_size",
    "ASK_SIZE": "ask_size",
    "TOTAL_VOLUME": "total_volume",
    "LAST_SIZE": "last_size",
    "QUOTE_TIME_MILLIS": "quote_time_ms",
    "TRADE_TIME_MILLIS": "trade_time_ms",
}
CHART_FIELDS = {
    "OPEN_PRICE": "open",
    "HIGH_PRICE": "high",
    "LOW_PRICE": "low",
    "CLOSE_PRICE": "close",
    "VOLUME": "volume",
    "CHART_TIME_MILLIS": "bar_start_ms",
}
#: The highest field number Schwab accepts on each service: every number above it, asked alone, is
#: answered code 22 "SUBS command failed"
#: (tests/fixtures/real_schwab_field_number_replies_2026_10_12.json). The daemon asks for every
#: number up to it, so each field Schwab sends, documented or not, is kept.
HIGHEST_FIELD = {
    "LEVELONE_EQUITIES": 150,
    "LEVELONE_OPTIONS": 150,
    "CHART_EQUITY": 300,
    "NYSE_BOOK": 300,
    "NASDAQ_BOOK": 300,
    "OPTIONS_BOOK": 300,
    "NEWS_HEADLINE": 300,
}
FIELDS = {svc: ",".join(str(f) for f in range(top + 1)) for svc, top in HIGHEST_FIELD.items()}

#: each Schwab service's bus topic kind and the source its messages carry
SERVICE_TOPIC = {
    "LEVELONE_EQUITIES": ("quote", "schwab_l1"),
    "CHART_EQUITY": ("bar1m", "schwab_chart"),
    "LEVELONE_OPTIONS": ("optquote", "schwab_options_l1"),
    "NEWS_HEADLINE": ("news", "schwab_news"),
    "NYSE_BOOK": ("book", "schwab_book"),
    "NASDAQ_BOOK": ("book", "schwab_book"),
    "OPTIONS_BOOK": ("book", "schwab_book"),
}

#: why Schwab is not connected while no attempt has failed since the stream last logged in: it is
#: logging in, or its connection has just ended and the reason is on its way
SCHWAB_CONNECTING = "NOT CONNECTED: the stream is logging in, or its connection has just ended"


def split_request(symbols: list[str], max_bytes: int = MAX_REQUEST_BYTES) -> list[list[str]]:
    """Chunks whose comma-joined key list stays under max_bytes."""
    chunks: list[list[str]] = []
    cur: list[str] = []
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


def held_key(service: str, sym: str) -> str:
    """Return the bus's current-record key of `sym` on `service` (stream_spine.current_key)."""
    kind, src = SERVICE_TOPIC[service]
    return current_key(f"{kind}.{sym}", {"service": service, "src": src})


def _message(
    service: str, sym: str, item: dict[str, Any], schwab_ts: int | None, ts_recv: float
) -> tuple[str, dict[str, Any]]:
    """Return (topic kind, bus message) for one Schwab item.

    The message carries the timestamp of Schwab's frame and the time it was received.
    """
    kind, src = SERVICE_TOPIC[service]
    at: dict[str, Any] = {"src": src, "schwab_ts": schwab_ts, "ts_recv": ts_recv}
    if service == "LEVELONE_EQUITIES":
        fields: dict[str, Any] = {name: item.get(k) for k, name in LEVELONE_FIELDS.items()}
        return kind, quote_msg(symbol=sym, native=item, **at, **fields)
    if service == "CHART_EQUITY":
        fields = {name: item.get(k) for k, name in CHART_FIELDS.items()}
        return kind, bar_msg(symbol=sym, native=item, **at, **fields)
    if service in ("LEVELONE_OPTIONS", "NEWS_HEADLINE"):
        return kind, verbatim_msg(symbol=sym, content=item, **at)
    return kind, book_msg(symbol=sym, service=service, content=item, **at)


def _publisher(
    service: str, bus: MessageBus, health: HealthRegistry, clock: Callable[[], float]
) -> Callable[[dict[str, Any]], None]:
    """schwab-py handler for one service: every item -> the bus.

    Each item goes with the timestamp Schwab put on the frame. The service counts as alive only
    when a frame delivered data, not merely arrived. A frame with no list of items, and an item
    with no symbol, cannot be taken: each is logged as it came and the stream goes on.
    """

    def handler(msg: dict[str, Any]) -> None:
        published = False
        now, schwab_ts = clock(), msg.get("timestamp")
        content = msg.get("content")
        if not isinstance(content, list):
            log.warning("%s: a frame with no list of items, not taken: %.500r", service, msg)
            return
        for item in content:
            key = item.get("key") if isinstance(item, dict) else None
            if not isinstance(key, str) or not key:
                log.warning("%s: an item with no symbol, not taken: %.500r", service, item)
                continue
            sym = key.upper()
            kind, out = _message(service, sym, item, schwab_ts, now)
            bus.publish(f"{kind}.{sym}", out)
            published = True
        if published:
            health.beat(service, now)

    return handler


def _dispatch(publishers: dict[str, Callable[[dict[str, Any]], None]], msg: dict[str, Any]) -> None:
    """Hand a frame's data, its fields named (_label), and its notifications to their services.

    Schwab's heartbeats carry nothing to hand.
    """
    for d in msg["data"] if "data" in msg else []:
        if d["service"] in publishers:
            publishers[d["service"]](label(d))
    for d in msg["notify"] if "notify" in msg else []:
        if "heartbeat" not in d and d["service"] in publishers:
            publishers[d["service"]](d)


@dataclass(eq=False)
class _Sent:
    """One request this connection sent, and how many answers Schwab has sent to it."""

    service: str
    command: str
    symbols: list[str]
    sent_ts: float
    answers: int = 0


class Connection:
    """The one Schwab stream connection, asking for what `wanted` returns per service, in order.

    `clock` is the program's clock (time_et.now), handed in by the daemon that runs it: a
    request's send time, the silence check and the backoff are read on it.
    """

    def __init__(
        self,
        bus: MessageBus,
        health: HealthRegistry,
        wanted: Callable[[], dict[str, tuple[str, ...]]],
        clock: Callable[[], float],
    ) -> None:
        self.bus = bus
        self.wanted = wanted
        self.clock = clock
        #: what this connection has asked Schwab for, what Schwab accepted (code 0), and the symbol
        #: limit Schwab stated for the service in a refusal (code 19), None until it states one
        self.asked: dict[str, frozenset[str]] = {s: frozenset() for s in SERVICES}
        self.held: dict[str, frozenset[str]] = {s: frozenset() for s in SERVICES}
        self.limit: dict[str, int | None] = dict.fromkeys(SERVICES)
        #: requests waiting to be sent, and every request sent on this connection by requestid
        self._requests: list[tuple[str, str, list[str]]] = []
        self._sent: dict[int, _Sent] = {}
        self.wake = asyncio.Event()  # a request is waiting: the connection sends it now
        self.stream: TimedStream | None = None
        #: each service's items -> the bus (_dispatch)
        self.publishers = {svc: _publisher(svc, bus, health, clock) for svc in SERVICES}
        #: why Schwab is not connected, for /api/health (read while the socket is not open):
        #: SCHWAB_CONNECTING, or NOT CONNECTED since the first failure in a row (_down_since) with
        #: the last one's reason, as the log has it
        self.schwab_down = SCHWAB_CONNECTING
        self._down_since: float | None = None

    def socket_open(self, now: float) -> bool:
        """Tell whether a stream exists and Schwab sent a frame within DEAD_SEC of `now`."""
        return self.stream is not None and now - self.stream.last_frame_ts < DEAD_SEC

    def ask(self) -> None:
        """Queue what this connection has not asked Schwab for.

        Per service, what is wanted cut at the symbol limit Schwab stated for it: UNSUBS what
        left, then SUBS (when nothing asked stays: its first request, or the first since Schwab
        stated its limit) or ADD what came, in the service's order. What Schwab refuses is not
        asked again on this connection. Nothing is queued while no connection is open: a
        connection asks for everything when it opens.
        """
        if self.stream is None:
            return
        for svc, order in self.wanted().items():
            want = order[: self.limit[svc]]
            have = self.asked[svc]
            drop, add = sorted(have.difference(want)), [s for s in want if s not in have]
            if drop:
                self._requests.append((svc, "UNSUBS", drop))
            if add:
                self._requests.append((svc, "ADD" if have - set(drop) else "SUBS", add))
            self.asked[svc] = frozenset(want)
        self.wake.set()

    async def send_requests(self, stream: TimedStream) -> None:
        """Send every queued request, each split under Schwab's message limit.

        Nothing waits for an answer: the reader matches each answer to its request (answered).
        A SUBS replaces all a service holds, so only its first part is SUBS and the rest are ADD.
        """
        while self._requests:
            svc, first, symbols = self._requests.pop(0)
            for i, chunk in enumerate(split_request(symbols)):
                cmd = "ADD" if first == "SUBS" and i else first
                params = {"keys": ",".join(chunk)}
                if cmd != "UNSUBS":
                    params["fields"] = FIELDS[svc]
                req, rid = stream._make_request(service=svc, command=cmd, parameters=params)
                self._sent[rid] = _Sent(svc, cmd, chunk, self.clock())
                await stream._send({"requests": [req]})
                log.info("%s %s sent: %d symbols, requestid %d", svc, cmd, len(chunk), rid)

    def answered(self, response: dict[str, Any]) -> None:
        """Take one answer from Schwab (an entry of a frame's `response`).

        It is matched to its request by its requestid, logged and recorded
        (stream_subscriptions) exactly as Schwab sent it. The first answer to a request decides
        what the service holds; a later answer to the same request is recorded as its own. An
        answer of code 19 that states a symbol limit not yet known has the service asked again
        within it (ask).
        """
        rid = int(response["requestid"])
        sent = self._sent.get(rid)
        if sent is None:
            log.warning(
                "schwab answered requestid %d, which this connection did not send: %s",
                rid,
                json.dumps(response),
            )
            return
        sent.answers += 1
        code, msg = response["content"]["code"], response["content"]["msg"]
        log.log(
            logging.INFO if code == 0 else logging.WARNING,
            "%s %s answer %d (%d symbols, requestid %d): %s",
            sent.service,
            sent.command,
            sent.answers,
            len(sent.symbols),
            rid,
            json.dumps(response),
        )
        self.bus.publish(
            f"sub.{sent.service}",
            subscription_msg(
                service=sent.service,
                command=sent.command,
                symbols=sent.symbols,
                code=code,
                reason=msg,
                ts=self.clock(),
            ),
        )
        svc = sent.service
        stated = re.search(rf"{svc}=(\d+)", msg)
        if code == SYMBOL_LIMIT and stated and int(stated[1]) != self.limit[svc]:
            # Schwab states the service's limit, and not which of the request's symbols it kept:
            # the service is asked again from nothing, the first that many of its order
            self.limit[svc] = int(stated[1])
            self.asked[svc] = frozenset()
            self.ask()
        if sent.answers > 1:
            return
        # a SUBS overwrites all the service held, an ADD adds, an UNSUBS removes (Schwab Streamer
        # API, Command Name); what Schwab refuses it does not confirm, so a refused SUBS holds none
        held, new = self.held[svc], frozenset(sent.symbols if code == 0 else ())
        kept = {"SUBS": new, "ADD": held | new, "UNSUBS": held - new}[sent.command]
        for sym in (held | new) - kept:  # no longer held: no longer current
            self.bus.forget(held_key(svc, sym))
        self.held[svc] = kept

    async def connect(self, client: object) -> TimedStream:
        stream = TimedStream(client, self.clock)
        # every message Schwab sends, whatever its size: the websockets library caps a received
        # message at 1 MiB by default, and nothing of ours does
        await stream.login(websocket_connect_args={"max_size": None})
        self.stream = stream
        self._requests, self._sent = [], {}
        self.schwab_down, self._down_since = SCHWAB_CONNECTING, None
        log.info("schwab: connected")
        return stream

    async def disconnect(self) -> None:
        s, self.stream = self.stream, None
        for svc in lmp.OPTION_SERVICES:  # an option contract's hold ends with its connection
            for sym in self.held[svc]:
                self.bus.forget(held_key(svc, sym))
        # the next connection has asked for nothing, holds nothing and has been told no limit
        self.asked = {k: frozenset() for k in SERVICES}
        self.held = {k: frozenset() for k in SERVICES}
        self.limit = dict.fromkeys(SERVICES)
        if s is not None:
            try:
                await asyncio.wait_for(s.logout(), timeout=5)
            except Exception as e:  # the session is dropped either way
                log.info(
                    "schwab: logout of the old session failed (%s: %s)",
                    type(e).__name__,
                    e,
                    exc_info=True,
                )

    async def read(self, stream: TimedStream) -> None:
        """Handle every frame Schwab sends, as it comes, until the socket is gone.

        Each answer goes to its request (answered), the data to the services' publishers. This
        task alone reads, so every answer reaches it; it awaits each frame with no timer of its
        own (a stop cancels it, and websockets' recv is safe to cancel: no frame is lost). A frame
        schwab-py cannot parse (UnparsableMessage) is logged and the next one read; any other
        error ends the connection, which run logs and reconnects.
        """
        while True:
            try:
                msg = await stream._receive()
            except UnparsableMessage as e:  # a frame Schwab sent that cannot be read
                log.warning(
                    "schwab: skipped a frame (%s: %s)",
                    type(e).__name__,
                    str(e)[:250],
                    exc_info=True,
                )
                continue
            for response in msg["response"] if "response" in msg else []:
                self.answered(response)
            try:
                _dispatch(self.publishers, msg)
            except Exception as e:  # that frame is logged; the next one is read
                log.warning(
                    "schwab: skipped a frame (%s: %s)",
                    type(e).__name__,
                    str(e)[:250],
                    exc_info=True,
                )

    async def send(self, stream: TimedStream) -> None:
        """Send what is asked (ask), as soon as it is asked, until the connection ends."""
        while True:
            await self.wake.wait()
            self.wake.clear()
            await self.send_requests(stream)

    async def watch(self, stream: TimedStream, stop: asyncio.Event) -> None:
        """Check the connection every READ_SEC until `stop`; raise once it is broken.

        Broken: no frame from Schwab for DEAD_SEC, or a request Schwab has not answered once the
        frames read reach REQUEST_TIMEOUT_SEC past it by Schwab's time (its send time is read on
        this computer's clock, which agreed with Schwab's: of 18,358 answers logged 2026-11-03 to
        11-09, Schwab's time on each was 0.005 s before to 3.5 s after its request's send, 0.02 s
        after at the median).
        """
        while not await time_et.set_within(stop, READ_SEC):
            now, schwab_now = self.clock(), stream.schwab_ts
            if now - stream.last_frame_ts > DEAD_SEC:
                raise ConnectionError(f"no frame from Schwab for {DEAD_SEC:.0f} s")
            late = [
                s
                for s in self._sent.values()
                if s.answers == 0
                and schwab_now is not None
                and schwab_now - s.sent_ts > REQUEST_TIMEOUT_SEC
            ]
            if late:
                raise ConnectionError(
                    f"no answer to {late[0].service} {late[0].command} in "
                    f"{REQUEST_TIMEOUT_SEC:.0f} s"
                )

    async def run_connection(self, client: object, stop: asyncio.Event) -> None:
        """Run one connection's life until it dies or stop is set.

        Ask for everything once; then one task reads (read), one sends what is asked (send) and
        one checks the connection (watch). The first to end ends the others: the stop, or the
        connection's error, raised.
        """
        stream = await self.connect(client)
        try:
            self.ask()
            parts = {
                asyncio.ensure_future(self.read(stream)),
                asyncio.ensure_future(self.send(stream)),
                asyncio.ensure_future(self.watch(stream, stop)),
            }
            try:
                done, _ = await asyncio.wait(parts, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for part in parts:
                    part.cancel()
                await asyncio.gather(*parts, return_exceptions=True)
            for part in done:
                part.result()  # the connection's error, raised for run to name
        finally:
            await self.disconnect()

    async def run(self, schwab_client: Callable[[], object], stop: asyncio.Event) -> None:
        """Connect, and reconnect with backoff whenever the connection ends, until stop."""
        failures = 0
        while not stop.is_set():
            started = self.clock()
            try:
                await self.run_connection(schwab_client(), stop)
            except Exception as e:  # every failure is a reconnect; its reason to the log and health
                why = f"{type(e).__name__}: {str(e)[:350]}"
                log.warning("schwab: connection ended (%s)", why, exc_info=True)
                if self._down_since is None:
                    self._down_since = self.clock()
                self.schwab_down = f"NOT CONNECTED since {ct_label(self._down_since)}: {why}"
            if stop.is_set():
                break
            # a connection that lasted 5 minutes starts the backoff over
            failures = 1 if self.clock() - started > 300 else failures + 1
            wait = RECONNECT_BACKOFF_SEC[min(failures, len(RECONNECT_BACKOFF_SEC)) - 1]
            log.info("schwab: reconnecting in %.0f s", wait)
            await time_et.set_within(stop, wait)
