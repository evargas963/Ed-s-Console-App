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

What to stream is decided HERE and sent to the daemon over the same socket, as one
complete list per Schwab service (current_wanted(); {"op": "wanted", ...}). Every change to
the active ticker, the equity demand or the option contracts bumps _wanted_version and the
feed loop sends the new list. The daemon's one-second status comes back on the same socket
(topic "daemon.heartbeat") and is the one source for "is the daemon / Schwab alive" and
"what does Schwab hold / refuse".

Public API: `start_order_flow_stream` / `stop_order_flow_stream`
/ `set_active_option_contract` / `get_option_contract_streaming_diagnostics`.
"""

from __future__ import annotations

import asyncio
import json
import queue
import logging
import threading
import time
from typing import Any, Callable, Optional

from instrument_identity import ticker_storage_key
import push_changes

from app.options.order_flow.state import (
    clear_all_live_state,
    clear_symbol,
    forget_unsubscribed_symbols,
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
#: Bumped whenever what this console wants streamed changes; the feed loop sends the new list.
_wanted_version = 0
#: (loop, event) of every task waiting for the wanted list to change; set from any thread.
_wanted_waiters: "set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]" = set()


def _wanted_changed() -> None:
    global _wanted_version
    _wanted_version += 1
    for loop, ev in list(_wanted_waiters):
        loop.call_soon_threadsafe(ev.set)


def _wait_for_wanted() -> "tuple[asyncio.AbstractEventLoop, asyncio.Event]":
    """An event set whenever the wanted list changes, for the calling task (on its loop)."""
    entry = (asyncio.get_running_loop(), asyncio.Event())
    _wanted_waiters.add(entry)
    return entry


def current_wanted() -> "dict":
    """Everything this console wants streamed, per Schwab service -- the ONE list sent to the
    daemon -- and `active`, the ticker on screen (push_changes.on_screen), whose chain the daemon
    fetches first. Equities (L1, 1-minute bars, news): the ticker on screen, the market context
    and the watchlist (the daemon adds the board itself). Books: the ticker on screen (NYSE_BOOK =
    the exchange book, NASDAQ_BOOK = market-maker quotes). Options: the primary contract (L1 +
    book) plus every contract the views ask for (L1)."""
    active = push_changes.on_screen()
    with _equity_lock:
        equities = equity_symbols(active, _watchlist)
    books = [active] if active else []
    primary = [_active_option_contract] if _active_option_contract else []
    return {"active": active,
            "LEVELONE_EQUITIES": equities, "CHART_EQUITY": equities, "NEWS_HEADLINE": equities,
            "NYSE_BOOK": books, "NASDAQ_BOOK": books,
            "LEVELONE_OPTIONS": sorted(set(primary) | set(_active_option_contracts)),
            "OPTIONS_BOOK": primary}


async def _send_wanted(ws) -> None:
    """Send the wanted list now, then again the moment it changes, for this connection's life."""
    entry = _wait_for_wanted()
    try:
        sent = None
        while True:
            entry[1].clear()
            if sent != _wanted_version:
                sent = _wanted_version
                await ws.send(json.dumps({"op": "wanted", "wanted": current_wanted()}))
            await entry[1].wait()
    finally:
        _wanted_waiters.discard(entry)

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False

