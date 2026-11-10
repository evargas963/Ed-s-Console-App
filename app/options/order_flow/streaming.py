"""The console's live-plane feed for every watchlist ticker.

It reads the capture daemon's one bus
(app.market_data.schwab.streaming.capture), in the same program. It opens no Schwab connection:
the daemon holds the one Schwab socket and is the one producer.

Each Schwab record on the bus is applied the moment it changes (_bus_loop -> _ingest_pushed) to
the console's planes. The database is not in the live path: stream_capture.db is the daemon's
record, and no screen value is read from it.

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
from typing import Any

import live_market_plane as _lmp
import live_price_rows
import time_et
from app.market_data.schwab.streaming.live_push import is_forwarded
from app.market_data.schwab.streaming.live_ui import HEARTBEAT_SEC
from app.options.order_flow import history as recent
from app.options.order_flow.engine import BOOK_VENUES, book_readout
from app.options.order_flow.state import (
    clear_all_live_state,
    get_stream_greeks,
    newest_book,
    option_top,
    push_book,
    push_level_one,
    push_option_top,
    push_rest_quotes,
)
from instrument_identity import ticker_storage_key
from stream_spine import LATEST
from time_et import record_markets

log = logging.getLogger(__name__)


def price_row(ticker: str, now: float) -> dict:
    """Return `ticker`'s price row at `now`.

    It is the daemon's one row (live_price_rows.price_row), the one the browser reads.
    """
    return live_price_rows.price_row(ticker, now)


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


#: the capture daemon this console runs in (start_order_flow_stream): watchlist requests and the
#: Flow panel's contract go to it
_daemon = None
#: request id -> the future the daemon's watchlist record for it resolves
#: (_answer_watchlist_request)
_watchlist_answers: dict[int, asyncio.Future] = {}
#: each watchlist request's id, unique in this process (an id, not a time)
_request_ids = itertools.count(1)
#: how long a watchlist request waits for the daemon's record (an add waits on Schwab's /quotes
#: answer)
WATCHLIST_ANSWER_SEC = 30.0


async def watchlist_request(action: str, ticker: str) -> dict:
    """Send an add or a removal ("add" | "remove") of `ticker` to the daemon.

    The daemon keeps the watchlist; this returns its record once the daemon has answered
    (capture.watchlist_message: the list, what happened, Schwab's /quotes answer to an add's
    check). Raises ConnectionError while no daemon runs in this program, TimeoutError when no
    record comes in WATCHLIST_ANSWER_SEC.
    """
    if _daemon is None:
        raise ConnectionError("no capture daemon runs in this program")
    rid = next(_request_ids)
    answer = asyncio.get_running_loop().create_future()
    _watchlist_answers[rid] = answer
    try:
        _daemon.console_frame({"op": "watchlist", "action": action, "ticker": ticker, "id": rid})

        return await asyncio.wait_for(answer, WATCHLIST_ANSWER_SEC)
    finally:
        del _watchlist_answers[rid]


async def select_flow_contract(contract: str | None) -> None:
    """Tell the daemon the Flow panel's selection (None: none).

    The daemon keeps it (capture.Daemon.flow_contract) and streams it on both option services on
    top of its rule.
    """
    if _daemon is not None:
        _daemon.console_frame({"op": "flow_contract", "contract": contract})


# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: asyncio.Task | None = None
_feed_running = False

#: Called with the symbol of every streamed equity quote, every option quote carrying a
#: _REPRICE_FIELDS value and every contract of a /quotes answer (server._on_stream_tick:
#: reprices its ticker).
#: Runs on the event loop, so it must return at once.
_on_tick_callback: Callable[[str], None] | None = None
_on_feed_callback: Callable[[], None] | None = None
#: Called with the symbol of every streamed equity quote and equity book (server.flow_changed:
#: the pages showing its order flow get it again). Runs on the event loop, so it returns at once.
_on_flow_callback: Callable[[str], None] | None = None
_tick_callback_failures = 0
#: Every streamed 1-minute bar (bar1m.SYM, Schwab CHART_EQUITY), for server._bar_writer to write;
#: None is server.stop_bar_writer's stop.
streamed_bars: queue.SimpleQueue[dict | None] = queue.SimpleQueue()
#: Called on the event loop with what assemble_chain_part settles: (ticker, contracts, fetched_ts,
#: None, (spot, spot_ts)) for each whole chain the daemon fetched, and (ticker, None, ts, reason,
#: None) for one it could not deliver (server._on_chain).
_on_chain_callback: Callable[..., None] | None = None
#: ticker -> the chain being received: {"ts", "parts", "got": {part: contracts}}
_chain_parts: dict[str, dict] = {}


def assemble_chain_part(
    msg: dict,
) -> list[tuple[str, list | None, float, str | None, tuple | None]]:
    """One chain message from the daemon (complete_chain_capture.chain_messages) -> what it settles.

    In order: a chain whose parts did not all arrive before the next one began
    (ticker, None, ts, reason, None); a fetch that failed (ticker, None, ts, Schwab's answer, None);
    the whole chain once its last part is in (ticker, contracts, fetched_ts, None, (spot, spot_ts)),
    with the chain's one spot and its trade time. A chain missing a part is never returned.
    """
    tk, ts = msg.get("ticker"), msg.get("ts_recv")
    if not tk or not isinstance(ts, (int, float)):
        return []
    out = []
    cur = _chain_parts.get(tk)
    if cur is not None and cur["ts"] != ts:
        out.append(
            (
                tk,
                None,
                float(ts),
                f"the daemon's chain of {tk} arrived with "
                f"{len(cur['got'])} of its {cur['parts']} parts",
                None,
            )
        )
        del _chain_parts[tk]
        cur = None
    if "failed" in msg:
        _chain_parts.pop(tk, None)
        return [*out, (tk, None, float(ts), str(msg["failed"]), None)]
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
                float(ts),
                None,
                (msg["spot"], msg["spot_ts"]),
            )
        )
    return out


def _tick(sym: str) -> None:
    global _tick_callback_failures
    if _on_tick_callback is None:
        return
    try:
        _on_tick_callback(sym)
    except Exception as e:  # counted + WARNING; ingest must go on
        _tick_callback_failures += 1
        if _tick_callback_failures & (_tick_callback_failures - 1) == 0:
            log.warning(
                "tick callback failed for %s (%s failures): %s",
                sym,
                _tick_callback_failures,
                e,
                exc_info=True,
            )


def _flow(sym: str) -> None:
    if _on_flow_callback is not None:
        _on_flow_callback(sym)


def _service_feed(symbol: str, service: str, now: float) -> dict:
    """One Schwab option service's feed for contract `symbol` at `now`, as the page shows it.

    Its state by the one live rule (live_market_plane.live_state: LIVE, OFFLINE or NOT LIVE), and
    how long ago the daemon last received anything on that service (its own report).
    """
    status = _lmp.daemon_status(now)
    reports = status.get("health") if status is not None else None
    health = reports.get(service) if reports is not None else None
    state = _lmp.live_state(symbol, service, now)[0]
    age = health.get("age_sec") if health is not None else None
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


def _ingest_pushed(topic: str, msg: Any) -> None:
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
    of a /quotes answer, is passed to the tick callback. A message missing its symbol, its
    receive time or its Schwab payload is dropped whole: nothing is applied with a guessed
    part.
    """
    if not isinstance(msg, dict):
        return
    if topic.startswith("chain."):
        _apply_chain_part(msg)
        return
    if topic.startswith("markets."):
        if msg["status"] == 200:
            record_markets(msg["answer"])
        return
    if topic in _APPLY_BY_TOPIC:
        _APPLY_BY_TOPIC[topic](msg)
        return
    sym = msg.get("symbol")
    ts = msg.get("ts_recv")
    if not sym or not isinstance(ts, (int, float)):
        return
    ts = float(ts)
    kind = topic.split(".", 1)[0]
    if kind in ("bar1m", "pricehistory"):  # the bar writer's: a streamed bar, a price history
        streamed_bars.put(msg)
        return
    received = {f: stamp[1] for f, stamp in msg["field_ts"].items()} if "field_ts" in msg else None
    apply = _APPLY_BY_KIND.get(kind)
    if apply is not None:
        apply(sym, ts, msg, received)


def _apply_chain_part(msg: dict) -> None:
    """Take a chain's part; each chain it completes goes to the chain callback."""
    for done in assemble_chain_part(msg):
        if _on_chain_callback is not None:
            _on_chain_callback(*done)


def _apply_rest_quotes(msg: dict) -> None:
    """Take a /quotes answer: each contract's newest values, its ticker repriced now.

    The answer's time is the daemon's receive time for it (`ts_recv`).
    """
    received = float(msg["ts_recv"])
    push_rest_quotes(msg["answer"], received)
    for sym in msg["answer"]:
        _tick(sym)


def _answer_watchlist_request(msg: dict) -> None:
    """Resolve the watchlist request the daemon's record answers, while it still waits."""
    answer = _watchlist_answers.get(msg["request_id"])
    if answer is not None and not answer.done():
        answer.set_result(msg)


def _apply_quote(sym: str, ts: float, msg: dict, received: dict | None) -> None:
    """Apply a LEVELONE_EQUITIES message: the order-flow state, then the equity's tick."""
    item = msg.get("native")
    if not isinstance(item, dict):
        return
    push_level_one(sym, item, ts_recv=ts, field_received=received)
    _flow(sym)
    _tick(sym)


def _apply_book(sym: str, ts: float, msg: dict, _received: dict | None) -> None:
    """Apply a book message: an option contract's, or an equity venue's with its readout."""
    content = msg.get("content")
    if not isinstance(content, dict):
        return
    book = push_book(sym, content, msg["service"])
    if msg.get("service") == "OPTIONS_BOOK":
        return
    if book is not None:
        recent.BOOKS.record(sym, msg["service"], book, ts)
    recent.LEAN.record(sym, ts, book_readout({v: newest_book(sym, v) for v in BOOK_VENUES}))
    _flow(sym)


def _apply_option_quote(sym: str, ts: float, msg: dict, received: dict | None) -> None:
    """Apply a LEVELONE_OPTIONS message: the contract's order-flow state and tape.

    A tick when the newest message carried a value the levels use (a merged record holds the last
    of each field; only one this message brought is new).
    """
    content = msg.get("content")
    if not isinstance(content, dict):
        return
    push_level_one(sym, content, ts_recv=ts, field_received=received)
    push_option_top(sym, content)
    recent.TAPE.record(sym, content, ts, option_top(sym), get_stream_greeks(sym))
    if any(f in content and (received is None or received[f] == ts) for f in _REPRICE_FIELDS):
        _tick(sym)


#: each symbol's message, by its topic's kind, and what applies it (_ingest_pushed)
_APPLY_BY_KIND = {"quote": _apply_quote, "book": _apply_book, "optquote": _apply_option_quote}
#: a whole-topic message (no one symbol), and what applies it (_ingest_pushed)
_APPLY_BY_TOPIC = {"watchlist": _answer_watchlist_request, "optquotes": _apply_rest_quotes}


async def _bus_loop(bus) -> None:
    """Every Schwab record on the daemon's bus, as it changes, applied the moment it does.

    Applied by _ingest_pushed: the console runs in the daemon's program and reads its one bus,
    no copy sent over a socket. A chain's record is its parts, in order. Each record handed over
    yields, so a burst of them never holds the loop: the daemon's status beat and every route
    take a turn.
    """
    sub = bus.subscribe("", policy=LATEST)
    try:
        while _feed_running:
            topic, record = await sub.get()
            if not is_forwarded(topic, record):
                continue
            for msg in record if isinstance(record, list) else [record]:
                _ingest_pushed(topic, msg)
            await asyncio.sleep(0)
    finally:
        bus.unsubscribe(sub)


async def _beat_loop() -> None:
    """Every HEARTBEAT_SEC, the daemon's status beat: the console restamps what is live.

    The beat is live_ui's, the one record of whether the daemon and Schwab are live.
    """
    while _feed_running:
        await asyncio.sleep(HEARTBEAT_SEC)
        if _on_feed_callback is not None:
            _on_feed_callback()


#: a contract's subscription, as the Flow panel shows it: the daemon's option rule holds it on
#: LEVELONE_OPTIONS, or it does not (capture.Daemon.pick_options streams each ticker's contracts
#: the heatmap shows first)
SUBSCRIBED, NOT_STREAMED = "SUBSCRIBED", "NOT STREAMED"


def get_option_contract_streaming_diagnostics(for_contract: str, now: float) -> dict[str, Any]:
    """Whether the daemon streams `for_contract` and is receiving it at `now`.

    This is distinct from the book's own content ages (options_live_payload): its subscription
    (SUBSCRIBED / NOT STREAMED, from the symbols on the latest beat), and each feed by the one
    live rule
    (live_market_plane.live_state). A missing beat keeps that last subscription.
    The feed health says whether it is live. The page paints ACTIVE only while that feed is live.
    """
    c = ticker_storage_key(for_contract)
    levelone = _lmp.feed_now(now).held.get("LEVELONE_OPTIONS")
    l1 = _service_feed(c, "LEVELONE_OPTIONS", now)
    healthy = bool(_feed_running and l1["state"] == _lmp.LIVE)
    return {
        "subscription_state": SUBSCRIBED
        if levelone is not None and c in levelone
        else NOT_STREAMED,
        "feed_health": {
            "replay": "healthy" if healthy else "stale" if _feed_running else "not connected",
            "l1": l1,
            "book": _service_feed(c, "OPTIONS_BOOK", now),
        },
    }


def bind_daemon(daemon) -> None:
    """Bind the capture daemon this console runs in (capture.run, before the web server starts).

    Its bus is the console's one source, and its requests go to it.
    """
    global _daemon
    _daemon = daemon


def start_order_flow_stream(
    on_tick_callback: Callable[[str], None] | None = None,
    on_chain_callback: Callable[..., None] | None = None,
    on_feed_callback: Callable[[], None] | None = None,
    on_flow_callback: Callable[[str], None] | None = None,
) -> bool:
    """Start reading the daemon's bus (bind_daemon) on the event loop.

    False when no daemon runs in this program.
    """
    global _feed_task, _feed_running, _on_tick_callback, _on_chain_callback, _on_feed_callback
    global _on_flow_callback
    if _daemon is None:
        log.error("no capture daemon runs in this program: the console has no data")
        return False
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _on_chain_callback = on_chain_callback
    _on_feed_callback = on_feed_callback
    _on_flow_callback = on_flow_callback
    _feed_running = True
    _feed_task = asyncio.get_event_loop().create_task(
        _run_feed(_daemon.bus), name="daemon-bus-feed"
    )
    log.info("Live-plane feed started (source=the capture daemon's bus, this program)")
    return True


async def _run_feed(bus) -> None:
    await asyncio.gather(_bus_loop(bus), _beat_loop())


def stop_order_flow_stream() -> None:
    """Clear the live state the feed fed and cancel its task.

    The task logs FEED_LOOP_STOP_DONE when it ends.
    """
    global _feed_running, _feed_task
    _feed_running = False
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("FEED_CANCEL_REQUESTED")
