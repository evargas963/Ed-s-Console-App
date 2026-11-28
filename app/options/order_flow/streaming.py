"""The console's live-plane feed for every watchlist ticker.

It reads the capture daemon's one bus
(app.market_data.schwab.streaming.capture), in the same program. It opens no Schwab connection:
the daemon holds the one Schwab socket and is the one producer.

Each Schwab record on the bus is applied the moment it changes (_bus_loop -> _ingest_pushed) to
the console's planes. The database is not in the live path: it is the daemon's record, and no
screen value is read from it.

The daemon streams every ticker on its watchlist (capture.Daemon.watchlist, the one list), and
picks the option contracts it streams itself (capture.Daemon.pick_options, the option rule). This
module hands the daemon the operator's adds and removals of watchlist tickers (watchlist_request),
each answered by the daemon's watchlist record on the bus, and the contract selected on the Flow
panel (select_flow_contract), which the daemon streams on top of the rule. The daemon's status
(live_market_plane, recorded by live_ui's one-second beat) is the one source for "is the daemon /
Schwab alive", the watchlist and "what does Schwab hold".

Public API: `bind_daemon` / `start_order_flow_stream` / `stop_order_flow_stream`
/ `get_option_contract_streaming_diagnostics`.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import queue
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, TypedDict

import live_market_plane as _lmp
import time_et
from app.market_data.schwab.streaming.live_push import is_forwarded
from app.market_data.schwab.streaming.live_ui import HEARTBEAT_SEC
from app.options.order_flow import history as recent
from app.options.order_flow.state import (
    bind_bus,
    clear_all_live_state,
    newest_book,
    push_book,
    push_level_one,
    push_rest_quotes,
)
from calc.order_flow import BOOK_VENUES, book_readout
from instrument_identity import ticker_storage_key
from stream_spine import LATEST, MessageBus
from time_et import record_markets

if TYPE_CHECKING:
    from app.market_data.schwab.streaming.capture import Daemon

log = logging.getLogger(__name__)


def price_state(
    ticker: str, now: float, service: str = "LEVELONE_EQUITIES"
) -> tuple[str, str | None]:
    """Return `ticker`'s state on Schwab `service` (its quote, or a venue's book) at `now`.

    It is the one live rule (live_market_plane.live_state) on that service while it is not LIVE
    (the feed down, the symbol not held, its market not trading); while it is LIVE, the quote's
    own state, which alone holds Schwab's SECURITY_STATUS.
    """
    label, why = _lmp.live_state(ticker, service, now)
    if label != _lmp.LIVE:
        return label, why
    return _lmp.live_state(ticker, "LEVELONE_EQUITIES", now)


@dataclass
class Feed:
    """The console's one reader of the daemon's bus, and what it calls.

    Owned by bind_daemon (the daemon this console runs in: watchlist requests and the Flow panel's
    contract go to it) and start_order_flow_stream / stop_order_flow_stream (the task on the event
    loop, whether it runs, and the callbacks). The callbacks run on the event loop, so each
    returns at once: `on_tick` with the symbol of every streamed equity quote, every option quote
    carrying a _REPRICE_FIELDS value and every contract of a /quotes answer (server._on_stream_tick:
    reprices its ticker); `on_chain` with what assemble_chain_part settles (server._on_chain);
    `on_feed` on each status beat; `on_flow` with the symbol of every streamed equity quote and
    book (server.flow_changed). `tick_failures` counts the tick callback's failures, and
    `apply_failures` the bus records that failed to apply (_bus_loop); both ride the daemon's
    status beat (capture.Daemon.status).
    """

    daemon: Daemon | None = None
    task: asyncio.Task[None] | None = None
    running: bool = False
    on_tick: Callable[[str], None] | None = None
    on_chain: Callable[..., None] | None = None
    on_feed: Callable[[], None] | None = None
    on_flow: Callable[[str], None] | None = None
    tick_failures: int = 0
    apply_failures: int = 0


#: the console's one bus reader (Feed)
FEED = Feed()


@dataclass(frozen=True)
class WatchlistAnswer:
    """The daemon's answer to one watchlist request (capture.watchlist_message's record).

    What happened to `ticker` (`op`), the request it answers, Schwab's /quotes answer to an add's
    check with its HTTP status, as sent, and the sentence the screen shows for it.
    """

    op: str
    ticker: str
    request_id: int
    status: int | None
    answer: Any
    text: str


#: request id -> the future the daemon's watchlist record for it resolves
#: (_answer_watchlist_request)
_watchlist_answers: dict[int, asyncio.Future[WatchlistAnswer]] = {}
#: each watchlist request's id, unique in this process (an id, not a time)
_request_ids = itertools.count(1)
#: how long a watchlist request waits for the daemon's record (an add waits on Schwab's /quotes
#: answer)
WATCHLIST_ANSWER_SEC = 30.0


async def watchlist_request(action: str, ticker: str) -> WatchlistAnswer:
    """Send an add or a removal ("add" | "remove") of `ticker` to the daemon.

    The daemon keeps the watchlist; this returns its record once the daemon has answered
    (capture.watchlist_message: the list, what happened, Schwab's /quotes answer to an add's
    check). Raises ConnectionError while no daemon runs in this program, TimeoutError when no
    record comes in WATCHLIST_ANSWER_SEC.
    """
    daemon = FEED.daemon
    if daemon is None:
        raise ConnectionError("no capture daemon runs in this program")
    rid = next(_request_ids)
    answer = asyncio.get_running_loop().create_future()
    _watchlist_answers[rid] = answer
    try:
        daemon.console_frame({"op": "watchlist", "action": action, "ticker": ticker, "id": rid})

        return await asyncio.wait_for(answer, WATCHLIST_ANSWER_SEC)
    finally:
        del _watchlist_answers[rid]


async def select_flow_contract(contract: str | None) -> None:
    """Tell the daemon the Flow panel's selection (None: none).

    The daemon keeps it (capture.Daemon.flow_contract) and streams it on both option services on
    top of its rule.
    """
    if FEED.daemon is not None:
        FEED.daemon.console_frame({"op": "flow_contract", "contract": contract})


#: Every streamed 1-minute bar (bar1m.SYM, Schwab CHART_EQUITY), for server._bar_writer to write;
#: None is server.stop_bar_writer's stop.
streamed_bars: queue.SimpleQueue[dict[str, Any] | None] = queue.SimpleQueue()
#: ticker -> the chain being received: {"ts", "parts", "got": {part: contracts}}
_chain_parts: dict[str, dict[str, Any]] = {}

#: what one chain message settles: (ticker, contracts, time, reason, (spot, spot_ts))
type ChainSettled = tuple[
    str,
    list[dict[str, Any]] | None,
    float,
    str | None,
    tuple[float | None, float | None] | None,
    bool,
]


def assemble_chain_part(msg: dict[str, Any]) -> list[ChainSettled]:
    """One chain message from the daemon (chain_sweep.chain_messages) -> what it settles.

    In order: a chain whose parts did not all arrive before the next one began
    (ticker, None, ts, reason, None, False); a fetch that failed (ticker, None, ts, Schwab's answer,
    None, False); the whole chain once its last part is in (ticker, contracts, fetched_ts, None,
    (spot, spot_ts), capture), with the chain's one spot and its trade time and whether the sweep
    stored it as its window's capture. A chain missing a part is never returned.
    """
    tk, ts = msg["ticker"], float(msg["ts_recv"])
    out: list[ChainSettled] = []
    cur = _chain_parts.get(tk)
    if cur is not None and cur["ts"] != ts:
        out.append(
            (
                tk,
                None,
                ts,
                f"the daemon's chain of {tk} arrived with "
                f"{len(cur['got'])} of its {cur['parts']} parts",
                None,
                False,
            )
        )
        del _chain_parts[tk]
        cur = None
    if "failed" in msg:
        _chain_parts.pop(tk, None)
        return [*out, (tk, None, ts, str(msg["failed"]), None, False)]
    if cur is None:
        if int(msg["part"]) != 0:
            return out  # a chain begun before this console connected: not its chain
        cur = _chain_parts[tk] = {"ts": ts, "parts": int(msg["parts"]), "got": {}}
    cur["got"][int(msg["part"])] = msg["contracts"]
    if len(cur["got"]) == cur["parts"]:
        del _chain_parts[tk]
        out.append(
            (
                tk,
                [c for i in range(cur["parts"]) for c in cur["got"][i]],
                ts,
                None,
                (msg["spot"], msg["spot_ts"]),
                msg["capture"],
            )
        )
    return out


def _tick(sym: str) -> None:
    if FEED.on_tick is None:
        return
    try:
        FEED.on_tick(sym)
    except Exception as e:  # counted + WARNING; ingest must go on
        FEED.tick_failures += 1
        if FEED.tick_failures & (FEED.tick_failures - 1) == 0:
            log.warning(
                "tick callback failed for %s (%s failures): %s",
                sym,
                FEED.tick_failures,
                e,
                exc_info=True,
            )


def _flow(sym: str) -> None:
    if FEED.on_flow is not None:
        FEED.on_flow(sym)


class ServiceFeed(TypedDict):
    """One Schwab option service's feed for a contract, as the page shows it (_service_feed)."""

    state: str
    text: str