#: The one option CONTRACT (OSI symbol) whose LEVELONE_OPTIONS/OPTIONS_BOOK rows this feed
#: replays — a SEPARATE slot from the ticker on screen (an equity ticker and an option contract
#: on that same underlying can be watched at once; they are different symbol identities in
#: every table and signal file).
_active_option_contract: Optional[str] = None
#: Own staleness clock, separate from the equity ticker's — an option contract watched
#: alongside a ticker must be able to go stale (or come up fresh) independently.
_option_streaming_last_update_ts: Optional[float] = None
#: PER-CONTRACT staleness clock (RC-UI-3 finding #4, 2026-09-12, REPRODUCED): the single
#: scalar above is updated by ANY contract's message -- primary OR any additional one (see
#: _ingest_pushed) -- so a fresh additional contract can mask a genuinely
#: stale primary, and vice versa: querying one contract's health answered with another
#: contract's heartbeat. Keyed by the SAME ticker_storage_key identity
#: set_active_option_contract/set_active_option_contracts already normalize to.
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
    global _option_streaming_last_update_ts
    if not isinstance(msg, dict):
        return None
    if topic.startswith("chain."):
        for done in assemble_chain_part(msg):
            if _on_chain_callback is not None:
                _on_chain_callback(*done)
        return None
    sym = msg.get("symbol")
    ts = msg.get("ts_recv")
    if not sym or not isinstance(ts, (int, float)):
        return None
    ts = float(ts)
    kind = topic.split(".", 1)[0]
    if kind == "bar1m":
        streamed_bars.put(msg)
        return None
    if kind == "quote":
        item = msg.get("native")
        if not isinstance(item, dict):
            return None
        push_level_one(sym, item, ts_recv=ts)
        push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "book":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_book(sym, content, msg["service"])
        if msg.get("service") == "OPTIONS_BOOK":
            _option_streaming_last_update_ts = ts
            _option_contract_last_update_ts[sym] = ts
        else:
            push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "optquote":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_level_one(sym, content, ts_recv=ts)
        push_option_top(sym, content)
        _option_streaming_last_update_ts = ts
        _option_contract_last_update_ts[sym] = ts
        if ("GAMMA" in content or "DELTA" in content or "OPEN_INTEREST" in content
                or "TOTAL_VOLUME" in content or "VOLUME" in content):
            _tick(sym)
    return None


def _rows_wanted() -> "list[str]":
    """The price rows this console holds: every equity the daemon streams (its heartbeat's held
    LEVELONE_EQUITIES -- what the console asked for and the board, as Schwab accepted them)."""
    return sorted(((_lmp.daemon_status() or {}).get("held") or {}).get("LEVELONE_EQUITIES") or [])


async def _rows_loop() -> None:
    """Hold the daemon's price rows (_rows_wanted): one browser client of the daemon's price
    push, resubscribed when what the daemon streams changes (checked on every frame; the daemon
    beats every second). Each row's arrival is the equity's tick."""
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
                        continue
                    msg = json.loads(frame)
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
        if _feed_running:
            await asyncio.sleep(PUSH_RECONNECT_SEC)


async def _feed_loop() -> None:
    """Consume the daemon's live push (LIVE_PUSH_URL) until the feed stops.

    Each frame is one Schwab stream message; it is applied the moment it arrives
    (_ingest_pushed) -- no poll interval, no database read. A dropped connection is retried
    every PUSH_RECONNECT_SEC; while it is down, the live values age out through their own
    freshness checks and the screen shows them stale. There is no second source."""
    global _feed_running
    from websockets.asyncio.client import connect

    async def _consume(ws) -> None:
        async for frame in ws:
            if not _feed_running:
                return
            try:
                env = json.loads(frame)
            except (TypeError, ValueError):
                continue
            if not isinstance(env, dict):
                continue
            if env.get("topic") == "daemon.heartbeat":
                _lmp.record_feed_heartbeat(env.get("msg"), time.time())
                continue
            _ingest_pushed(str(env.get("topic") or ""), env.get("msg"))
    rows = asyncio.create_task(_rows_loop(), name="daemon-price-rows")
    try:
        while _feed_running:
            try:
                async with connect(LIVE_PUSH_URL, max_size=None, open_timeout=5,
                                   ping_interval=20, ping_timeout=20) as ws:
                    _log_stream("PUSH_CONNECTED", url=LIVE_PUSH_URL)
                    sender = asyncio.create_task(_send_wanted(ws))
                    try:
                        await _consume(ws)
                    finally:
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
                log.info("live push unavailable (%s: %s); retrying in %.1fs",
                         type(e).__name__, e, PUSH_RECONNECT_SEC)
            _lmp.record_feed_down()        # no daemon, no live price -- visible at once
            if _feed_running:
                await asyncio.sleep(PUSH_RECONNECT_SEC)
    finally:
        rows.cancel()
        await asyncio.gather(rows, return_exceptions=True)
        _price_rows.clear()
        _lmp.record_feed_down()
        _log_stream("FEED_LOOP_STOP_DONE")



