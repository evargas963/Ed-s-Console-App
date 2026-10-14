"""
Live-plane feed for the single active UI ticker — READ-ONLY consumer of the canonical
capture daemon (app.market_data.schwab.streaming.capture), never a second Schwab session.

SINGLE-STREAM-AUTHORITY LAW (root-fixed here): this module used to own its own
`schwab.streaming.StreamClient`, logging into Schwab independently of the canonical
capture daemon — two authenticated sockets on one account, racing each other for the
same market truth. It now opens ZERO Schwab connections. The daemon is the one producer.

LIVE PUSH (2026-09-23): the daemon forwards every Schwab stream message to this module over
a local WebSocket (app.market_data.schwab.streaming.live_push, ws://127.0.0.1:8799) the
moment it arrives, and this module applies it to the in-process planes
(`app.options.order_flow.state`, `live_market_plane`). The database is NOT in the live
path: it used to be -- this module polled `stream_capture.db` every 0.5s -- which put a
disk write, a commit and a poll between Schwab and the screen. stream_capture.db stays the
permanent record (options history reads it); nothing live reads it. If the push connection
drops, the live values go stale and the screen says so; nothing falls back to the database
(operator rule 2026-09-23: no fallbacks).

The daemon streams every ticker on its watchlist (capture.Daemon.watchlist, the one list), and
picks the option contracts it streams itself (capture.Daemon.pick_options, the option rule).
Over the same socket this module sends the operator's adds and removals of watchlist tickers
(watchlist_request), each answered by the daemon's watchlist record, and the contract selected on
the Flow panel (select_flow_contract), which the daemon streams on top of the rule. The daemon's
one-second status comes on the price-row connection (_rows_loop, live_ui's "feed" beat), where
no chain waits ahead of it, and is the one source for "is the daemon / Schwab alive", the
watchlist and "what does Schwab hold".

Public API: `start_order_flow_stream` / `stop_order_flow_stream`
/ `get_option_contract_streaming_diagnostics`.
"""

from __future__ import annotations

import asyncio
import json
import queue
import logging
import time
from typing import Any, Callable, Optional

from instrument_identity import ticker_storage_key
import push_changes
from app.options.order_flow import history as recent

from app.options.order_flow.state import (
    ContractRecord,
    clear_all_live_state,
    drop_unlisted,
    clear_symbol,
    contract,
    push_book,
    push_contract,
)

import live_market_plane as _lmp
from time_et import record_markets

log = logging.getLogger(__name__)

#: The daemon's live push endpoint (app.market_data.schwab.streaming.live_push), the feed's
#: (start_order_flow_stream -> _feed_loop).
from app.market_data.schwab.streaming.live_push import LIVE_PUSH_HOST, LIVE_PUSH_PORT
from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT

LIVE_PUSH_URL = f"ws://{LIVE_PUSH_HOST}:{LIVE_PUSH_PORT}"
#: The daemon's Schwab push (live_ui): the console's price rows (_rows_loop).
LIVE_UI_URL = f"ws://127.0.0.1:{LIVE_UI_PORT}"
#: Wait between reconnect attempts when the daemon's push server is down. While it is down
#: no live value is refreshed -- the freshness checks turn them stale; nothing substitutes.
PUSH_RECONNECT_SEC = 1.0


#: the console's push connection to the daemon while it is open (_feed_loop): watchlist requests go on it
_push_ws = None
#: request id -> the future the daemon's watchlist record for it resolves (_ingest_pushed)
_watchlist_answers: "dict[int, asyncio.Future]" = {}
#: how long a watchlist request waits for the daemon's record (an add waits on Schwab's /quotes answer)
WATCHLIST_ANSWER_SEC = 30.0


async def watchlist_request(action: str, ticker: str) -> dict:
    """An add or a removal ("add" | "remove") of `ticker`, sent to the daemon, which keeps the
    watchlist; its record once the daemon has answered (capture.watchlist_message: the list, what
    happened, Schwab's /quotes answer to an add's check). Raises ConnectionError while the push
    connection is not open, TimeoutError when no record comes in WATCHLIST_ANSWER_SEC."""
    ws = _push_ws
    if ws is None:
        raise ConnectionError("the capture daemon's push connection is not open")
    rid = time.time_ns()
    answer = asyncio.get_running_loop().create_future()
    _watchlist_answers[rid] = answer
    try:
        await ws.send(json.dumps({"op": "watchlist", "action": action, "ticker": ticker, "id": rid}))
        return await asyncio.wait_for(answer, WATCHLIST_ANSWER_SEC)
    finally:
        del _watchlist_answers[rid]


