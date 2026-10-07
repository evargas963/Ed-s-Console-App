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
    clear_all_live_state,
    clear_symbol,
    push_book,
    push_level_one,
    push_option_top,
)

import live_market_plane as _lmp

log = logging.getLogger(__name__)

#: The daemon's live push endpoint (app.market_data.schwab.streaming.live_push). Module
#: attribute, read at connect time, so a test can point the feed at its own server.
from app.market_data.schwab.streaming.live_push import LIVE_PUSH_HOST, LIVE_PUSH_PORT
from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT

LIVE_PUSH_URL = f"ws://{LIVE_PUSH_HOST}:{LIVE_PUSH_PORT}"
#: The daemon's price-row push (live_ui), the one the browser reads.
LIVE_UI_URL = f"ws://127.0.0.1:{LIVE_UI_PORT}"
#: The daemon's finished price row per ticker (live_price_rows.price_row), exactly as it pushes
#: it to the browser. The console keeps no other copy of a live price; the rows are dropped when
#: the push is gone or silent for the live limit (live_market_plane.FEED_HEARTBEAT_MAX_AGE_SEC).
_price_rows: "dict[str, dict]" = {}


def price_row(ticker: str) -> "dict | None":
    return _price_rows.get(ticker_storage_key(ticker) or "")
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

#: Each option contract's last streamed message time (LEVELONE_OPTIONS or OPTIONS_BOOK), keyed
#: by ticker_storage_key.
_option_contract_last_update_ts: dict[str, float] = {}

#: Called with the symbol of every streamed equity quote and every option quote carrying
#: GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLUME (server._on_stream_tick: reprices a viewed
#: ticker). Runs on the event loop, so it must return at once.
_on_tick_callback: Optional[Callable[[str], None]] = None
_tick_callback_failures = 0
#: Every streamed 1-minute bar (bar1m.SYM, Schwab CHART_EQUITY), for server._bar_writer to write.
streamed_bars: "queue.SimpleQueue[dict]" = queue.SimpleQueue()
#: Called on the event loop with (ticker, contracts, fetched_ts, None) for each whole chain the
#: daemon fetched, and with (ticker, None, ts, reason) for one it could not deliver
#: (server._on_chain).
_on_chain_callback: Optional[Callable[..., None]] = None
#: ticker -> the chain being received: {"ts", "parts", "got": {part: contracts}}
_chain_parts: "dict[str, dict]" = {}


def assemble_chain_part(msg: dict) -> "list[tuple[str, list | None, float, str | None]]":
    """One chain message from the daemon (complete_chain_capture.chain_messages) -> what it
    settles, in order: a chain whose parts did not all arrive before the next one began
    (ticker, None, ts, reason); a fetch that failed (ticker, None, ts, Schwab's answer); the whole
    chain once its last part is in (ticker, contracts, fetched_ts, None). A chain missing a part
    is never returned."""
    tk, ts = msg.get("ticker"), msg.get("ts_recv")
    if not tk or not isinstance(ts, (int, float)):
        return []
    out = []
    cur = _chain_parts.get(tk)
    if cur is not None and cur["ts"] != ts:
        out.append((tk, None, float(ts), f"the daemon's chain of {tk} arrived with "
                    f"{len(cur['got'])} of its {cur['parts']} parts"))
        del _chain_parts[tk]
        cur = None
    if "failed" in msg:
        _chain_parts.pop(tk, None)
        return [*out, (tk, None, float(ts), str(msg["failed"]))]
    if cur is None:
        if int(msg["part"]) != 0:
            return out              # a chain begun before this console connected: not its chain
        cur = _chain_parts[tk] = {"ts": ts, "parts": int(msg["parts"]), "got": {}}
    cur["got"][int(msg["part"])] = msg.get("contracts") or []
    if len(cur["got"]) == cur["parts"]:
        del _chain_parts[tk]
        out.append((tk, [c for i in range(cur["parts"]) for c in cur["got"][i]], float(ts), None))
    return out


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


def _service_feed(symbol: "str | None", service: str) -> dict:
    """One Schwab service's feed for `symbol`, as the page shows it: LIVE by the one live rule
    (live_market_plane.feed_live_for), and how long ago the daemon last received anything on
    that service (its own report)."""
    health = ((_lmp.daemon_status() or {}).get("health") or {}).get(service) or {}
    return {"state": "LIVE" if _lmp.feed_live_for(symbol, service) else "NOT LIVE",
            "age_sec": health.get("age_sec")}


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