class FeedHealth(TypedDict):
    """A contract's three feeds on the Flow panel: the console's own, and Schwab's two services."""

    replay: str
    l1: ServiceFeed
    book: ServiceFeed


class StreamingPlane(TypedDict):
    """Whether the daemon streams a contract and is receiving it.

    Built by get_option_contract_streaming_diagnostics. `subscription_active`: it is held and its
    LEVELONE_OPTIONS feed is live; `subscription_text`: the Flow panel's badge for it.
    """

    subscription_state: str
    subscription_active: bool
    subscription_text: str
    feed_health: FeedHealth


def _service_feed(symbol: str, service: str, now: float) -> ServiceFeed:
    """One Schwab option service's feed for contract `symbol` at `now`, as the page shows it.

    Its state by the one live rule (live_market_plane.live_state: LIVE, OFFLINE or NOT LIVE), and
    how long ago the daemon last received anything on that service (its own report).
    """
    status = _lmp.daemon_status(now)
    health = None if status is None else status["health"].get(service)
    state = _lmp.live_state(symbol, service, now)[0]
    age = None if health is None else health["age_sec"]
    return {
        "state": state,
        # as the page shows it: "LIVE · 3s", or the state alone with no report from the daemon
        "text": state if age is None else f"{state} · {time_et.age_text(age)}",
    }


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