def get_active_option_contract() -> Optional[str]:
    """The DESIRED option contract symbol (this daemon's own signal), or None.

    This is REQUESTED/desired state, same caveat as `_active_option_contract`'s other
    readers (see the PR214 premerge gap 1A note below at the diagnostics endpoint): it can
    be ahead of what the vendor has actually confirmed for one tick. Callers using this to
    freshen a computation with streamed data already tolerate that (the data simply is not
    there yet if the vendor hasn't caught up), so no additional confirmation is required
    here — unlike stopping a process, freshening a projection has no destructive downside
    to occasionally reading one tick early."""
    return _active_option_contract


def clear_active_option_contract(*, reason: str) -> None:
    """Drop desired option-contract state and tell the daemon to unsubscribe.

    Used when the active underlying changes and no replacement vendor symbol
    exists — keeping the previous underlying's contract would stream the wrong
    identity. Empty signal reads as None (fail-closed: no subscription).
    """
    global _active_option_contract, _option_streaming_last_update_ts
    old = _active_option_contract
    # Same guard as set_active_option_contract: do not wipe a symbol's shared live store
    # while the ADDITIONAL set still desires it.
    if old and old not in _active_option_contracts:
        clear_symbol(old)
        _option_contract_last_update_ts.pop(old, None)
        _log_stream("OPTION_CONTRACT_CLEARED", old=old, reason=reason)
    _active_option_contract = None
    _option_streaming_last_update_ts = None
    _wanted_changed()


#: Which stocks/indexes a screen shows a live price for. The daemon streams the board itself;
#: everything else a screen shows is requested here (the no-fallback rule means an unstreamed
#: symbol reads UNAVAILABLE, so every shown symbol must be requested).
#: The market context every page's header shows beside the selected ticker (Trade Desk,
#: operator 2026-09-25). Standing demand: measured 2026-09-25, a page whose watchlist did not
#: happen to hold them showed SPX/NDX/VIX as "—" all session because nobody requested them.
MARKET_CONTEXT_SYMBOLS = ("$SPX", "$NDX", "$VIX")
#: The browser's watchlist, as its page last declared it.
_watchlist: "list[str]" = []
_equity_lock = threading.Lock()


def equity_symbols(active: "str | None", watchlist: "list[str]") -> "list[str]":
    """Every symbol the screens show, none left out: the active ticker, the market context
    (MARKET_CONTEXT_SYMBOLS), then the watchlist in its own order. Duplicates count once."""
    ordered: list[str] = []
    for sym in [active, *MARKET_CONTEXT_SYMBOLS, *watchlist]:
        t = ticker_storage_key(sym or "")
        if t and t not in ordered:
            ordered.append(t)
    return ordered


def declare_watchlist(symbols: "list[str]") -> None:
    """The browser's watchlist, whose live prices its page shows."""
    global _watchlist
    with _equity_lock:
        _watchlist = [t for t in (ticker_storage_key(s or "") for s in symbols or []) if t]
    _wanted_changed()


def _screen_changed(old: "str | None", new: "str | None") -> None:
    """The ticker on screen changed (push_changes): the old one's books are no longer streamed
    and their state is forgotten; the daemon gets the new wanted list."""
    forget_unsubscribed_symbols([old] if old else [], [new] if new else [])
    _wanted_changed()
    log.info("Live-plane feed: ticker on screen %s -> %s", old, new)


push_changes.on_screen_change(_screen_changed)


#: Monotonic generation for option-contract subscription commands: the operator's POST and
#: the console's own choice for the ticker on screen (server._follow_screen_contract).
#: Every command takes a number the moment it is admitted; only a command whose number is
#: still the highest may write `_active_option_contract`, so ordering never depends on HTTP
#: arrival or completion order. Guarded by a lock: the POST runs on a thread-pool executor.
_option_command_seq: int = 0
_option_command_lock = threading.Lock()


