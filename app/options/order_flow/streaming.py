"""
Live-plane feed for the single active UI ticker: a read-only consumer of the capture daemon
(app.market_data.schwab.streaming.capture). It opens no Schwab connection.

The daemon forwards each Schwab book, option-quote, news and bar message to this module over a
local WebSocket (app.market_data.schwab.streaming.live_push, ws://127.0.0.1:8799) the moment it
arrives, and this module applies it to the in-process planes (`app.options.order_flow.state`,
`live_market_plane`). Nothing here reads `stream_capture.db`. If the push connection drops, the
live values go stale and the screen says so.

What to stream is decided HERE and sent to the daemon over the same socket, as one
complete list per Schwab service (current_wanted(); {"op": "wanted", ...}). Every change to
the active ticker, the equity demand or the option contracts bumps _wanted_version and the
feed loop sends the new list. The daemon's one-second status comes back on the same socket
(topic "daemon.heartbeat") and is the one source for "is the daemon / Schwab alive" and
"what does Schwab hold / refuse".

Public API: `start_order_flow_stream` / `stop_order_flow_stream` / `set_streaming_active_ticker`
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
from stream_spine import (
    EQUITY_SYMBOLS_MAX_HELD,
    OPTION_CONTRACTS_MAX_HELD,
    rank_option_contracts,
)

from app.options.order_flow.state import (
    clear_all_live_state,
    clear_symbol,
    forget_unsubscribed_symbols,
    push_book,
    push_level_one,
    push_option_top,
)

import live_market_plane as _lmp
from time_et import ct_label

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


#: The daemon's verdict on each symbol's 1-minute bars (barstate.SYM, live_ui.publish_states):
#: whether today's minutes are covered through now. Carried as pushed; dropped when the push is
#: gone. The currency of every value the console builds from today's bars.
_bar_states: "dict[str, dict]" = {}


def bar_state(ticker: str) -> "dict | None":
    return _bar_states.get(ticker_storage_key(ticker) or "")


#: Schwab's daily candles of the days before today per symbol, as the daemon pushed them
#: (bardays.SYM: candles, or none with its problem). Dropped when the push is gone.
_bar_days: "dict[str, dict]" = {}


def bar_days(ticker: str) -> "dict | None":
    return _bar_days.get(ticker_storage_key(ticker) or "")
#: Wait between reconnect attempts when the daemon's push server is down. While it is down
#: no live value is refreshed -- the freshness checks turn them stale; nothing substitutes.
PUSH_RECONNECT_SEC = 1.0
#: How often the feed loop checks whether the wanted list changed (it sends only on change).
WANTED_SEND_SEC = 0.25
#: Bumped whenever what this console wants streamed changes; the feed loop sends the new list.
_wanted_version = 0


def _wanted_changed() -> None:
    global _wanted_version
    _wanted_version += 1


def current_wanted() -> "dict[str, list[str]]":
    """Everything this console wants streamed, per Schwab service -- the ONE list sent to the
    daemon. Equities (L1, 1-minute bars, news): the ranked equity demand. Books: the active
    ticker (NYSE_BOOK = the exchange book, NASDAQ_BOOK = market-maker quotes). Options: the
    primary contract (L1 + book) plus the views' ranked contracts (L1)."""
    with _equity_lock:
        equities, _ = rank_equity_symbols(_active_ticker, _equity_demand)
    books = [_active_ticker] if _active_ticker else []
    primary = [_active_option_contract] if _active_option_contract else []
    return {"LEVELONE_EQUITIES": equities, "CHART_EQUITY": equities, "NEWS_HEADLINE": equities,
            "NYSE_BOOK": books, "NASDAQ_BOOK": books,
            "LEVELONE_OPTIONS": sorted(set(primary) | set(_active_option_contracts)),
            "OPTIONS_BOOK": primary}


async def _send_wanted(ws) -> None:
    """Send the wanted list now, then again whenever it changes, for this connection's life."""
    sent = None
    while True:
        if sent != _wanted_version:
            sent = _wanted_version
            await ws.send(json.dumps({"op": "wanted", "wanted": current_wanted()}))
        await asyncio.sleep(WANTED_SEND_SEC)

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False
_active_ticker: Optional[str] = None