#: the option quote fields the levels are priced from: a message carrying one reprices (a
#: streamed contract's volume and its Greeks; its open interest is the chain's)
_REPRICE_FIELDS = ("TOTAL_VOLUME", "GAMMA", "DELTA", "THETA", "VEGA", "RHO", "VOLATILITY")


def _ingest_pushed(topic: str, msg: dict[str, Any]) -> None:
    """Apply ONE daemon-pushed Schwab stream message to the live planes.

    Every timestamp written is the message's own `ts_recv` -- the daemon's receive time for
    it -- never the time this console processed it (a delayed message must not read as
    fresh).

      quote.SYM    LEVELONE_EQUITIES -> order-flow state (the tape), and the equity's tick; the
                   live price is the daemon's price row (live_price_rows.price_row), never
                   rebuilt here
      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book, its recent books and the
                   imbalance readout's value of both books then held; OPTIONS_BOOK -> the option
                   contract's book
      optquote.SYM LEVELONE_OPTIONS -> order-flow state for the contract
      optquotes    Schwab's /quotes answer for option contracts -> each contract's newest values
                   (state.push_rest_quotes), at the answer's receive time
      markets.DATE Schwab's /markets answer -> that date's sessions (time_et), when it is a 200

    Every equity quote, every option quote carrying a _REPRICE_FIELDS value, and every contract
    of a /quotes answer, is passed to the tick callback. Each message is the daemon's own
    constructor's (stream_spine.quote_msg, book_msg, verbatim_msg, bar_msg; chain_sweep's), so
    its symbol, receive time and Schwab payload are there; a message that fails to apply raises,
    and _bus_loop counts it (Feed.apply_failures).
    """
    if topic.startswith("chain."):
        _apply_chain_part(msg)
        return
    if topic.startswith("markets."):
        if msg["status"] == HTTPStatus.OK:
            record_markets(msg["answer"])
        return
    if topic in _APPLY_BY_TOPIC:
        _APPLY_BY_TOPIC[topic](msg)
        return
    kind = topic.split(".", 1)[0]
    if kind in ("bar1m", "pricehistory"):  # the bar writer's: a streamed bar, a price history
        streamed_bars.put(msg)
        return
    apply = _APPLY_BY_KIND.get(kind)
    if apply is not None:
        apply(topic, msg)


def _apply_chain_part(msg: dict[str, Any]) -> None:
    """Take a chain's part; each chain it completes goes to the chain callback."""
    for done in assemble_chain_part(msg):
        if FEED.on_chain is not None:
            FEED.on_chain(*done)


def _apply_rest_quotes(msg: dict[str, Any]) -> None:
    """Take a /quotes answer: each contract's newest values, its ticker repriced now.

    The answer's time is the daemon's receive time for it (`ts_recv`).
    """
    received = float(msg["ts_recv"])
    push_rest_quotes(msg["answer"], received)
    for sym in msg["answer"]:
        _tick(sym)