#: the option quote fields the levels are priced from: a message carrying one reprices
_REPRICE_FIELDS = ("GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME", "VOLUME")


def _ingest_pushed(topic: str, msg: Any) -> None:
    """Apply ONE daemon-pushed Schwab stream message to the live planes.

    The same plane-ingest calls the DB replay made, now fed straight from the daemon's
    bus. Every timestamp written is the message's own `ts_recv` -- the daemon's receive
    time for it -- never the time this console processed it (a delayed message must not
    read as fresh; 2026-09-23 audit P0).

      quote.SYM    LEVELONE_EQUITIES -> order-flow state (the tape); the live price is the
                   daemon's price row (_rows_loop), never rebuilt here
      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book; OPTIONS_BOOK -> the option
                   contract's book
      optquote.SYM LEVELONE_OPTIONS -> order-flow state for the contract

    Every option quote carrying GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLUME is passed to the
    tick callback (an equity's tick is its price row's arrival). A message missing its symbol, its
    receive time or its Schwab payload is dropped whole: nothing is applied with a guessed
    part."""
    if not isinstance(msg, dict):
        return None
    if topic.startswith("chain."):
        for done in assemble_chain_part(msg):
            if _on_chain_callback is not None:
                _on_chain_callback(*done)
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
        streamed_bars.put(msg)
        return None
    received = {f: stamp[1] for f, stamp in msg["field_ts"].items()} if "field_ts" in msg else None
    if kind == "quote":
        item = msg.get("native")
        if not isinstance(item, dict):
            return None
        push_level_one(sym, item, ts_recv=ts, field_received=received)
        push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "book":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_book(sym, content, msg["service"])
        if msg.get("service") == "OPTIONS_BOOK":
            _option_contract_last_update_ts[sym] = ts
        else:
            recent.BOOKS.record(sym, msg["service"], content, ts)
            push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "optquote":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_level_one(sym, content, ts_recv=ts, field_received=received)
        push_option_top(sym, content)
        recent.TAPE.record(sym, content, ts)
        _option_contract_last_update_ts[sym] = ts
        # a tick when the newest message carried a value the levels use (a merged record holds
        # the last of each field; only one this message brought is new)
        if any(f in content and (received is None or received[f] == ts) for f in _REPRICE_FIELDS):
            _tick(sym)
    return None


def _rows_wanted() -> "list[str]":
    """The price rows this console holds: every equity the daemon streams (its heartbeat's held
    LEVELONE_EQUITIES -- what the console asked for and the board, as Schwab accepted them)."""
    return sorted(((_lmp.daemon_status() or {}).get("held") or {}).get("LEVELONE_EQUITIES") or [])