#: The one option CONTRACT (OSI symbol) whose LEVELONE_OPTIONS/OPTIONS_BOOK rows this feed
#: replays — a SEPARATE slot from _active_ticker (an equity ticker and an option contract
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
    live rule (live_market_plane.feed_live_for), and how long ago the daemon last received
    anything on that service (its own report)."""
    health = ((_lmp.daemon_status(now) or {}).get("health") or {}).get(service) or {}
    return {"state": "LIVE" if _lmp.feed_live_for(symbol, service, now) else "NOT LIVE",
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

      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book; OPTIONS_BOOK -> the option
                   contract's book
      optquote.SYM LEVELONE_OPTIONS -> order-flow state for the contract

    An equity's quote is the daemon's price row (_rows_loop); the console receives no other copy.
    Every option quote carrying GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLUME is passed to the
    tick callback (an equity's tick is its price row's arrival). A message missing its symbol, its
    receive time or its Schwab payload is dropped whole: nothing is applied with a guessed
    part."""
    global _option_streaming_last_update_ts
    if not isinstance(msg, dict):
        return None
    if topic.startswith("barstate.") and msg.get("symbol"):
        _bar_states[ticker_storage_key(msg["symbol"])] = msg      # the daemon's verdict, carried
        return None
    if topic.startswith("bardays.") and msg.get("symbol"):
        _bar_days[ticker_storage_key(msg["symbol"])] = msg        # Schwab's daily candles, carried
        return None
    if topic.startswith("barheld."):       # the daemon's held day, sent on connect: backfill only
        for bar in msg.get("bars") or ():
            streamed_bars.put({**bar, "backfill": True})
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
    if kind == "barhist":                  # one price-history reply: each minute to the bar writer
        for bar in msg.get("bars") or ():
            streamed_bars.put(bar)
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