def _answer_watchlist_request(msg: dict[str, Any]) -> None:
    """Resolve the watchlist request the daemon's record answers, while it still waits."""
    answer = _watchlist_answers.get(msg["request_id"])
    if answer is not None and not answer.done():
        answer.set_result(
            WatchlistAnswer(
                op=msg["op"],
                ticker=msg["ticker"],
                request_id=msg["request_id"],
                status=msg["status"],
                answer=msg["answer"],
                text=msg["text"],
            )
        )


def _apply_quote(topic: str, msg: dict[str, Any]) -> None:
    """Apply a version of a LEVELONE_EQUITIES record: the order-flow state, then the tick.

    A version that brought a trade is a print, kept with the bid and ask in force when it traded
    (state.push_level_one).
    """
    push_level_one("LEVELONE_EQUITIES", (topic, msg))
    _flow(msg["symbol"])
    _tick(msg["symbol"])


def _apply_book(_topic: str, msg: dict[str, Any]) -> None:
    """Apply a book message: an option contract's, or an equity venue's with its readout.

    Either one sends the panels that show it (the flow callback).
    """
    sym = msg["symbol"]
    book = push_book(sym, msg["content"], msg["service"])
    if msg["service"] != "OPTIONS_BOOK":
        if book is not None:
            recent.BOOKS.record(sym, msg["service"], book)
        recent.LEAN.record(
            sym,
            float(msg["ts_recv"]),
            book_readout({v: newest_book(sym, v) for v in BOOK_VENUES}),
        )
    _flow(sym)


def _apply_option_quote(topic: str, msg: dict[str, Any]) -> None:
    """Apply a version of a LEVELONE_OPTIONS record: the contract's tape and look-back.

    A version that brought a trade is a print, kept with the bid and ask in force when it traded
    (state.push_level_one). Every version sends the chain screens its values (the flow callback);
    a tick when its message brought a value the levels use (a merged record holds the last of
    each field; only one this message brought, received at its receive time, is new).
    """
    sym, content, stamps = msg["symbol"], msg["content"], msg["field_ts"]
    push_level_one("LEVELONE_OPTIONS", (topic, msg))
    _flow(sym)
    if any(f in content and stamps[f][1] == msg["ts_recv"] for f in _REPRICE_FIELDS):
        _tick(sym)


#: each symbol's message, by its topic's kind, and what applies it (_ingest_pushed)
_APPLY_BY_KIND = {"quote": _apply_quote, "book": _apply_book, "optquote": _apply_option_quote}
#: a whole-topic message (no one symbol), and what applies it (_ingest_pushed)
_APPLY_BY_TOPIC = {"watchlist": _answer_watchlist_request, "optquotes": _apply_rest_quotes}
#: the records the console applies in one turn of its loop (_bus_loop): about 4 ms of work at
#: the 20-44 us one takes (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json through
#: _ingest_pushed), the interpreter's switch interval
RECORDS_PER_TURN = 200


def _apply(topic: str, msg: dict[str, Any]) -> None:
    """Apply one bus record (_ingest_pushed); a failure is counted and logged, never raised."""
    try:
        _ingest_pushed(topic, msg)
    except Exception as e:  # counted + WARNING; the next record is still applied
        FEED.apply_failures += 1
        if FEED.apply_failures & (FEED.apply_failures - 1) == 0:
            log.warning(
                "a %s record not applied (%s failures): %s",
                topic,
                FEED.apply_failures,
                e,
                exc_info=True,
            )


async def _bus_loop(bus: MessageBus) -> None:
    """Every Schwab record on the daemon's bus, as it changes, applied the moment it does.

    Applied by _ingest_pushed: the console runs in the daemon's program and reads its one bus,
    no copy sent over a socket. A chain's record is its parts, in order. Up to RECORDS_PER_TURN
    records are applied in one turn of the loop, and a chain ends its turn: each turn waits to
    take back Python's interpreter lock from the program's busy threads (up to the switch
    interval, 5 ms), so a turn per record left each contract a pass of thousands behind, and a
    turn never holds the daemon's status beat and the routes past a few milliseconds. A record is
    applied as taken: one that waits in its turn behind a chain while newer messages come is the
    version taken, never the bus's newer one, and each trade is its own (stream_spine LATEST).

    A record that fails to apply is counted (Feed.apply_failures) and logged with its traceback
    (at the 1st, 2nd, 4th, 8th... failure: one on every message would flood the log), and the
    next is applied: one record never ends the console's data.
    """
    sub = bus.subscribe("", policy=LATEST)
    record: dict[str, Any] | list[dict[str, Any]]
    try:
        while FEED.running:
            for topic, record in [await sub.get(), *sub.taken(RECORDS_PER_TURN - 1)]:
                if is_forwarded(topic, record):
                    for msg in record if isinstance(record, list) else [record]:
                        _apply(topic, msg)
                if isinstance(record, list):
                    await asyncio.sleep(0)
            await asyncio.sleep(0)
    finally:
        bus.unsubscribe(sub)


