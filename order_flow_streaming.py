"""
Schwab streaming — dynamic LEVEL_ONE_EQUITY (+ book) for the single active UI ticker.

Lifecycle: a dedicated thread owns a dedicated asyncio event loop and the sole
StreamClient / websocket. **Never** use asyncio.wait_for() to cancel
StreamClient.handle_message() on a timer — that cancels the underlying
websocket recv(), leaving websockets protocol tasks pending and causing
"Task was destroyed but it is pending" at loop close.

Shutdown: asyncio.Event on the stream loop + thread join from app lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Optional
from instrument_identity import ticker_storage_key

from order_flow_live_state import (
    clear_all_live_state,
    forget_unsubscribed_symbols,
    push_book,
    push_level_one,
)

import live_market_plane as _lmp

log = logging.getLogger(__name__)

# ── Runtime (stream thread only for client; diagnostics read from any thread) ──
_stream_thread: Optional[threading.Thread] = None
_stream_loop: Optional[asyncio.AbstractEventLoop] = None
_stream_running = False
_stream_client: Any = None
_streaming_logged_in = False

_on_tick_callback: Optional[Callable[[str], None]] = None

# Created inside the stream loop (asyncio.Event / asyncio.Lock bound to that loop)
_stream_shutdown_event: Optional[asyncio.Event] = None
_stream_resubscribe_lock: Optional[asyncio.Lock] = None

# Single-symbol subscription (active UI ticker)
_subscribed_equity_syms: list[str] = []
_active_streaming_ticker: Optional[str] = None
_streaming_last_update_ts: Optional[float] = None
_last_subscribe_completed_ts: Optional[float] = None

_pending_post_login_ticker: Optional[str] = None
_pending_lock = threading.Lock()

STREAMING_STALE_MS = 25_000.0
GRACE_AFTER_SUBSCRIBE_SEC = 8.0

# Join timeout when stopping (HTTP thread must not hang forever)
STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0

# Throttle noisy L1 INFO logs (full tick stream can be 100s/sec)
_STREAM_DIAG_L1_INFO_INTERVAL_SEC = 5.0
_diag_l1_last_info_log_ts: float = 0.0

# ── OPTIONS collection MOVED OUT (2026-08-26) ────────────────────────────────────────────────
# Raw options collection used to live here, riding the server's UI Schwab stream. That made this
# UI module a SECOND streaming Collect authority beside the capture daemon
# (tools/run_stream_capture.py), which the repo already defines as the single stream owner. The
# whole subsystem now lives in options_stream_collect.py and is driven by the daemon on its one
# stream. This module is once again purely OBSERVATIONAL: it serves the UI live quotes and
# persists nothing. See options_stream_collect for the collection lifecycle.


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


def _streaming_healthy() -> bool:
    if not (_stream_running and _streaming_logged_in and _active_streaming_ticker):
        return False
    now = time.time()
    if _streaming_last_update_ts is not None:
        return (now - _streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if _last_subscribe_completed_ts is not None and (now - _last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC:
        return True
    return False


def is_order_flow_stream_running() -> bool:
    return bool(_stream_running and _streaming_logged_in)


def get_plane_authority_for_ticker(ticker: str) -> str:
    """
    rest_only | streaming | rest_fallback_explicit | rest_mismatch
    """
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical stream key (idempotent on Schwab stream symbols)
    if not (_stream_running and _streaming_logged_in):
        return "rest_only"
    if not _active_streaming_ticker or _active_streaming_ticker.upper() != t:
        return "rest_mismatch"
    if _streaming_healthy():
        return "streaming"
    return "rest_fallback_explicit"


# Max age of last L1 tick before /api/fast-quote must not serve frozen plane cache.
FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS = 5_000.0


def streaming_l1_cache_usable(ticker: str) -> bool:
    """
    True only when plane authority is streaming AND the active ticker received a
    recent L1 tick. Prevents serving a stale cached row after the websocket died
    but before STREAMING_STALE_MS (25s) expires.
    """
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical stream key (idempotent on Schwab stream symbols)
    if get_plane_authority_for_ticker(t) != "streaming":
        return False
    last = _streaming_last_update_ts
    if last is None:
        return False
    return (time.time() - last) * 1000.0 <= FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS


def _is_stream_disconnect_error(exc: BaseException) -> bool:
    """Websocket clean/error close from schwab-py / websockets — exit recv loop."""
    name = type(exc).__name__
    return name in ("ConnectionClosedOK", "ConnectionClosedError", "ConnectionClosed")


def _stale_bucket(staleness_ms: Optional[float], healthy: bool) -> str:
    """Coarse bucket for STREAM_STALENESS_TRANSITION lines."""
    if not healthy and staleness_ms is None:
        return "no_l1_yet"
    if staleness_ms is None:
        return "grace_or_unknown"
    if staleness_ms < 5_000:
        return "fresh_lt_5s"
    if staleness_ms < 15_000:
        return "aging_5_to_15s"
    if staleness_ms < STREAMING_STALE_MS:
        return "warn_15_to_25s"
    return "unhealthy_ge_25s"


def _diag_on_active_l1_tick(sym: str) -> None:
    """Log STREAM_LAST_UPDATE_TS at INFO (throttled); proves L1 path without flooding logs."""
    global _diag_l1_last_info_log_ts
    now = time.time()
    if now - _diag_l1_last_info_log_ts < _STREAM_DIAG_L1_INFO_INTERVAL_SEC:
        return
    _diag_l1_last_info_log_ts = now
    ts = _streaming_last_update_ts
    _log_stream(
        "STREAM_LAST_UPDATE_TS",
        sym=sym,
        stream_last_update_ts=ts,
        age_sec=round(now - ts, 3) if ts is not None else None,
    )


async def _async_staleness_watch() -> None:
    """
    Sample staleness every 5s and log STREAM_STALENESS_TRANSITION when the bucket changes.
    Exits when shutdown_event is set (same event as message loop).
    """
    ev = _stream_shutdown_event
    if ev is None:
        return
    last_bucket: Optional[str] = None
    while _stream_running:
        try:
            await asyncio.wait_for(ev.wait(), timeout=5.0)
            break
        except asyncio.TimeoutError:
            pass
        d = get_streaming_diagnostics()
        sm = d.get("streaming_staleness_ms")
        h = bool(d.get("streaming_healthy"))
        bucket = _stale_bucket(sm if isinstance(sm, (int, float)) else None, h)
        tk = d.get("streaming_ticker")
        if bucket != last_bucket:
            _log_stream(
                "STREAM_STALENESS_TRANSITION",
                from_bucket=last_bucket,
                to_bucket=bucket,
                staleness_ms=sm,
                streaming_healthy=h,
                ticker=tk,
            )
            last_bucket = bucket


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
        "streaming_connected": bool(_stream_running and _streaming_logged_in),
        "streaming_ticker": _active_streaming_ticker,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": _streaming_healthy(),
    }


async def _resubscribe_to_ticker(sc: Any, ticker: str) -> None:
    global _subscribed_equity_syms, _active_streaming_ticker, _last_subscribe_completed_ts, _streaming_last_update_ts
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical stream key (idempotent on Schwab stream symbols)
    if not t:
        return
    old = list(_subscribed_equity_syms)
    new = [t]
    if old == new:
        return
    _log_stream("STREAM_RESUBSCRIBE_START", old=old, new=new)
    forget_unsubscribed_symbols(old, new)
    try:
        if old:
            await sc.level_one_equity_unsubs(old)
            await sc.nasdaq_book_unsubs(old)
            await sc.nyse_book_unsubs(old)
    except Exception as e:
        log.warning("stream unsubs: %s", e)
    await sc.level_one_equity_subs(new)
    await sc.nasdaq_book_subs(new)
    await sc.nyse_book_subs(new)
    _subscribed_equity_syms = new
    _active_streaming_ticker = t
    _last_subscribe_completed_ts = time.time()
    _streaming_last_update_ts = None
    log.info("Streaming resubscribed equity+book → %s", t)
    _log_stream("STREAM_RESUBSCRIBE_DONE", ticker=t)


async def _resubscribe_coro(ticker: str) -> None:
    if _stream_client is None:
        return
    lock = _stream_resubscribe_lock
    if lock is None:
        await _resubscribe_to_ticker(_stream_client, ticker)
        return
    async with lock:
        if _stream_client is None:
            return
        await _resubscribe_to_ticker(_stream_client, ticker)


def set_streaming_active_ticker(ticker: str) -> bool:
    """Switch Schwab L1+book to this symbol. Safe from any thread after the stream loop exists."""
    global _stream_loop, _pending_post_login_ticker
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical stream key (idempotent on Schwab stream symbols)
    if not t:
        return False
    loop = _stream_loop
    if loop is None or not loop.is_running():
        with _pending_lock:
            _pending_post_login_ticker = t
        log.debug("set_streaming_active_ticker: loop not ready, queued %s", t)
        return False
    # Loop is running but login() may still be in progress — never call subs before socket/login.
    if not _streaming_logged_in:
        with _pending_lock:
            _pending_post_login_ticker = t
        log.debug("set_streaming_active_ticker: login not complete, queued %s", t)
        return False
    fut = asyncio.run_coroutine_threadsafe(_resubscribe_coro(t), loop)
    try:
        fut.result(timeout=30.0)
    except TimeoutError:
        _log_stream("STREAM_RESUBSCRIBE_TIMEOUT", ticker=t)
    except Exception as e:
        _log_stream("STREAM_RESUBSCRIBE_ERROR", ticker=t, err=str(e))
    return True


async def _graceful_disconnect_stream_client(sc: Any) -> None:
    """LOGOUT + close websocket; avoids leaving websockets protocol tasks pending."""
    _log_stream("STREAM_CLIENT_CLOSE_START")
    try:
        if sc is not None:
            try:
                await sc.logout()
            except Exception as e:
                log.warning("STREAM_CLIENT_LOGOUT_FAIL err=%s", e)
        sock = getattr(sc, "_socket", None) if sc is not None else None
        if sock is not None:
            try:
                await sock.close()
            except Exception as e:
                log.warning("STREAM_WS_CLOSE_FAIL err=%s", e)
    finally:
        _log_stream("STREAM_CLIENT_CLOSE_DONE")


async def _drain_asyncio_tasks() -> None:
    """Cancel stray tasks (e.g. ensure_future from schwab async handlers) before loop teardown."""
    loop = asyncio.get_running_loop()
    cur = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks(loop) if t is not cur and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _message_loop_until_shutdown(sc: Any) -> None:
    """
    Process stream messages without asyncio.wait_for timeouts.
    Race handle_message against shutdown so we only cancel recv on intentional stop.
    """
    global _streaming_logged_in
    ev = _stream_shutdown_event
    assert ev is not None
    while _stream_running:
        msg_task = asyncio.create_task(sc.handle_message(), name="schwab_handle_message")
        shut_task = asyncio.create_task(ev.wait(), name="stream_shutdown_wait")
        done, pend = await asyncio.wait(
            {msg_task, shut_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pend:
            t.cancel()
        for t in pend:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if shut_task in done:
            _log_stream("STREAM_MESSAGE_LOOP_EXIT", reason="shutdown_event")
            break
        if not _stream_running:
            break
        # msg_task finished: consume exception so asyncio does not log "never retrieved"
        if msg_task.cancelled():
            continue
        err = msg_task.exception()
        if err is not None:
            _streaming_logged_in = False
            reason = "websocket_closed" if _is_stream_disconnect_error(err) else "handle_message_error"
            _log_stream(
                "STREAM_MESSAGE_LOOP_EXIT",
                reason=reason,
                err=f"{type(err).__name__}: {err}",
            )
            break
        # One message handled successfully; continue recv loop


def _run_stream_loop(
    client: Any,
    account_id: Any,
    initial_ticker: str,
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> None:
    global _stream_loop, _stream_running, _stream_client, _streaming_logged_in, _on_tick_callback
    global _stream_shutdown_event, _stream_resubscribe_lock

    _on_tick_callback = on_tick_callback

    async def _async_run() -> None:
        global _stream_running, _stream_client, _streaming_logged_in
        global _stream_shutdown_event, _stream_resubscribe_lock, _pending_post_login_ticker
        global _streaming_last_update_ts, _subscribed_equity_syms, _active_streaming_ticker

        _stream_shutdown_event = asyncio.Event()
        _stream_resubscribe_lock = asyncio.Lock()
        _stream_running = True

        sc: Any = None
        try:
            from schwab.streaming import StreamClient
        except ImportError as e:
            log.warning("schwab.streaming not available — %s", e)
            _stream_running = False
            _stream_shutdown_event = None
            _stream_resubscribe_lock = None
            return

        sc = StreamClient(client, account_id=account_id)
        _stream_client = sc
        _log_stream("STREAM_CLIENT_START", account_id=str(account_id))

        def _book_handler(msg: dict) -> None:
            content = msg.get("content") or []
            for item in content:
                if isinstance(item, dict):
                    sym = (item.get("key") or "").upper().strip()
                    if sym:
                        push_book(sym, item)
                        if _on_tick_callback:
                            try:
                                _on_tick_callback(sym)
                            except Exception as e:
                                log.debug("Tick callback: %s", e)

        def _level_one_handler(msg: dict) -> None:
            global _streaming_last_update_ts
            content = msg.get("content") or []
            for item in content:
                if isinstance(item, dict):
                    sym = (item.get("key") or "").upper().strip()
                    if sym:
                        if _active_streaming_ticker and sym.upper() == _active_streaming_ticker.upper():
                            _streaming_last_update_ts = time.time()
                            _diag_on_active_l1_tick(sym)
                        push_level_one(sym, item)
                        try:
                            _lmp.record_from_level_one_equity(sym, item)
                        except Exception as e:
                            log.debug("live_market_plane ingest: %s", e)
                        if _on_tick_callback:
                            try:
                                _on_tick_callback(sym)
                            except Exception as e:
                                log.debug("Tick callback: %s", e)

        # ── OPTIONS handlers (LEVELONE_OPTIONS / OPTIONS_BOOK) ────────────────────────────
        # These run INLINE on this loop, exactly like the equity handlers above, so they must
        # stay O(1). They hand the frame to a bounded queue drained by a separate writer
        # THREAD and return; no SQLite work happens here. Measured: p50 6 us / p99 32 us per
        # offer, against a 3,900/s write throughput and a realistic 243 frames/s — see
        # tools/measure_options_ingest_capacity_v1.py and reports/options_ingest_capacity_*.
        # Doing the write inline instead would put fsync on the same thread that services
        # LEVELONE_EQUITIES / NASDAQ_BOOK / NYSE_BOOK.

        try:
            sc.add_nasdaq_book_handler(_book_handler)
            sc.add_nyse_book_handler(_book_handler)
            sc.add_level_one_equity_handler(_level_one_handler)

            # OPTIONS collection is NOT started here. This UI stream is observational — it serves
            # live quotes and persists nothing. Raw options Collect belongs to the capture daemon
            # (tools/run_stream_capture.py + options_stream_collect.py), the single stream owner.

            await sc.login()
            _streaming_logged_in = True
            _log_stream("STREAM_CLIENT_CONNECTED")

            with _pending_lock:
                first = _pending_post_login_ticker or initial_ticker
                _pending_post_login_ticker = None
            await _resubscribe_to_ticker(sc, first)

            log.info("Order flow streaming connected; active L1 = %s", _active_streaming_ticker)

            watch_task = asyncio.create_task(_async_staleness_watch(), name="stream_staleness_watch")
            try:
                await _message_loop_until_shutdown(sc)
            finally:
                watch_task.cancel()
                try:
                    await watch_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            log.warning("Order flow streaming error: %s", e)
        finally:
            try:
                await _graceful_disconnect_stream_client(sc)
            except Exception as e:
                log.warning("STREAM_CLIENT_CLOSE_EXCEPTION err=%s", e)
            try:
                await _drain_asyncio_tasks()
            except Exception as e:
                log.warning("STREAM_TASK_DRAIN_FAIL err=%s", e)
            _streaming_logged_in = False
            _stream_client = None
            _stream_running = False
            _stream_shutdown_event = None
            _stream_resubscribe_lock = None
            _streaming_last_update_ts = None
            _subscribed_equity_syms = []
            _active_streaming_ticker = None
            clear_all_live_state()
            log.info("Order flow streaming stopped")

    _stream_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_stream_loop)
    try:
        _stream_loop.run_until_complete(_async_run())
    except Exception as e:
        log.warning("stream loop exit: %s", e)
    finally:
        _log_stream("STREAM_LOOP_STOP_START")
        try:
            # Defensive: loop should have no pending callbacks if _async_run exited cleanly
            if _stream_loop is not None and not _stream_loop.is_closed():
                _stream_loop.close()
        except Exception as e:
            log.warning("STREAM_LOOP_CLOSE_FAIL err=%s", e)
        _log_stream("STREAM_LOOP_STOP_DONE")
        _stream_loop = None


def start_order_flow_stream(
    client: Any,
    account_id: Any,
    initial_ticker: str,
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    global _stream_thread
    if not account_id:
        log.warning("Order flow streaming: no account_id")
        return False
    it = (initial_ticker or "").upper().strip()
    if not it:
        log.warning("Order flow streaming: no initial ticker")
        return False

    if _stream_thread is not None and _stream_thread.is_alive():
        log.info("Order flow streaming already running")
        return True

    _stream_thread = threading.Thread(
        target=_run_stream_loop,
        args=(client, account_id, it),
        kwargs={"on_tick_callback": on_tick_callback},
        daemon=True,
        name="order-flow-stream",
    )
    _stream_thread.start()
    log.info("Order flow streaming thread started (initial ticker %s)", it)
    return True


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    """
    Signal the stream loop to exit, close the Schwab websocket cleanly, then join the thread.

    Must be called from app shutdown **before** the process exits or the main event loop closes.
    """
    global _stream_running, _stream_shutdown_event, _stream_loop, _stream_thread, _streaming_logged_in, _streaming_last_update_ts

    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _stream_running = False
    _streaming_logged_in = False
    _streaming_last_update_ts = None
    clear_all_live_state()
    loop = _stream_loop
    ev = _stream_shutdown_event
    if loop is not None and ev is not None:
        try:

            def _signal() -> None:
                try:
                    ev.set()
                except Exception as e:
                    log.warning("STREAM_SHUTDOWN_EVENT_SET_FAIL err=%s", e)

            loop.call_soon_threadsafe(_signal)
        except Exception as e:
            log.warning("STREAM_SHUTDOWN_SIGNAL_FAIL err=%s", e)

    th = _stream_thread
    if th is not None and th.is_alive():
        th.join(timeout=join_timeout)
        if th.is_alive():
            _log_stream("STREAM_THREAD_JOIN_TIMEOUT", seconds=join_timeout)
        else:
            _log_stream("STREAM_THREAD_JOIN_DONE")
    else:
        _log_stream("STREAM_THREAD_JOIN_DONE", note="no_alive_thread")


def get_stream_thread() -> Optional[threading.Thread]:
    return _stream_thread
