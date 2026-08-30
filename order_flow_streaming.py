"""
Live-plane feed for the single active UI ticker — READ-ONLY consumer of the canonical
capture daemon (tools/run_stream_capture.py), never a second Schwab session.

SINGLE-STREAM-AUTHORITY LAW (root-fixed here): this module used to own its own
`schwab.streaming.StreamClient`, logging into Schwab independently of the canonical
capture daemon — two authenticated sockets on one account, racing each other for the
same market truth. It now opens ZERO Schwab connections. The daemon is the one producer;
this module polls `stream_capture.db` (read-only) for the rows the daemon already wrote,
and replays them into the same in-process planes (`order_flow_live_state`,
`live_market_plane`) the old socket handlers fed — so every downstream consumer
(`/api/fast-quote`, streaming diagnostics, the active-ticker switch endpoint) needs no
changes and cannot tell the difference except by dropped/added latency.

Dynamic ticker switching survives the process boundary via a small signal file
(`stream_spine.write_active_ticker_signal` / `read_active_ticker_signal`): this module
WRITES the desired active ticker, the daemon POLLS it and adds/drops NASDAQ_BOOK /
NYSE_BOOK subscription for that one symbol. Equity L1 needs no signal — the daemon
already captures LEVELONE_EQUITIES for its whole configured roster; whichever symbol
this module is asked to serve, its rows are already there.

Public API is unchanged from the pre-repair module (same names, same call sites in
server.py): `start_order_flow_stream` / `stop_order_flow_stream` /
`set_streaming_active_ticker` / `get_plane_authority_for_ticker` /
`streaming_l1_cache_usable` / `get_streaming_diagnostics` / `is_order_flow_stream_running`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from instrument_identity import ticker_storage_key
from stream_spine import (
    STREAM_DB_DEFAULT,
    write_active_option_contract_signal,
    write_active_ticker_signal,
)

from order_flow_live_state import (
    clear_all_live_state,
    clear_symbol,
    forget_unsubscribed_symbols,
    get_content_for_symbol,
    push_book,
    push_level_one,
)
from order_flow_engine import compute_book_microstructure

import live_market_plane as _lmp

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.5   # daemon commits every batch_sec=0.25s; sub-second feed latency

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False
_active_ticker: Optional[str] = None
_streaming_last_update_ts: Optional[float] = None
_last_subscribe_completed_ts: Optional[float] = None
#: Per-symbol read cursor (ts_recv of the newest row already replayed) so a poll tick
#: reads only NEW rows — never replays history, never misses a row between polls.
_l1_cursor: dict[str, float] = {}
_book_cursor: dict[str, float] = {}

#: The one option CONTRACT (OSI symbol) whose LEVELONE_OPTIONS/OPTIONS_BOOK rows this feed
#: replays — a SEPARATE slot from _active_ticker (an equity ticker and an option contract
#: on that same underlying can be watched at once; they are different symbol identities in
#: every table and signal file).
_active_option_contract: Optional[str] = None
_option_l1_cursor: dict[str, float] = {}
_option_book_cursor: dict[str, float] = {}
#: Own staleness clock, separate from the equity ticker's — an option contract watched
#: alongside a ticker must be able to go stale (or come up fresh) independently.
_option_streaming_last_update_ts: Optional[float] = None
_option_last_subscribe_completed_ts: Optional[float] = None

_on_tick_callback: Optional[Callable[[str], None]] = None

STREAMING_STALE_MS = 25_000.0
GRACE_AFTER_SUBSCRIBE_SEC = 8.0


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


def _streaming_healthy() -> bool:
    if not (_feed_running and _active_ticker):
        return False
    now = time.time()
    if _streaming_last_update_ts is not None:
        return (now - _streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if _last_subscribe_completed_ts is not None and (now - _last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC:
        return True
    return False


def is_order_flow_stream_running() -> bool:
    return bool(_feed_running)


def get_plane_authority_for_ticker(ticker: str) -> str:
    """
    rest_only | streaming | rest_fallback_explicit | rest_mismatch
    """
    t = ticker_storage_key(ticker)
    if not _feed_running:
        return "rest_only"
    if not _active_ticker or _active_ticker.upper() != t:
        return "rest_mismatch"
    if _streaming_healthy():
        return "streaming"
    return "rest_fallback_explicit"


FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS = 5_000.0


def streaming_l1_cache_usable(ticker: str) -> bool:
    t = ticker_storage_key(ticker)
    if get_plane_authority_for_ticker(t) != "streaming":
        return False
    last = _streaming_last_update_ts
    if last is None:
        return False
    return (time.time() - last) * 1000.0 <= FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS


def get_streaming_diagnostics() -> dict[str, Any]:
    now = time.time()
    last = _streaming_last_update_ts
    stale_ms: Optional[float]
    if last is not None:
        stale_ms = max(0.0, (now - last) * 1000.0)
    elif _last_subscribe_completed_ts is not None and (now - _last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC:
        stale_ms = 0.0
    else:
        stale_ms = None

    return {
        "streaming_connected": bool(_feed_running),
        "streaming_ticker": _active_ticker,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": _streaming_healthy(),
    }


def _open_capture_db_readonly(db_path=None) -> Optional[sqlite3.Connection]:
    """Read-only by construction (uri mode=ro), never a write handle onto the daemon's
    database — this module carries observations, it does not produce them.

    `db_path` defaults to the MODULE ATTRIBUTE at call time, not a parameter default bound
    once at function-definition time — a default of `STREAM_DB_DEFAULT` directly would
    freeze whatever that name pointed to when this module was imported, so a caller (or a
    test) that reassigns the module attribute afterward would silently be ignored."""
    if db_path is None:
        db_path = STREAM_DB_DEFAULT
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None   # daemon has not created the DB yet (cold start) — retry next tick


def _replay_new_rows(con: sqlite3.Connection, ticker: str) -> None:
    """One poll tick: read rows newer than the cursor for `ticker`, replay them through
    the SAME plane-ingest functions the old direct-socket handlers called."""
    global _streaming_last_update_ts

    l1_since = _l1_cursor.get(ticker, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_quotes_raw "
        "WHERE symbol = ? AND ts_recv > ? AND native_json IS NOT NULL "
        "ORDER BY ts_recv", (ticker, l1_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_level_one(ticker, item)
        try:
            _lmp.record_from_level_one_equity(ticker, item)
        except Exception as e:
            log.debug("live_market_plane ingest: %s", e)
        _streaming_last_update_ts = time.time()
        if _on_tick_callback:
            try:
                _on_tick_callback(ticker)
            except Exception as e:
                log.debug("Tick callback: %s", e)
        _l1_cursor[ticker] = ts_recv

    book_since = _book_cursor.get(ticker, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_book_raw "
        "WHERE symbol = ? AND ts_recv > ? ORDER BY ts_recv", (ticker, book_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_book(ticker, item)
        _book_cursor[ticker] = ts_recv


def _replay_option_contract_rows(con: sqlite3.Connection, contract_symbol: str) -> None:
    """Same replay shape as _replay_new_rows, for the one option CONTRACT this feed is
    tracking. LEVELONE_OPTIONS rows read via push_level_one and OPTIONS_BOOK rows via
    push_book — order_flow_live_state's functions are symbol-generic (they read Schwab's
    native field names, not an equity-specific schema) and the captured field shapes
    (reports/of_capability_probe/options_20260820T1354Z/) carry every field either reads:
    BID_PRICE/ASK_PRICE/LAST_PRICE/LAST_SIZE/TOTAL_VOLUME/TRADE_TIME_MILLIS for L1;
    BIDS/ASKS/BOOK_TIME for book. No new plane, no new ingest function — the SAME producer
    order_flow_live_state already is, called with a different symbol."""
    global _option_streaming_last_update_ts
    l1_since = _option_l1_cursor.get(contract_symbol, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_options_quotes_raw "
        "WHERE symbol = ? AND ts_recv > ? ORDER BY ts_recv",
        (contract_symbol, l1_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_level_one(contract_symbol, item)
        _option_streaming_last_update_ts = time.time()
        _option_l1_cursor[contract_symbol] = ts_recv

    book_since = _option_book_cursor.get(contract_symbol, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_book_raw "
        "WHERE symbol = ? AND service = 'OPTIONS_BOOK' AND ts_recv > ? ORDER BY ts_recv",
        (contract_symbol, book_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_book(contract_symbol, item)
        _option_book_cursor[contract_symbol] = ts_recv


async def _feed_loop() -> None:
    """A sqlite3.Connection is THREAD-AFFINE (check_same_thread=True by default) — it may
    only be touched from the OS thread that created it. This loop opens ONE read-only
    connection and reuses it across every poll tick's two replay calls, but the default
    executor `asyncio.to_thread` schedules onto (min(32, cpu_count+4) worker threads with
    no affinity guarantee between calls — a real defect, not a test artifact: measured via
    a genuinely flaky integration test ("SQLite objects created in a thread can only be
    used in that same thread") that reproduced under real cross-call thread reuse, not a
    synthetic shortcut. Fixed at the root: every DB touch in this loop's lifetime — open
    AND both replay calls — runs on a DEDICATED single-worker executor, so `con` never
    crosses threads. The executor is scoped to this loop's own lifetime, not module-level,
    so a start/stop/restart cycle never risks a stale worker thread from a prior run."""
    global _feed_running
    con: Optional[sqlite3.Connection] = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-plane-feed-db")
    loop = asyncio.get_event_loop()
    try:
        while _feed_running:
            if con is None:
                con = await loop.run_in_executor(executor, _open_capture_db_readonly)
            tkr = _active_ticker
            contract = _active_option_contract
            if con is not None and (tkr or contract):
                try:
                    if tkr:
                        await loop.run_in_executor(executor, _replay_new_rows, con, tkr)
                    if contract:
                        await loop.run_in_executor(
                            executor, _replay_option_contract_rows, con, contract)
                except sqlite3.Error as e:
                    log.warning("daemon plane feed: db read failed, reopening: %s", e)
                    try:
                        await loop.run_in_executor(executor, con.close)
                    except sqlite3.Error:
                        pass
                    con = None
            await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        if con is not None:
            try:
                await loop.run_in_executor(executor, con.close)
            except sqlite3.Error:
                pass
        executor.shutdown(wait=False)
        _log_stream("FEED_LOOP_STOP_DONE")


def set_streaming_active_ticker(ticker: str) -> bool:
    """Request book depth + begin replaying L1 for this symbol. The daemon adds/drops
    its own NASDAQ_BOOK/NYSE_BOOK subscription for `ticker` on its own poll cadence
    (stream_active_ticker.json) — L1 replay here starts immediately since the daemon
    already captures LEVELONE_EQUITIES for its whole roster."""
    global _active_ticker, _last_subscribe_completed_ts, _streaming_last_update_ts
    t = ticker_storage_key(ticker)
    if not t:
        return False
    old = [_active_ticker] if _active_ticker else []
    if _active_ticker == t:
        return True
    _log_stream("STREAM_RESUBSCRIBE_START", old=old, new=[t])
    forget_unsubscribed_symbols(old, [t])
    write_active_ticker_signal(t)
    _active_ticker = t
    _last_subscribe_completed_ts = time.time()
    _streaming_last_update_ts = None
    log.info("Live-plane feed active ticker -> %s", t)
    _log_stream("STREAM_RESUBSCRIBE_DONE", ticker=t)
    return True


def set_active_option_contract(contract_symbol: str) -> bool:
    """Request LEVELONE_OPTIONS+OPTIONS_BOOK for this ONE option contract and begin
    replaying its rows. `contract_symbol` MUST already be a chain response's own "symbol"
    field (see stream_spine.ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT) — never constructed
    here. A separate slot from the equity active ticker: the daemon adds its own
    subscription on its own poll cadence (stream_active_option_contract.json)."""
    global _active_option_contract, _option_last_subscribe_completed_ts, _option_streaming_last_update_ts
    t = ticker_storage_key(contract_symbol)
    if not t:
        return False
    if _active_option_contract == t:
        return True
    old = _active_option_contract
    _log_stream("OPTION_CONTRACT_RESUBSCRIBE_START", old=old, new=t)
    if old:
        clear_symbol(old)
    write_active_option_contract_signal(t)
    _active_option_contract = t
    _option_last_subscribe_completed_ts = time.time()
    _option_streaming_last_update_ts = None
    log.info("Live-plane feed active option contract -> %s", t)
    _log_stream("OPTION_CONTRACT_RESUBSCRIBE_DONE", contract=t)
    return True


def get_option_contract_book_microstructure(contract_symbol: str) -> dict:
    """The order-flow SEMANTIC PRODUCT for one option contract's live book: reuses
    order_flow_engine.compute_book_microstructure — the SAME one producer the equity
    `/api/order-flow/microstructure` route reads — called with this contract's own
    replayed content, never a second book-imbalance computation. Fail-closed by that
    producer's own contract: no book snapshot yet -> status 'no_book', no fabricated
    metric. This function does not gate on _active_option_contract being set to
    `contract_symbol` — a caller may query content already replayed even if the daemon
    has since moved on, exactly as the equity route does not gate on the ticker being
    'the' active one."""
    t = ticker_storage_key(contract_symbol)
    content = get_content_for_symbol(t) if t else []
    return compute_book_microstructure({"content": content}, ticker=t)


def _option_streaming_healthy() -> bool:
    if not (_feed_running and _active_option_contract):
        return False
    now = time.time()
    if _option_streaming_last_update_ts is not None:
        return (now - _option_streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if (_option_last_subscribe_completed_ts is not None
            and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        return True
    return False


def get_option_contract_streaming_diagnostics() -> dict[str, Any]:
    """FRESHNESS/HEALTH for the option-contract feed — the SAME shape as
    get_streaming_diagnostics(), mirrored for the separate option-contract slot. Answers
    "is the daemon actually subscribed and receiving data for this contract", distinct
    from get_option_contract_book_microstructure's book-CONTENT-level ages/status (which
    answer "how stale is the replayed book itself"). Both distinctions matter: a feed can
    be streaming_healthy=True with status='no_book' (subscribed, market simply has not
    sent a book frame yet) as legitimately as it can be streaming_healthy=False with a
    perfectly fresh cached book (the feed died after its last good frame)."""
    now = time.time()
    last = _option_streaming_last_update_ts
    stale_ms: Optional[float]
    if last is not None:
        stale_ms = max(0.0, (now - last) * 1000.0)
    elif (_option_last_subscribe_completed_ts is not None
          and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        stale_ms = 0.0
    else:
        stale_ms = None

    return {
        "streaming_connected": bool(_feed_running),
        "option_contract": _active_option_contract,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": _option_streaming_healthy(),
    }


def start_order_flow_stream(
    client: Any,
    account_id: Any,
    initial_ticker: str,
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """`client`/`account_id` are accepted, not used: this feed opens no Schwab session
    of its own, so it has no account dependency — kept for call-site compatibility."""
    global _feed_task, _feed_running, _on_tick_callback
    it = (initial_ticker or "").upper().strip()
    if not it:
        log.warning("Live-plane feed: no initial ticker")
        return False
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _feed_running = True
    set_streaming_active_ticker(it)
    _feed_task = asyncio.get_event_loop().create_task(_feed_loop(), name="daemon-plane-feed")
    log.info("Live-plane feed started (initial ticker %s, source=canonical capture daemon)", it)
    return True


STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    global _feed_running, _feed_task, _streaming_last_update_ts, _active_ticker
    global _active_option_contract, _option_streaming_last_update_ts
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _streaming_last_update_ts = None
    _active_ticker = None
    _active_option_contract = None
    _option_streaming_last_update_ts = None
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


def get_stream_thread() -> None:
    """No dedicated OS thread exists — the feed is one asyncio task on the server's own
    event loop. Kept for import compatibility; nothing external reads a live value."""
    return None