async def _rows_loop() -> None:
    """Hold the daemon's price rows for the equities this console wants streamed: one browser
    client of the daemon's price push. Each row's arrival is the equity's tick."""
    from websockets.asyncio.client import connect

    while _feed_running:
        try:
            async with connect(LIVE_UI_URL, max_size=None, open_timeout=5) as ws:
                sent = None
                while _feed_running:
                    want = current_wanted()["LEVELONE_EQUITIES"]
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
                            # the row carries the top of book the order-flow panels show
                            push_changes.changed(row["ticker"], push_changes.FLOW)
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
    freshness checks and the screen shows them stale. There is no second source. On reconnect
    the daemon sends current state only (books, option quote fields, bar verdicts, daily candles)
    and its held minutes of the day (barheld), which backfill the store insert-only: the 1-minute
    bars Schwab sent while it was down are not received as bar events, and that span is named
    (PUSH_GAP)."""
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
    down_since = None          # when the push dropped, until it is back
    try:
        while _feed_running:
            try:
                async with connect(LIVE_PUSH_URL, max_size=None, open_timeout=5,
                                   ping_interval=20, ping_timeout=20) as ws:
                    _log_stream("PUSH_CONNECTED", url=LIVE_PUSH_URL)
                    if down_since is not None:
                        _log_stream("PUSH_GAP", note=(
                            f"no 1-minute bars received from {ct_label(down_since)} to "
                            f"{ct_label(time.time())} as bar events; the daemon's held minutes of "
                            f"the day backfill the store"))
                        down_since = None
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
            _bar_states.clear()            # nor its verdict on any symbol's bars
            _bar_days.clear()
            down_since = time.time() if down_since is None else down_since
            if _feed_running:
                await asyncio.sleep(PUSH_RECONNECT_SEC)
    finally:
        rows.cancel()
        await asyncio.gather(rows, return_exceptions=True)
        _price_rows.clear()
        _bar_states.clear()
        _bar_days.clear()
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


#: Which stocks/indexes a screen shows a live price for, by source. The daemon streams the
#: board it read at its start (capture.standing_roster) and never unsubscribes an equity on a
#: connection; everything else is requested here (the no-fallback rule
#: means an unstreamed symbol reads UNAVAILABLE, so every shown symbol must be requested).
#: The market context every page's header shows beside the selected ticker (Trade Desk,
#: operator 2026-09-25). Standing demand: measured 2026-09-25, a page whose watchlist did not
#: happen to hold them showed SPX/NDX/VIX as "—" all session because nobody requested them.
MARKET_CONTEXT_SYMBOLS = ("$SPX", "$NDX", "$VIX")
_EQUITY_DEMAND_ORDER = ("context", "watchlist", "board")
_equity_demand: "dict[str, list[str]]" = {k: [] for k in _EQUITY_DEMAND_ORDER}
_equity_demand["context"] = list(MARKET_CONTEXT_SYMBOLS)
_equity_not_admitted: "dict[str, str]" = {}
_equity_lock = threading.Lock()


def rank_equity_symbols(active: "str | None", demand: "dict[str, list[str]]",
                        budget: int = EQUITY_SYMBOLS_MAX_HELD,
                        ) -> "tuple[list[str], dict[str, str]]":
    """(admitted, {not_admitted: reason}). Order of importance: the active ticker, then the
    market context (MARKET_CONTEXT_SYMBOLS), then the watchlist in its own order, then the
    gamma board. Duplicates count once, at their
    most important place; everything past the budget is named, never silently cut."""
    ordered: list[str] = []
    for sym in [active, *[s for k in _EQUITY_DEMAND_ORDER for s in demand.get(k, [])]]:
        t = ticker_storage_key(sym or "")
        if t and t not in ordered:
            ordered.append(t)
    admitted = ordered[:max(budget, 0)]
    not_admitted = {t: f"not streamed: outside the live equity budget ({budget})"
                    for t in ordered[max(budget, 0):]}
    return admitted, not_admitted


def _publish_equity_symbols() -> None:
    """Re-rank the equity demand; the daemon gets it with the next wanted list."""
    global _equity_not_admitted
    with _equity_lock:
        _, _equity_not_admitted = rank_equity_symbols(_active_ticker, _equity_demand)
    _wanted_changed()


def declare_equity_symbols(kind: str, symbols: "list[str]") -> "dict[str, str]":
    """A screen's set of symbols whose live price it shows (`kind` = watchlist | board).
    Returns the symbols left unstreamed, with the reason."""
    if kind not in _equity_demand:
        raise ValueError(f"unknown equity demand kind {kind!r}")
    with _equity_lock:
        _equity_demand[kind] = [t for t in (ticker_storage_key(s or "") for s in symbols or []) if t]
    _publish_equity_symbols()
    return get_equity_symbols_not_admitted()


def get_equity_symbols_not_admitted() -> "dict[str, str]":
    with _equity_lock:
        return dict(_equity_not_admitted)


def set_streaming_active_ticker(ticker: str) -> bool:
    """Make `ticker` the active symbol: the daemon adds its NASDAQ_BOOK/NYSE_BOOK depth
    (stream_active_ticker.json) and, when it is outside the daemon's roster, its
    LEVELONE_EQUITIES stream (stream_equity_symbols.json, ranked first)."""
    global _active_ticker
    t = ticker_storage_key(ticker)
    if not t:
        return False
    old = [_active_ticker] if _active_ticker else []
    if _active_ticker == t:
        return True
    _log_stream("STREAM_RESUBSCRIBE_START", old=old, new=[t])
    forget_unsubscribed_symbols(old, [t])
    _active_ticker = t
    _publish_equity_symbols()
    log.info("Live-plane feed active ticker -> %s", t)
    _log_stream("STREAM_RESUBSCRIBE_DONE", ticker=t)
    return True


#: Monotonic generation for option-contract subscription COMMANDS (PR214 premerge
#: gap 2). Every command takes a number the moment it is admitted; only a command whose
#: number is still the highest may WRITE desired state. This is the one authority that
#: orders the two things a command mutates together -- the signal file the daemon reads
#: and `_active_option_contract` -- so ordering never depends on HTTP arrival or
#: completion order, and never on the browser choosing to ignore a stale response.
#: Guarded by a lock because the endpoint runs its body on a thread-pool executor, so
#: two commands really can interleave inside this module.
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
    field (see stream_spine.ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT) — never constructed
    here. A separate slot from the equity active ticker: the daemon adds its own
    subscription on its own poll cadence (stream_active_option_contract.json).

    PR214 premerge gap 2: `command_generation` (from begin_option_contract_command)
    mechanically orders competing commands. A request for A that was admitted BEFORE a
    request for B, but reaches this writer AFTER it, is superseded and refused --
    otherwise the delayed A would write the signal file and `_active_option_contract`
    back to A, leaving the daemon subscribed to the contract the operator already moved
    off. The browser-side token cannot prevent that: it only stops a stale RESPONSE from
    repainting, never a stale WRITE from landing. Omitting the generation preserves the
    historical single-caller behavior for internal/test callers."""
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
#: {symbol: reason} for every contract the last plural request asked for that was not
#: admitted to the stream (outside the budget, or no spot to rank it by).
_option_contracts_not_admitted: "dict[str, str]" = {}