#: the contract Ed selected on the Flow panel, or None: the daemon streams it on both option
#: services on top of its option rule; sent on every connection to the daemon and on each change
_flow_contract: "str | None" = None


async def select_flow_contract(contract: "str | None") -> None:
    """The Flow panel's selection (None: none), told to the daemon now when connected, and on each
    connection after (serve_push), so a daemon restart keeps it."""
    global _flow_contract
    _flow_contract = contract
    if _push_ws is not None:
        await _push_ws.send(json.dumps({"op": "flow_contract", "contract": contract}))

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False

#: Called with the symbol of every streamed equity quote and option message
#: (server._on_stream_tick: reprices a viewed ticker). Runs on the event loop, so it must return at once.
_on_tick_callback: Optional[Callable[[str], None]] = None
_tick_callback_failures = 0
#: Every streamed 1-minute bar (bar1m.SYM, Schwab CHART_EQUITY), for server._bar_writer to write.
streamed_bars: "queue.SimpleQueue[dict]" = queue.SimpleQueue()
#: Called on the event loop with (ticker, round's start, None) when the daemon's round of a
#: ticker is in (its contracts' records hold its answers), and with (ticker, ts, reason) for one
#: that failed (server._on_chain).
_on_chain_callback: Optional[Callable[..., None]] = None


def _tick(sym: str) -> None:
    global _tick_callback_failures
    if _on_tick_callback is None:
        return
    try:
        _on_tick_callback(sym)
    except Exception as e:  # noqa: BLE001 -- counted + WARNING; ingest must go on
        _tick_callback_failures += 1
        if _tick_callback_failures & (_tick_callback_failures - 1) == 0:
            log.warning("tick callback failed for %s (%s failures): %s",
                        sym, _tick_callback_failures, e)


def _service_feed(symbol: "str | None", service: str, now: float) -> dict:
    """One Schwab service's feed for `symbol` at `now`, as the page shows it: LIVE by the one
    live rule (live_market_plane.feed_live_for), and when the daemon last received anything on
    that service (its own report; its age is labelled by the console's push)."""
    status = _lmp.daemon_status(now)
    reports = status.get("health") if status is not None else None
    health = reports.get(service) if reports is not None else None
    return {"state": "LIVE" if _lmp.feed_live_for(symbol, service, now) else "NOT LIVE",
            "last_ts": health.get("last_ts") if health is not None else None}


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


#: the LEVELONE_EQUITIES fields of a trade
_TRADE_FIELDS = ("LAST_PRICE", "LAST_SIZE", "TRADE_TIME_MILLIS")