class StaleOptionCommandError(RuntimeError):
    """A superseded subscription command tried to write desired state after a newer one
    already did. Raised instead of silently returning, so the caller reports the command
    as superseded rather than as the successful current authority."""


def begin_option_contract_command() -> int:
    """Admit a subscription command and return its generation. Callers pass this back to
    set_active_option_contract so a delayed command cannot overwrite a newer one."""
    global _option_command_seq
    with _option_command_lock:
        _option_command_seq += 1
        return _option_command_seq


def set_active_option_contract(contract_symbol: str,
                               command_generation: Optional[int] = None) -> bool:
    """Request LEVELONE_OPTIONS+OPTIONS_BOOK for this ONE option contract and begin
    replaying its rows. `contract_symbol` MUST already be a chain response's own "symbol"
    field — never constructed here. A separate slot from the equity active ticker; it goes
    to the daemon in the wanted list the moment it changes.

    `command_generation` (from begin_option_contract_command) orders competing commands: a
    request for A admitted before a request for B, but reaching this writer after it, is
    superseded and refused (StaleOptionCommandError), so the daemon never streams a contract
    the screen already moved off. Without a generation the write is unordered."""
    global _active_option_contract, _option_streaming_last_update_ts
    t = ticker_storage_key(contract_symbol)
    if not t:
        return False
    # The staleness check and the two writes it guards happen under ONE lock: checking
    # outside it would leave the same race one layer down.
    with _option_command_lock:
        if command_generation is not None and command_generation < _option_command_seq:
            _log_stream("OPTION_CONTRACT_COMMAND_SUPERSEDED",
                        contract=t, generation=command_generation,
                        newest=_option_command_seq)
            raise StaleOptionCommandError(
                f"subscription command for {t} (generation {command_generation}) was "
                f"superseded by a newer command (generation {_option_command_seq}); "
                f"refusing to overwrite newer desired state")
        if _active_option_contract == t:
            return True
        old = _active_option_contract
        _log_stream("OPTION_CONTRACT_RESUBSCRIBE_START", old=old, new=t)
        # Independent-review finding (2026-09-12), mirror case: a symbol the primary slot
        # is switching AWAY from must not be cleared if it is STILL desired in the
        # ADDITIONAL set (_active_option_contracts) -- clear_symbol wipes the one shared
        # per-symbol live store regardless of which slot(s) name it, so clearing it here
        # would erase state the additional-contracts subscription still depends on.
        if old and old not in _active_option_contracts:
            clear_symbol(old)
        _active_option_contract = t
        _wanted_changed()
        _option_streaming_last_update_ts = None
        log.info("Live-plane feed active option contract -> %s", t)
        _log_stream("OPTION_CONTRACT_RESUBSCRIBE_DONE", contract=t)
        return True


#: The ADDITIONAL option contracts to stream beside the one primary/pinned
#: `_active_option_contract` (RC-UI-3, 2026-09-12 multi-contract coverage). Both go to the
#: daemon in current_wanted()'s LEVELONE_OPTIONS list.
_active_option_contracts: "list[str]" = []

#: Serializes the swap of the additional-contracts set (the plural signal write).
_option_contracts_command_lock = threading.Lock()

#: Per-view demand (2026-09-24). Every page that shows option contracts (the heatmap, Strike
#: Detail, in any number of tabs) declares ITS OWN set under its own client id; the stream
#: carries the union of every live declaration. MEASURED 2026-09-24:
#: this used to be one last-writer-wins slot, so two views (a 0DTE ladder and the
#: all-expiry grid) replaced each other's set on every render and the daemon swapped ~200
#: contracts on the shared Schwab socket every few seconds until the socket died.
#: A declaration is a lease: a live view re-declares every 30 s (DEMAND_REFRESH_MS in
#: static/js/ed-stream.js), and one not refreshed within OPTION_DEMAND_LEASE_SEC -- a closed
#: or crashed tab -- stops counting at the next declaration from any view.
OPTION_DEMAND_LEASE_SEC = 90.0
_option_demand_by_client: "dict[str, dict]" = {}
_option_demand_lock = threading.Lock()