def _contract_ranking_inputs(symbols: "list[str]") -> "dict[str, dict]":
    """{symbol: {expirationDate, strikePrice, spot}} for every requested symbol found in a
    Schwab chain the console currently holds (the terrain cache's raw REST contracts).
    expirationDate and strikePrice are that contract's own fields; spot is resolve_spot of
    the ticker whose chain holds the contract (streamed LAST_PRICE, or None). A symbol in
    no held chain is absent, and rank_option_contracts reports it as not admitted."""
    import server as _srv

    wanted = set(symbols)
    out: "dict[str, dict]" = {}
    with _srv._terrain_cache_lock:
        chains = [(tk, list(payload.get("_chain") or []))
                  for tk, payload in _srv._terrain_cache.items()]
    spot_by_ticker: "dict[str, float | None]" = {}
    for tk, contracts in chains:
        for ct in contracts:
            sym = ticker_storage_key(ct.get("symbol")) if isinstance(ct, dict) else None
            if not sym or sym not in wanted or sym in out:
                continue
            if tk not in spot_by_ticker:
                spot_by_ticker[tk] = _srv.resolve_spot(tk)[0]
            out[sym] = {"expirationDate": ct.get("expirationDate"),
                        "strikePrice": ct.get("strikePrice"),
                        "spot": spot_by_ticker[tk]}
    return out


def get_option_contracts_over_budget() -> "list[str]":
    """Contracts the last plural request asked for that were not admitted to the stream."""
    return sorted(_option_contracts_not_admitted)


def get_option_contracts_not_admitted() -> "dict[str, str]":
    """{symbol: reason} for the last plural request's contracts that were not admitted."""
    return dict(_option_contracts_not_admitted)


def get_option_contracts_budget_state() -> dict:
    """What the last plural request was admitted to, against the shared-socket budget."""
    return {"admitted_count": len(_active_option_contracts),
            "over_budget_count": len(_option_contracts_not_admitted),
            "budget": OPTION_CONTRACTS_MAX_HELD}

#: Serializes the swap of the additional-contracts set (the plural signal write).
_option_contracts_command_lock = threading.Lock()
#: The last request that was ranked in full, and the set that rank admitted (see
#: set_active_option_contracts: identical demand keeps the held set, no re-rank).
_option_contracts_last_request: "list[str] | None" = None
_option_contracts_last_admitted: "list[str]" = []
_OVER_BUDGET_REASON_PREFIX = "not admitted: outside the live-stream budget"

#: Per-view demand (2026-09-24). Every page that shows option contracts (the heatmap, Strike
#: Detail, in any number of tabs) declares ITS OWN set under its own client id; the stream
#: carries the union of every live declaration, ranked to the budget. MEASURED 2026-09-24:
#: this used to be one last-writer-wins slot, so two views (a 0DTE ladder and the
#: all-expiry grid) replaced each other's set on every render and the daemon swapped ~200
#: contracts on the shared Schwab socket every few seconds until the socket died.
#: A view's demand lives as long as the view's push connection (/api/changes,
#: push_changes.view_open): declared only while it is open, released when its last one closes
#: (release_option_contract_demand). The page declares again each time the connection opens.
_option_demand_by_client: "dict[str, dict]" = {}
_option_demand_lock = threading.Lock()


class ViewNotConnectedError(RuntimeError):
    """A view with no open push connection declared demand: nothing would ever release it."""


def _stream_demand_union() -> int:
    """Stream the union of every view's demand; how many views hold any. Caller holds
    _option_demand_lock."""
    live = [v["symbols"] for v in _option_demand_by_client.values() if v["symbols"]]
    set_active_option_contracts(sorted(set().union(*live)) if live else [])
    return len(live)


def declare_option_contract_demand(client_id: str, contract_symbols: "list[str]", *,
                                   seq: int) -> dict:
    """Record one view's demand and stream the union of every view's demand.

    `seq` orders ONE client's declarations (a late, older request from the same view never
    overwrites a newer one: StaleOptionCommandError). Different clients never supersede each
    other -- that was the defect. Returns this client's accepted demand (`requested`, the
    set the view can confirm against) and how many views are counted."""
    cid = str(client_id or "").strip()
    if not cid:
        raise ValueError("client_id is required: demand is declared per view")
    requested = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: a view declaring no contracts is an empty declaration, which releases its demand
                        if ticker_storage_key(s)})
    with _option_demand_lock:
        if not push_changes.view_open(cid):
            raise ViewNotConnectedError(f"view {cid} has no open push connection")
        prior = _option_demand_by_client.get(cid)
        if prior is not None and seq <= prior["seq"]:
            raise StaleOptionCommandError(
                f"demand {requested} from view {cid} (seq {seq}) was superseded by that "
                f"view's newer declaration (seq {prior['seq']})")
        _option_demand_by_client[cid] = {"symbols": requested, "seq": seq}
        views = _stream_demand_union()
    return {"requested": requested, "demand_views": views}