async def _beat_loop() -> None:
    """Every HEARTBEAT_SEC, the daemon's status beat: the console restamps what is live.

    The beat is live_ui's, the one record of whether the daemon and Schwab are live.
    """
    while FEED.running:
        await asyncio.sleep(HEARTBEAT_SEC)
        if FEED.on_feed is not None:
            FEED.on_feed()


#: a contract's subscription, as the Flow panel shows it: the daemon's option rule holds it on
#: LEVELONE_OPTIONS, or it does not (capture.Daemon.pick_options streams each ticker's contracts
#: the heatmap shows first); and the badge's word for one held while its feed is live
SUBSCRIBED, NOT_STREAMED = "SUBSCRIBED", "NOT STREAMED"
ACTIVE = "ACTIVE"


def get_option_contract_streaming_diagnostics(for_contract: str, now: float) -> StreamingPlane:
    """Whether the daemon streams `for_contract` and is receiving it at `now`.

    This is distinct from the book's own content ages (options_live_payload): its subscription
    (SUBSCRIBED / NOT STREAMED, from the symbols on the latest beat), and each feed by the one
    live rule
    (live_market_plane.live_state). A missing beat keeps that last subscription.
    The feed health says whether it is live. The badge the page draws is served with it: ACTIVE
    only while the contract is held and its LEVELONE_OPTIONS feed is live; a held contract whose
    feed is not live reads that feed's state (OFFLINE: its feed down; NOT LIVE: its market not
    trading); one not held reads NOT STREAMED.
    """
    c = ticker_storage_key(for_contract)
    levelone = _lmp.feed_now(now).held.get("LEVELONE_OPTIONS")
    l1 = _service_feed(c, "LEVELONE_OPTIONS", now)
    healthy = bool(FEED.running and l1["state"] == _lmp.LIVE)
    subscribed = levelone is not None and c in levelone
    active = subscribed and l1["state"] == _lmp.LIVE
    return {
        "subscription_state": SUBSCRIBED if subscribed else NOT_STREAMED,
        "subscription_active": active,
        "subscription_text": ACTIVE if active else l1["state"] if subscribed else NOT_STREAMED,
        "feed_health": {
            "replay": "healthy" if healthy else "stale" if FEED.running else "not connected",
            "l1": l1,
            "book": _service_feed(c, "OPTIONS_BOOK", now),
        },
    }


def bind_daemon(daemon: Daemon | None) -> None:
    """Bind the capture daemon this console runs in (capture.run, before the web server starts).

    Its bus is the console's one source, and its requests go to it; None: no daemon (a test's end).
    Each symbol's top of book, Greeks and volume are read from its bus's records (bind_bus).
    """
    FEED.daemon = daemon
    if daemon is not None:
        bind_bus(daemon.bus.current)


def start_order_flow_stream(
    on_tick_callback: Callable[[str], None] | None = None,
    on_chain_callback: Callable[..., None] | None = None,
    on_feed_callback: Callable[[], None] | None = None,
    on_flow_callback: Callable[[str], None] | None = None,
) -> bool:
    """Start reading the daemon's bus (bind_daemon) on the event loop.

    False when no daemon runs in this program.
    """
    if FEED.daemon is None:
        log.error("no capture daemon runs in this program: the console has no data")
        return False
    if FEED.task is not None and not FEED.task.done():
        log.info("Live-plane feed already running")
        return True
    FEED.on_tick, FEED.on_chain = on_tick_callback, on_chain_callback
    FEED.on_feed, FEED.on_flow = on_feed_callback, on_flow_callback
    FEED.running = True
    FEED.task = asyncio.get_event_loop().create_task(
        _run_feed(FEED.daemon.bus), name="daemon-bus-feed"
    )
    log.info("Live-plane feed started (source=the capture daemon's bus, this program)")
    return True


async def _run_feed(bus: MessageBus) -> None:
    await asyncio.gather(_bus_loop(bus), _beat_loop())


def stop_order_flow_stream() -> None:
    """Clear the live state the feed fed and cancel its task.

    The task logs FEED_LOOP_STOP_DONE when it ends.
    """
    FEED.running = False
    clear_all_live_state()
    task = FEED.task
    if task is not None and not task.done():
        task.cancel()
    FEED.task = None
    _log_stream("FEED_CANCEL_REQUESTED")