def declare_option_contract_demand(client_id: str, contract_symbols: "list[str]", *,
                                   seq: int, now: "float | None" = None) -> dict:
    """Record one view's demand and stream the union of every live view's demand.

    `seq` orders ONE client's declarations (a late, older request from the same view never
    overwrites a newer one: StaleOptionCommandError). Different clients never supersede each
    other -- that was the defect. Returns this client's accepted demand (`requested`, the
    set the view can confirm against) and how many views are counted."""
    cid = str(client_id or "").strip()
    if not cid:
        raise ValueError("client_id is required: demand is declared per view")
    t = time.time() if now is None else float(now)
    requested = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: a view declaring no contracts is an empty declaration, which releases its demand
                        if ticker_storage_key(s)})
    with _option_demand_lock:
        prior = _option_demand_by_client.get(cid)
        if prior is not None and seq <= prior["seq"]:
            raise StaleOptionCommandError(
                f"demand {requested} from view {cid} (seq {seq}) was superseded by that "
                f"view's newer declaration (seq {prior['seq']})")
        _option_demand_by_client[cid] = {"symbols": requested, "seq": seq, "ts": t}
        for other in [k for k, v in _option_demand_by_client.items()
                      if t - v["ts"] > OPTION_DEMAND_LEASE_SEC]:
            del _option_demand_by_client[other]
        live = [v["symbols"] for v in _option_demand_by_client.values() if v["symbols"]]
        union = sorted(set().union(*live)) if live else []
        set_active_option_contracts(union)
    return {"requested": requested, "demand_views": len(live)}


def get_active_option_contracts() -> "list[str]":
    """The DESIRED additional option-contract symbols (this daemon's own plural signal),
    beside the one primary contract get_active_option_contract reports. Same
    requested/desired-state caveat as get_active_option_contract."""
    return list(_active_option_contracts)


def set_active_option_contracts(contract_symbols: "list[str]") -> bool:
    """Request LEVELONE_OPTIONS+OPTIONS_BOOK for these ADDITIONAL option contracts,
    beside the one primary contract set_active_option_contract manages. Symbols MUST
    already be chain-response "symbol" fields, same requirement as
    set_active_option_contract -- never constructed here.

    The ONE caller in production is declare_option_contract_demand, which passes the union
    of every live view's demand under its own lock; ordering is per view there (`seq`)."""
    global _active_option_contracts
    symbols = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: no symbols requested is an empty request, which clears the set
                      if ticker_storage_key(s)})
    with _option_contracts_command_lock:
        old = _active_option_contracts
        if set(old) == set(symbols):
            return True
        _log_stream("OPTION_CONTRACTS_RESUBSCRIBE_START", old=old, new=symbols)
        # Only a symbol actually being DROPPED needs its replay cursors forgotten -- one
        # still (or newly) requested keeps replaying without a spurious reset. Independent-
        # review finding (2026-09-12): a symbol dropped from the ADDITIONAL set that is
        # STILL the primary/pinned contract (_active_option_contract) must not be cleared
        # either -- clear_symbol wipes the one shared per-symbol live store (cursors,
        # streamed greeks, book state) regardless of which slot(s) named it, so clearing it
        # here would erase state the primary subscription is still actively depending on.
        for s in old:
            if s not in symbols and s != _active_option_contract:
                clear_symbol(s)
                _option_contract_last_update_ts.pop(s, None)
        _active_option_contracts = symbols
        _wanted_changed()
        log.info("Live-plane feed additional option contracts -> %s", symbols)
        _log_stream("OPTION_CONTRACTS_RESUBSCRIBE_DONE", contracts=symbols)
        return True


#: The two Schwab option services whose durable open coverage epochs constitute
#: PRODUCER-side subscription identity (as opposed to the server's desired state).
OPTION_PRODUCER_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def _read_producer_option_contracts() -> dict[str, list[str]]:
    """What Schwab holds per option service, from the daemon's status; empty when that status
    is missing or stale (unknown is never confirmation)."""
    held = (_lmp.daemon_status() or {}).get("held") or {}
    return {s: sorted(held.get(s) or []) for s in OPTION_PRODUCER_SERVICES}