def release_option_contract_demand(client_id: str) -> None:
    """A push connection of the view closed: with none left open, its demand ends."""
    with _option_demand_lock:
        if push_changes.view_open(client_id) or client_id not in _option_demand_by_client:
            return
        del _option_demand_by_client[client_id]
        _stream_demand_union()


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
    global _active_option_contracts, _option_contracts_not_admitted
    global _option_contracts_last_request, _option_contracts_last_admitted
    requested = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: no symbols requested is an empty request, which clears the set
                        if ticker_storage_key(s)})
    # The same demand as last time keeps the set already held. MEASURED 2026-09-24: every
    # re-post of an unchanged heatmap re-ranked against the newest streamed spot, the
    # 200-contract cutoff slid by a strike, and the daemon unsubscribed/resubscribed on the
    # shared Schwab socket for nothing (3,676 SPY option subscriptions in 5 minutes, median
    # life 5 s; the socket died 8 times that session). A new rank happens only when the
    # demand changes, or when the last rank could not place every contract (an input such as
    # spot was missing then and may be present now).
    if (requested == _option_contracts_last_request
            and list(_active_option_contracts) == _option_contracts_last_admitted):
        return True
    # The shared Schwab socket's budget (stream_spine.OPTION_CONTRACTS_MAX_HELD, measured):
    # publish only what the daemon may hold, ranked on canonical Schwab fields (the chain
    # contract's expirationDate, then |strikePrice - streamed LAST_PRICE|), and remember
    # what was left out and why. Any input missing: not admitted, never a guess.
    admitted, not_admitted = rank_option_contracts(requested, _contract_ranking_inputs(requested))
    symbols = sorted(admitted)
    _option_contracts_not_admitted = not_admitted
    with _option_contracts_command_lock:
        # Remember this rank as final only when every contract was placed (admitted, or
        # left out by the budget alone); a contract missing an input is re-ranked next time.
        placed = all(r.startswith(_OVER_BUDGET_REASON_PREFIX) for r in not_admitted.values())
        _option_contracts_last_request = requested if placed else None
        _option_contracts_last_admitted = symbols
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


def read_producer_admitted_option_contracts(now: float) -> "dict[str, list[str]]":
    """What Schwab holds per option service, from the daemon's status at `now`; empty when that
    status is missing or stale (unknown is never confirmation)."""
    held = (_lmp.daemon_status(now) or {}).get("held") or {}
    return {s: sorted(held.get(s) or []) for s in OPTION_PRODUCER_SERVICES}


def is_option_producer_daemon_available(now: float) -> bool:
    """True while the daemon's status is fresh at `now`."""
    return _lmp.daemon_status(now) is not None


def read_producer_rejected_option_contracts(now: float) -> "dict[str, str]":
    """{symbol: Schwab's reason} for option contracts Schwab refused, from the daemon's status."""
    refused = (_lmp.daemon_status(now) or {}).get("refused") or {}
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
    for_contract: Optional[str], now: float,
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
    `contract_match` left None rather than fabricated. `now`: epoch seconds."""
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
    healthy = bool(_feed_running and subject and _lmp.feed_live_for(subject, "LEVELONE_OPTIONS", now))

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
    producer = read_producer_admitted_option_contracts(now)
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
                        "l1": _service_feed(subject, "LEVELONE_OPTIONS", now),
                        "book": _service_feed(subject, "OPTIONS_BOOK", now)},
    }


def start_order_flow_stream(
    client: Any,
    account_id: Any,
    initial_ticker: "str | None",
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """`client`/`account_id` are accepted, not used: this feed opens no Schwab session
    of its own, so it has no account dependency — kept for call-site compatibility.
    `initial_ticker` may be None: the feed then runs with no active ticker until the browser
    chooses one (no built-in ticker -- universality, operator 2026-09-23)."""
    global _feed_task, _feed_running, _on_tick_callback
    it = (initial_ticker or "").upper().strip()
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _feed_running = True
    if it:
        set_streaming_active_ticker(it)
    _feed_task = asyncio.get_event_loop().create_task(_feed_loop(), name="daemon-plane-feed")
    log.info("Live-plane feed started (initial ticker %s, source=capture daemon live push)",
             it or "none -- awaiting the browser's choice")
    return True


STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    global _feed_running, _feed_task, _active_ticker
    global _active_option_contract, _option_streaming_last_update_ts
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _active_ticker = None
    _active_option_contract = None
    _option_streaming_last_update_ts = None
    _option_contract_last_update_ts.clear()
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