def _ingest_pushed(topic: str, msg: Any) -> None:
    """Apply ONE daemon-pushed Schwab stream message to the live planes.

    The same plane-ingest calls the DB replay made, now fed straight from the daemon's
    bus. Every timestamp written is the message's own `ts_recv` -- the daemon's receive
    time for it -- never the time this console processed it (a delayed message must not
    read as fresh; 2026-09-23 audit P0).

      quote.SYM    LEVELONE_EQUITIES -> its trade into the one tape (history.TAPE); the live
                   price is the daemon's price row (_rows_loop), never rebuilt here
      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book; OPTIONS_BOOK -> the option
                   contract's book
      contract.SYM an option contract's one record (option_ledger) -> the mirror (push_contract),
                   its trade into the one tape
      chain.TK     a ticker's round is in, or why it failed -> the levels (server._on_chain)
      markets.DATE Schwab's /markets answer -> that date's sessions (time_et), when it is a 200

    Every option message is passed to the tick callback (an equity's tick is its price row's
    arrival). A message missing its symbol, its
    receive time or its Schwab payload is dropped whole: nothing is applied with a guessed
    part."""
    if not isinstance(msg, dict):
        return None
    if topic.startswith("chain."):
        if msg.get("ticker") and isinstance(msg.get("ts_recv"), (int, float)):
            if msg.get("opening"):
                drop_unlisted(msg["ticker"], float(msg["ts_recv"]))
            if _on_chain_callback is not None:
                _on_chain_callback(msg["ticker"], float(msg["ts_recv"]), msg.get("failed"))
        return None
    if topic.startswith("markets."):
        if msg["status"] == 200:
            record_markets(msg["answer"])
        return None
    if topic == "watchlist":                        # the daemon's answer to a watchlist request
        if msg["request_id"] in _watchlist_answers and not _watchlist_answers[msg["request_id"]].done():
            _watchlist_answers[msg["request_id"]].set_result(msg)
        return None
    sym = msg.get("symbol")
    ts = msg.get("ts_recv")
    if not sym or not isinstance(ts, (int, float)):
        return None
    ts = float(ts)
    kind = topic.split(".", 1)[0]
    if kind in ("bar1m", "pricehistory"):          # the bar writer's: a streamed bar, a price history
        if kind == "bar1m":
            _lmp.note_posted(sym, "CHART_EQUITY", ts)
        streamed_bars.put(msg)
        return None
    if kind == "quote":
        item = msg.get("native")
        if not isinstance(item, dict):
            return None
        # the trade's receive time: the message that carried it (its fields' own stamps), not a
        # later tick merged into the same current record
        trade_at = [stamp[1] for f, stamp in msg["field_ts"].items() if f in _TRADE_FIELDS]
        if trade_at:
            recent.TAPE.record_equity(sym, item, max(trade_at))
        push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "book":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_book(sym, content, msg["service"])
        _lmp.note_posted(sym, msg["service"], ts)
        if msg.get("service") != "OPTIONS_BOOK":
            recent.BOOKS.record(sym, msg["service"], content, ts)
            push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "contract":
        fields = msg.get("fields")
        if not isinstance(fields, dict):
            return None
        record = ContractRecord(fields, msg["field_ts"])
        push_contract(sym, record)
        if "streamTime" in record.times:         # Schwab's stream posted to it (REST does not)
            _lmp.note_posted(sym, "LEVELONE_OPTIONS", record.times["streamTime"][1])
        recent.TAPE.record_option(sym, fields, record.times, ts)
        _tick(sym)          # a record changes only when Schwab sent it something new
    return None


def _rows_wanted(now: float) -> "list[str]":
    """The price rows this console holds at `now`: every equity the daemon streams (its
    heartbeat's held LEVELONE_EQUITIES -- the watchlist and the market context, as Schwab
    accepted them)."""
    return sorted(_lmp.held_by_daemon("LEVELONE_EQUITIES", now))