def is_option_producer_daemon_available() -> bool:
    """True while the daemon's status is fresh."""
    return _lmp.daemon_status() is not None


def read_producer_rejected_option_contracts() -> "dict[str, str]":
    """{symbol: Schwab's reason} for option contracts Schwab refused, from the daemon's status."""
    refused = (_lmp.daemon_status() or {}).get("refused") or {}
    return dict(refused.get("LEVELONE_OPTIONS") or {})


def _pick_producer_contract(symbols: "list[str]", queried: Optional[str]) -> Optional[str]:
    """Reduce a service's list of currently-confirmed producer symbols to the single
    value the back-compat `producer_l1_contract`/`producer_book_contract` diagnostic
    fields report (RC-UI-3: those fields predate multi-contract coverage and every
    existing caller — the JS binding-status renderers, the order-flow subscription
    panel — still expects a single symbol or None). Prefers the QUERIED contract when it
    is among the confirmed symbols, since that is the subject the caller actually asked
    about; otherwise falls back to the first (the list is already sorted, so this is
    deterministic) so a caller not asking about a specific contract still sees SOME live
    evidence instead of a fabricated absence. Single-contract operation is unaffected:
    with at most one symbol ever confirmed, this always returns exactly that symbol or
    None, identical to the pre-RC-UI-3 scalar behavior."""
    if not symbols:
        return None
    if queried is not None and queried in symbols:
        return queried
    return symbols[0]


