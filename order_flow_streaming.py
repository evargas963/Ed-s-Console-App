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
from typing import Any, Callable, Optional

from instrument_identity import ticker_storage_key
from stream_spine import STREAM_DB_DEFAULT, write_active_ticker_signal

from order_flow_live_state import (
    clear_all_live_state,
    forget_unsubscribed_symbols,
    push_book,
    push_level_one,
)

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


def _open_capture_db_readonly(db_path=STREAM_DB_DEFAULT) -> Optional[sqlite3.Connection]:
    """Read-only by construction (uri mode=ro), never a write handle onto the daemon's
    database — this module carries observations, it does not produce them."""
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


async def _feed_loop() -> None:
    global _feed_running
    con: Optional[sqlite3.Connection] = None
    try:
        while _feed_running:
            if con is None:
                con = await asyncio.to_thread(_open_capture_db_readonly)
            tkr = _active_ticker
            if con is not None and tkr:
                try:
                    await asyncio.to_thread(_replay_new_rows, con, tkr)
                except sqlite3.Error as e:
                    log.warning("daemon plane feed: db read failed, reopening: %s", e)
                    try:
                        con.close()
                    except sqlite3.Error:
                        pass
                    con = None
            await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass
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
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _streaming_last_update_ts = None
    _active_ticker = None
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