async def _rows_loop(ui_url: str, reconnect_sec: float) -> None:
    """Take Schwab's LEVELONE_EQUITIES fields (_rows_wanted) and the daemon's status: one client
    of the daemon's Schwab push (`ui_url`, retried every `reconnect_sec`), resubscribed when what
    the daemon streams changes (checked on every frame). Each message's changed fields go to the
    console's price record (live_market_plane, which live_price_rows.price_row reads). The daemon
    beats every second with its whole status (`feed`), the one record of whether the daemon and
    Schwab are live (live_market_plane.record_feed_heartbeat); this connection carries no chain,
    so a beat never waits behind one. Silence or a lost connection is a feed down: the last values
    stand, not live. Each message is the equity's tick."""
    from websockets.asyncio.client import connect

    while _feed_running:
        try:
            async with connect(ui_url, max_size=None, open_timeout=5) as ws:
                sent = None
                while _feed_running:
                    want = _rows_wanted(time.time())
                    if want != sent:
                        await ws.send(json.dumps({"op": "subscribe", "symbols": want}))
                        sent = want
                    try:
                        frame = await asyncio.wait_for(ws.recv(), _lmp.FEED_HEARTBEAT_MAX_AGE_SEC)
                    except asyncio.TimeoutError:
                        _lmp.record_feed_down()      # the daemon beats every second: silence
                        _mark_liveness(time.time())
                        continue
                    msg = json.loads(frame)
                    if msg["type"] == "feed":
                        apply_heartbeat(msg["feed"])
                        _mark_liveness(time.time())
                    elif msg["type"] == "schwab":
                        for m in msg["messages"]:
                            if m["service"] == "LEVELONE_EQUITIES":   # Change: the fields Schwab changed
                                _lmp.record_from_level_one_equity(m["key"], m["content"], received_ts=float(m["ts_recv"]))
                                push_changes.changed(m["key"], push_changes.FLOW)   # its price record moved
                                _tick(m["key"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
            log.info("price rows unavailable (%s: %s); retrying in %.1fs",
                     type(e).__name__, e, reconnect_sec)
        _lmp.record_feed_down()            # no daemon, no live price -- visible at once
        _mark_liveness(time.time())
        if _feed_running:
            await asyncio.sleep(reconnect_sec)


async def serve_push(ws) -> None:
    """One connection to the daemon's live push, for its life: the Flow panel's contract sent first
    (select_flow_contract), the watchlist requests sent on it (watchlist_request), and every
    frame applied the moment it arrives (_ingest_pushed)."""
    global _push_ws
    # the daemon replays every record on a new connection, each in place of the one held: the
    # mirror is never emptied, so no calculation reads part of a ticker's contracts
    await ws.send(json.dumps({"op": "flow_contract", "contract": _flow_contract}))
    _push_ws = ws
    try:
        async for frame in ws:
            try:
                env = json.loads(frame)
            except (TypeError, ValueError):
                log.warning("live push: a frame that is not JSON was skipped: %r", frame[:200])
                continue
            _ingest_pushed(str(env["topic"]), env["msg"])
            # a frame already received is handed over without a wait, so a backlog of chain
            # parts would hold the loop: the daemon's status beat and every route take a turn
            await asyncio.sleep(0)
    finally:
        _push_ws = None


async def _feed_loop(push_url: str, ui_url: str, reconnect_sec: float) -> None:
    """Consume the daemon's live push (`push_url`) and its price rows (`ui_url`, _rows_loop)
    until the feed stops.

    Each frame is one Schwab stream message; it is applied the moment it arrives
    (_ingest_pushed) -- no poll interval, no database read. A dropped connection is retried
    every `reconnect_sec`; while it is down, the live values age out through their own
    freshness checks and the screen shows them stale. There is no second source."""
    from websockets.asyncio.client import connect

    rows = asyncio.create_task(_rows_loop(ui_url, reconnect_sec), name="daemon-price-rows")
    try:
        while _feed_running:
            try:
                async with connect(push_url, max_size=None, open_timeout=5,
                                   ping_interval=20, ping_timeout=20) as ws:
                    _log_stream("PUSH_CONNECTED", url=push_url)
                    await serve_push(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
                log.info("live push unavailable (%s: %s); retrying in %.1fs",
                         type(e).__name__, e, reconnect_sec)
            if _feed_running:
                await asyncio.sleep(reconnect_sec)
    finally:
        rows.cancel()
        await asyncio.gather(rows, return_exceptions=True)
        _lmp.record_feed_down()
        _log_stream("FEED_LOOP_STOP_DONE")


#: The two Schwab option services a contract streams on.
OPTION_PRODUCER_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


#: each shown feed's verdict (live, outage), by (symbol, Schwab service), when last marked
_verdicts: "dict[tuple[str, str], tuple]" = {}


def _shown_feeds() -> "set[tuple[str, str, str]]":
    """(ticker, symbol, service) of every feed an open page shows: each shown price row's
    LEVELONE_EQUITIES, and each feed a panel on screen is read from (push_changes.feeds)."""
    return {(s, s, "LEVELONE_EQUITIES") for s in push_changes.symbols()} | push_changes.feeds()


def _verdict(symbol: str, service: str, now: float) -> tuple:
    return _lmp.feed_live_for(symbol, service, now), _lmp.outage(symbol, service, now)


def _mark_liveness(now: float) -> None:
    """A feed an open page shows that went down or came back is a change of its ticker: the price
    row and every panel read from it are pushed again, marked (push_changes.changed)."""
    shown = _shown_feeds()
    moved = set()
    for s, svc in {(s, svc) for _tk, s, svc in shown}:
        verdict = _verdict(s, svc, now)
        if _verdicts.get((s, svc)) != verdict:
            _verdicts[(s, svc)] = verdict
            moved.add((s, svc))
    for tk in {tk for tk, s, svc in shown if (s, svc) in moved}:
        push_changes.changed(tk, push_changes.LIVE)


#: the option contracts the daemon's last applied status says its rule picks
_picked: "set[str]" = set()


def note_liveness(now: float) -> None:
    """The verdict of each feed an open page has just begun to show, as its first answers read
    it (on the event loop, before they are computed): only a later change of it is marked."""
    for _tk, s, svc in _shown_feeds():
        if (s, svc) not in _verdicts:
            _verdicts[(s, svc)] = _verdict(s, svc, now)


def apply_heartbeat(feed: Any) -> None:
    """Apply the daemon's status (`feed`, live_market_plane.record_feed_heartbeat) and forget the
    live state of each option contract its option rule picked before and picks no more (`options`)
    for a ticker it has ranked (`ranked`), so no screen shows that contract's last message as
    current. A connection that ends, a new one still asking, and a restarted daemon (it has ranked
    no ticker yet) release nothing (operator 2026-10-13: "On disconnect keep the last values,
    marked not live; reconnect's opening replaces them"); nor does a status not applied."""
    global _picked
    if _lmp.record_feed_heartbeat(feed) is None:
        return
    picked = set().union(*(feed["options"][s] for s in OPTION_PRODUCER_SERVICES))
    ranked = {ticker_storage_key(t) for t in feed["ranked"]}
    kept = set()
    for sym in _picked - picked:
        rec = contract(sym)
        tk = rec.fields.get("ticker") if rec is not None else None     # a stream-only record names none
        if tk is not None and ticker_storage_key(tk) not in ranked:
            kept.add(sym)                # its ticker's pick is not the rule's answer yet
        else:
            clear_symbol(sym)
    _picked = picked | kept


#: a contract's subscription, as the Flow panel shows it: the daemon's option rule holds it on
#: LEVELONE_OPTIONS, or it does not (capture.Daemon.pick_options streams each ticker's contracts
#: with the highest gamma)
SUBSCRIBED, NOT_STREAMED = "SUBSCRIBED", "NOT STREAMED"


def get_option_contract_streaming_diagnostics(for_contract: str, now: float) -> dict[str, Any]:
    """Whether the daemon streams `for_contract` and is receiving it at `now`, distinct from the
    book's own content ages (options_live_payload): its subscription (SUBSCRIBED / NOT STREAMED,
    from the daemon's live heartbeat: unknown is never confirmation), and each feed by the one live rule
    (live_market_plane.feed_live_for)."""
    c = ticker_storage_key(for_contract)
    healthy = bool(_feed_running and _lmp.feed_live_for(c, "LEVELONE_OPTIONS", now))
    return {
        "queried_contract": c,
        "subscription_state": SUBSCRIBED if c in _lmp.held_by_daemon("LEVELONE_OPTIONS", now) else NOT_STREAMED,
        "feed_health": {"replay": "healthy" if healthy else "stale" if _feed_running else "not connected",
                        "l1": _service_feed(c, "LEVELONE_OPTIONS", now),
                        "book": _service_feed(c, "OPTIONS_BOOK", now)},
    }


def start_order_flow_stream(on_tick_callback: Optional[Callable[[str], None]] = None,
                            on_chain_callback: Optional[Callable[..., None]] = None) -> bool:
    """Start the feed from the capture daemon (on the event loop)."""
    global _feed_task, _feed_running, _on_tick_callback, _on_chain_callback
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _on_chain_callback = on_chain_callback
    _feed_running = True
    _feed_task = asyncio.get_event_loop().create_task(
        _feed_loop(LIVE_PUSH_URL, LIVE_UI_URL, PUSH_RECONNECT_SEC), name="daemon-plane-feed")
    log.info("Live-plane feed started (source=capture daemon live push)")
    return True


STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    global _feed_running, _feed_task
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