def get_option_contract_streaming_diagnostics(
    for_contract: Optional[str] = None,
) -> dict[str, Any]:
    """FRESHNESS/HEALTH for the option-contract feed. Answers
    "is the daemon actually subscribed and receiving data for this contract", distinct
    from options_live_payload's book-CONTENT-level ages/status (which
    answer "how stale is the replayed book itself"). Both distinctions matter: a feed can
    be streaming_healthy=True with status='no_book' (subscribed, market simply has not
    sent a book frame yet) as legitimately as it can be streaming_healthy=False with a
    perfectly fresh cached book (the feed died after its last good frame).

    CONTRACT BINDING (PR214 merge blocker 1A): `option_contract` is, and always was,
    the GLOBALLY ACTIVE contract — but this health was being attached verbatim to a
    payload computed for a DIFFERENT, caller-queried contract, so a response could
    read `contract: A` beside `streaming_healthy: true` that belonged entirely to B.
    Pass `for_contract` to bind the answer to the contract actually being asked
    about: the plane still truthfully reports which contract it is streaming, and
    `contract_match` states whether that is the one queried. On a mismatch the
    health FAILS CLOSED — there is no live evidence about A while the feed is bound
    to B, and absence of evidence must never render as healthy. `for_contract=None`
    (no caller-specified subject) keeps the historical whole-plane answer, with
    `contract_match` left None rather than fabricated."""
    now = time.time()
    queried = ticker_storage_key(for_contract) if for_contract else None
    # RC-UI-3 finding #4 (2026-09-12), REPRODUCED: `last`/`stale_ms` used to read ONLY the
    # single global `_option_streaming_last_update_ts`, which every contract's rows (primary
    # OR any additional one) all bump together -- so a query about a genuinely stale
    # contract could report a fresh `streaming_staleness_ms` borrowed entirely from a
    # DIFFERENT contract's own recent traffic. When a specific contract is queried, answer
    # from THAT contract's own per-contract clock instead.
    last = _option_contract_last_update_ts.get(queried) if queried else _option_streaming_last_update_ts
    stale_ms = None if last is None else max(0.0, (now - last) * 1000.0)
    # the one live rule (live_market_plane.feed_live_for): the daemon's heartbeat is current,
    # its Schwab socket is open, and it holds this contract
    subject = queried or _active_option_contract
    healthy = bool(_feed_running and subject and _lmp.feed_live_for(subject, "LEVELONE_OPTIONS"))

    # Contract binding: compare on the SAME canonical key set_active_option_contract
    # stores (ticker_storage_key), so a caller passing the raw chain "symbol" string
    # reconciles correctly rather than mismatching on whitespace/case alone.
    #
    # PR214 premerge gap 1A: `_active_option_contract` is only DESIRED/REQUESTED state
    # (the server wrote the signal file). It is NOT proof the daemon has completed the
    # LEVELONE_OPTIONS / OPTIONS_BOOK subscriptions -- between the request for B and the
    # daemon's next poll, the producer still physically holds A. Binding health to
    # requested state alone would green B during exactly that window. Producer truth is
    # read from the CANONICAL open coverage epochs in the same stream DB, and a full
    # contract match now requires requested AND both producer services to agree.
    producer = _read_producer_option_contracts()
    contract_match: Optional[bool] = None
    if queried:
        # Independent-review finding (2026-09-12): this used to recognize ONLY the
        # primary/pinned contract as a legitimate requested subject -- a queried contract
        # that was genuinely requested and confirmed as an ADDITIONAL contract (RC-UI-3)
        # was always rejected, because `requested_ok` never checked
        # `_active_option_contracts` at all. Fixed by recognizing either role.
        is_primary_request = (_active_option_contract == queried)
        is_extra_request = queried in _active_option_contracts
        requested_ok = is_primary_request or is_extra_request
        if is_primary_request:
            # The primary slot always requests BOTH services (the Flow view needs book
            # depth too), so a full match still requires both to confirm.
            producer_ok = (queried in producer["LEVELONE_OPTIONS"]
                           and queried in producer["OPTIONS_BOOK"])
        else:
            # An ADDITIONAL-only contract requests LEVELONE_OPTIONS alone (survivor-
            # challenge finding: the heatmap/GEX/volume consumers it serves never read
            # book depth -- see EXTRA_OPTION_CONTRACT_SVC_KEY in capture.py). Requiring
            # OPTIONS_BOOK confirmation here would fail this contract closed FOREVER,
            # since book is never subscribed for it in the first place.
            producer_ok = queried in producer["LEVELONE_OPTIONS"]
        contract_match = bool(requested_ok and producer_ok)
        if not contract_match:
            # Either the plane is bound elsewhere, or the producer has not yet confirmed
            # this contract on its required service(s). No live evidence about the queried
            # contract exists in either case -- fail closed rather than lending another
            # contract's health, or a not-yet-established subscription's, to this one.
            healthy = False
    pl1 = _pick_producer_contract(producer["LEVELONE_OPTIONS"], queried)
    pbk = _pick_producer_contract(producer["OPTIONS_BOOK"], queried)
    # the queried contract's subscription, as the page shows it: SUBSCRIBED (the producer holds it),
    # MOVED (both services hold one other contract), else PENDING; None with no contract queried
    subscription_state = (None if not queried else "SUBSCRIBED" if contract_match
                          else "MOVED" if pl1 and pl1 == pbk and pl1 != queried else "PENDING")
    return {
        "streaming_connected": bool(_feed_running),
        # Back-compatible name; it has always been the SERVER-REQUESTED contract.
        "option_contract": _active_option_contract,
        "server_requested_contract": _active_option_contract,
        "producer_l1_contract": pl1,
        "producer_book_contract": pbk,
        "queried_contract": queried,
        "contract_match": contract_match,
        "subscription_state": subscription_state,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": healthy,
        "feed_health": {"replay": "not connected" if not _feed_running else "healthy" if healthy else "stale",
                        "l1": _service_feed(subject, "LEVELONE_OPTIONS"),
                        "book": _service_feed(subject, "OPTIONS_BOOK")},
    }


def start_order_flow_stream(on_tick_callback: Optional[Callable[[str], None]] = None,
                            on_chain_callback: Optional[Callable[..., None]] = None) -> bool:
    """Start the feed from the capture daemon (on the event loop). It follows the ticker on
    screen (push_changes) from the first page that opens."""
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
    global _active_option_contract, _option_streaming_last_update_ts
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _active_option_contract = None
    _option_streaming_last_update_ts = None
    _option_contract_last_update_ts.clear()
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