async def _rows_loop() -> None:
    """Hold the daemon's price rows (_rows_wanted) and its status: one browser client of the
    daemon's price push, resubscribed when what the daemon streams changes (checked on every
    frame). The daemon beats every second with its whole status (`feed`), the one record of
    whether the daemon and Schwab are live (live_market_plane.record_feed_heartbeat); this
    connection carries no chain, so a beat never waits behind one. Silence or a lost connection
    is a feed down. Each row's arrival is the equity's tick."""
    from websockets.asyncio.client import connect

    while _feed_running:
        try:
            async with connect(LIVE_UI_URL, max_size=None, open_timeout=5) as ws:
                sent = None
                while _feed_running:
                    want = _rows_wanted()
                    if want != sent:
                        await ws.send(json.dumps({"op": "subscribe", "symbols": want}))
                        sent = want
                    try:
                        frame = await asyncio.wait_for(ws.recv(), _lmp.FEED_HEARTBEAT_MAX_AGE_SEC)
                    except asyncio.TimeoutError:
                        _price_rows.clear()          # the daemon beats every second: silence
                        _lmp.record_feed_down()
                        continue
                    msg = json.loads(frame)
                    if msg.get("type") == "feed":
                        _lmp.record_feed_heartbeat(msg.get("feed"))
                        _drop_released_options()
                    for row in msg.get("rows") or []:
                        _price_rows[row["ticker"]] = row
                        if msg.get("type") == "quotes":
                            _tick(row["ticker"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
            log.info("price rows unavailable (%s: %s); retrying in %.1fs",
                     type(e).__name__, e, PUSH_RECONNECT_SEC)
        _price_rows.clear()
        _lmp.record_feed_down()            # no daemon, no live price -- visible at once
        if _feed_running:
            await asyncio.sleep(PUSH_RECONNECT_SEC)


async def serve_push(ws) -> None:
    """One connection to the daemon's live push, for its life: the Flow panel's contract sent first
    (select_flow_contract), the watchlist requests sent on it (watchlist_request), and every
    frame applied the moment it arrives (_ingest_pushed)."""
    global _push_ws
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


async def _feed_loop() -> None:
    """Consume the daemon's live push (LIVE_PUSH_URL) until the feed stops.

    Each frame is one Schwab stream message; it is applied the moment it arrives
    (_ingest_pushed) -- no poll interval, no database read. A dropped connection is retried
    every PUSH_RECONNECT_SEC; while it is down, the live values age out through their own
    freshness checks and the screen shows them stale. There is no second source."""
    from websockets.asyncio.client import connect

    rows = asyncio.create_task(_rows_loop(), name="daemon-price-rows")
    try:
        while _feed_running:
            try:
                async with connect(LIVE_PUSH_URL, max_size=None, open_timeout=5,
                                   ping_interval=20, ping_timeout=20) as ws:
                    _log_stream("PUSH_CONNECTED", url=LIVE_PUSH_URL)
                    await serve_push(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
                log.info("live push unavailable (%s: %s); retrying in %.1fs",
                         type(e).__name__, e, PUSH_RECONNECT_SEC)
            if _feed_running:
                await asyncio.sleep(PUSH_RECONNECT_SEC)
    finally:
        rows.cancel()
        await asyncio.gather(rows, return_exceptions=True)
        _price_rows.clear()
        _lmp.record_feed_down()
        _log_stream("FEED_LOOP_STOP_DONE")


#: The two Schwab option services whose durable open coverage epochs constitute
#: PRODUCER-side subscription identity (as opposed to the server's desired state).
OPTION_PRODUCER_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def _read_producer_option_contracts() -> dict[str, list[str]]:
    """What Schwab holds per option service, from the daemon's status; empty when that status
    is missing or stale (unknown is never confirmation)."""
    held = (_lmp.daemon_status() or {}).get("held") or {}
    return {s: sorted(held.get(s) or []) for s in OPTION_PRODUCER_SERVICES}


#: the option contracts the daemon held at its last status (_drop_released_options)
_held_options: "set[str]" = set()


def _drop_released_options() -> None:
    """Forget the live state of each option contract the daemon stopped streaming (its option
    rule moved off it), so no screen shows that contract's last message as current."""
    global _held_options
    held = set().union(*_read_producer_option_contracts().values())
    for sym in _held_options - held:
        clear_symbol(sym)
        _option_contract_last_update_ts.pop(sym, None)
    _held_options = held


#: a contract's subscription, as the Flow panel shows it: the daemon's option rule holds it on
#: LEVELONE_OPTIONS, or it does not (capture.Daemon.pick_options streams the contracts nearest
#: each ticker's price)
SUBSCRIBED, NOT_STREAMED = "SUBSCRIBED", "NOT STREAMED"


def get_option_contract_streaming_diagnostics(for_contract: str) -> dict[str, Any]:
    """Whether the daemon streams `for_contract` and is receiving it, distinct from the book's own
    content ages (options_live_payload): its subscription (SUBSCRIBED / NOT STREAMED, from the
    daemon's held contracts), and each feed by the one live rule (live_market_plane.feed_live_for)."""
    c = ticker_storage_key(for_contract)
    held = _read_producer_option_contracts()
    healthy = bool(_feed_running and _lmp.feed_live_for(c, "LEVELONE_OPTIONS"))
    return {
        "queried_contract": c,
        "subscription_state": SUBSCRIBED if c in held["LEVELONE_OPTIONS"] else NOT_STREAMED,
        "streaming_last_update_ts": _option_contract_last_update_ts.get(c),
        "feed_health": {"replay": "healthy" if healthy else "stale" if _feed_running else "not connected",
                        "l1": _service_feed(c, "LEVELONE_OPTIONS"),
                        "book": _service_feed(c, "OPTIONS_BOOK")},
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
    _feed_task = asyncio.get_event_loop().create_task(_feed_loop(), name="daemon-plane-feed")
    log.info("Live-plane feed started (source=capture daemon live push)")
    return True


STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    global _feed_running, _feed_task
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _option_contract_last_update_ts.clear()
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


