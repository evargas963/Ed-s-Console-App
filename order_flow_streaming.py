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

# ── OPTIONS collection (LEVELONE_OPTIONS / OPTIONS_BOOK) on this SAME client ──────────────
# Off unless explicitly enabled. Enabling changes what production streams and how fast the
# database grows, so it is a deliberate act rather than a side effect of deploying this file.
# MEASURED COST at the canary size (240 contracts): 243 frames/s, 1,824 bytes/frame,
# ~1.59 GB per RTH hour ~= 10.3 GB per RTH day. That is why this starts OFF and why the
# default scale is a canary/measurement set rather than the full enrolled universe.
ED_OPTIONS_STREAM_ENV = "ED_OPTIONS_STREAM"
_options_ingest: Any = None
_options_subscribed_syms: list[str] = []
_options_last_receipt: dict[str, Any] | None = None
#: The last slice this process applied — what rotated in, what rotated out, and when. Without it
#: an operator can see that frames are arriving but not that the ROTATION is advancing, which is
#: the difference between "options collection works" and "the intended architecture is running".
_options_last_slice: dict[str, Any] | None = None
#: The rotation task, on the stream's own event loop. Held so the loop's finally can cancel it;
#: an orphaned rotation would keep subscribing against a client that is being torn down.
_options_rotation_task: Any = None


def options_streaming_enabled() -> bool:
    """True only when the operator has explicitly turned options collection on."""
    import os
    return str(os.environ.get(ED_OPTIONS_STREAM_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def _options_frame_handler(service: str) -> Callable[[dict], None]:
    """Hand ONE options frame to the bounded queue and return. O(1), no SQLite here.

    Hoisted to module scope 2026-08-26 so its failure containment can be DRIVEN. It closes
    over nothing local — `_options_ingest`, `time` and `log` are module globals read at call
    time — so this is a pure move. It was nested inside _run_stream_loop, which made the
    property assertable only by reading the function's source text, and RC-308 is explicit:
    if the property is behaviour, assert the behaviour.
    """
    def _handler(msg: dict) -> None:
        ing = _options_ingest
        if ing is None:
            return
        try:
            ing.offer(service, msg, received_ts_ms=int(time.time() * 1000.0))
        except Exception as e:                  # noqa: BLE001
            # An options storage problem must never propagate into the shared loop.
            log.debug("options ingest offer (%s): %s", service, e)
    return _handler


def _register_options_handlers(sc: Any, make_handler: Callable[[str], Callable[[dict], None]]) -> None:
    """Attach options handlers to the EXISTING client. Inert until something subscribes.

    Registration is separated from subscription on purpose: a handler with no subscription
    receives nothing, so this is safe to run unconditionally and keeps the enable/disable
    decision in exactly one place (_start_options_collection).
    """
    for attr, service in (("add_level_one_option_handler", "LEVELONE_OPTIONS"),
                          ("add_options_book_handler", "OPTIONS_BOOK")):
        fn = getattr(sc, attr, None)
        if fn is None:
            log.warning("stream client has no %s — options %s cannot be collected", attr, service)
            continue
        try:
            fn(make_handler(service))
        except Exception as e:                          # noqa: BLE001
            log.warning("registering %s failed: %s", attr, e)


def options_desired_for_slice(at_epoch_s: float, *, equity_symbols: int,
                              book_enabled: bool = True) -> dict[str, Any]:
    """THE ONE COMPUTATION of "which contracts should be subscribed at this instant".

    Everything downstream — the first subscribe at stream start, every rotation boundary, and
    the diagnostics surface — asks THIS function and reconciles to its answer. A second place
    that decided what to subscribe would be a second coverage authority, and the two would
    disagree the first time either changed.

    The shape it produces is the intended architecture made concrete:
      * CORE underlyings appear in every slice, so their coverage is continuous rather than
        sampled; they are the money path.
      * the remaining budget rotates deterministically over the rest of the enrolled universe,
        so each non-core underlying gets REAL depth periodically instead of a permanent sliver.
      * the budget itself is DERIVED from the vendor key limit and the keys the equity path is
        actually holding right now, so options can never crowd out the stream the console
        depends on.

    Deterministic and stateless: the cohort is a pure function of the clock and the roster
    (RotationPolicy.slice_index), so replay can reconstruct which underlyings were eligible at a
    past instant without consulting anything but those two.
    """
    from options_stream_subscription import (
        RotationPolicy, SelectionPolicy, build_chains_for_selection,
        contract_budget_from_key_limit, rotation_cohort, select_contracts, split_budget,
    )

    pol = RotationPolicy()
    universe = sorted(build_chains_for_selection().keys())
    cohort = rotation_cohort(universe, at_epoch_s, pol)
    budget = contract_budget_from_key_limit(
        equity_symbols=max(1, int(equity_symbols)), book_enabled=book_enabled)
    split = split_budget(budget["contracts_allowed"], len(cohort["core"]),
                         len(cohort["rotating"]), pol)

    symbols: list[str] = []
    per_underlying: dict[str, int] = {}
    notes: list[str] = []
    # Core and cohort are selected SEPARATELY so the core's depth cannot be diluted by a large
    # cohort — select_contracts allocates round-robin within the set it is given, and a single
    # combined call would spread one ceiling across everything.
    for label, names, ceiling in (("core", cohort["core"], split["core"]),
                                  ("rotating", cohort["rotating"], split["rotating"])):
        if not names or ceiling <= 0:
            continue
        chains = build_chains_for_selection(tickers=names)
        missing = sorted(set(names) - set(chains))
        if missing:
            # A NAME WITH NO FRESH CHAIN IS A COVERAGE GAP, not a market observation. Say so
            # here so the slice record shows it rather than the reader inferring it from absence.
            notes.append(f"{label}: no fresh chain for {missing} — not subscribed this slice")
        sel = select_contracts(chains, SelectionPolicy(max_contracts=int(ceiling)))
        symbols.extend(sel.symbols)
        for k, v in sel.per_underlying.items():
            per_underlying[k] = per_underlying.get(k, 0) + v
        notes.extend(f"{label}: {n}" for n in sel.notes)

    return {
        "at_epoch_s": float(at_epoch_s),
        "slice_index": cohort["slice_index"],
        "slice_seconds": cohort["slice_seconds"],
        "core": cohort["core"],
        "rotating": cohort["rotating"],
        "non_core_total": cohort["non_core_total"],
        "full_cycle_slices": cohort["full_cycle_slices"],
        "full_cycle_seconds": cohort["full_cycle_seconds"],
        "budget": budget,
        "split": split,
        "symbols": symbols,
        "per_underlying": per_underlying,
        "notes": notes,
        "policy": cohort["policy"],
    }


async def _apply_options_slice(sc: Any, at_epoch_s: float, reason: str) -> dict[str, Any]:
    """Reconcile the live subscription to what this slice should be observing.

    ORDERING IS THE WHOLE POINT, because the coverage record must never claim observability we
    did not have:
      * DROP first, and close each dropped contract's epoch only AFTER the vendor has confirmed
        the unsubscribe. Closing before would leave frames arriving inside a window the record
        says was shut; unsubscribing first means nothing can arrive after the close instant.
      * ADD second, and open an epoch only for services the vendor ACCEPTED. Opening before the
        receipt would claim coverage the account may never have been granted.
    Core symbols normally appear in both the old and the new set, so they are neither dropped
    nor re-added — their coverage stays CONTINUOUS across slice boundaries by construction, not
    by a special case.
    """
    global _options_subscribed_syms, _options_last_receipt, _options_last_slice

    from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
    from calibration.options_stream_coverage import close_epochs, open_epochs
    from options_stream_subscription import subscribe_options, unsubscribe_options

    plan = options_desired_for_slice(
        at_epoch_s, equity_symbols=len(_subscribed_equity_syms) or 1, book_enabled=True)
    want = list(dict.fromkeys(plan["symbols"]))
    have = list(_options_subscribed_syms)
    to_drop = [s for s in have if s not in set(want)]
    to_add = [s for s in want if s not in set(have)]

    dropped_ok = added = 0
    if to_drop:
        try:
            await unsubscribe_options(sc, to_drop)
            now_ms = int(time.time() * 1000.0)
            for service in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
                close_epochs(_CAPTURE_DB, to_drop, service=service, reason=reason, at_ms=now_ms)
            dropped_ok = len(to_drop)
        except Exception as e:                          # noqa: BLE001
            # Leaving them subscribed is the SAFE failure: the record still matches reality.
            log.warning("options rotation: unsubscribe failed, keeping %d contracts: %s",
                        len(to_drop), e)
            to_drop = []

    if to_add:
        receipt = await subscribe_options(sc, to_add)
        _options_last_receipt = receipt
        now_ms = int(time.time() * 1000.0)
        for service, ok in (("LEVELONE_OPTIONS", receipt.get("level_one")),
                            ("OPTIONS_BOOK", receipt.get("book"))):
            if ok:
                open_epochs(_CAPTURE_DB, to_add, service=service, policy=plan["policy"],
                            reason=reason, at_ms=now_ms)
        added = len(to_add)

    _options_subscribed_syms = [s for s in have if s not in set(to_drop)] + to_add
    _options_last_slice = {
        "reason": reason,
        "at_epoch_s": plan["at_epoch_s"],
        "slice_index": plan["slice_index"],
        "core": plan["core"],
        "rotating": plan["rotating"],
        "added": added,
        "dropped": dropped_ok,
        "subscribed_total": len(_options_subscribed_syms),
        "per_underlying": plan["per_underlying"],
        "full_cycle_seconds": plan["full_cycle_seconds"],
        "notes": plan["notes"][:12],
    }
    log.info("OPTIONS slice %s (%s): +%d -%d = %d contracts across %d underlyings; "
             "core=%s rotating=%s cycle=%ss",
             plan["slice_index"], reason, added, dropped_ok, len(_options_subscribed_syms),
             len(plan["per_underlying"]), plan["core"], plan["rotating"],
             plan["full_cycle_seconds"])
    _log_stream("OPTIONS_SLICE", **{k: _options_last_slice[k] for k in
                                    ("reason", "slice_index", "added", "dropped",
                                     "subscribed_total")})
    return _options_last_slice


async def _options_rotation_loop(sc: Any) -> None:
    """Advance the rotation at each slice boundary, on the SAME loop and the SAME client.

    This is the pattern the staleness watch already uses in _run_stream_loop: a task on the
    existing loop, cancelled in the same finally. It is deliberately NOT a thread and NOT a
    second client — a second streaming authority would be free to disagree with this one about
    what is subscribed.

    Boundaries are computed from the clock rather than by sleeping a fixed interval, so a slow
    slice cannot make the rotation drift away from the deterministic slice_index that replay
    and the coverage record both depend on.
    """
    from options_stream_subscription import RotationPolicy

    pol = RotationPolicy()
    while True:
        now = time.time()
        nxt = (pol.slice_index(now) + 1) * float(pol.slice_seconds)
        try:
            await asyncio.sleep(max(1.0, nxt - now))
        except asyncio.CancelledError:
            raise
        try:
            await _apply_options_slice(sc, time.time(), reason="rotation")
        except asyncio.CancelledError:
            raise
        except Exception as e:                          # noqa: BLE001
            # A failed slice must not end the rotation, and must never touch the equity path.
            log.warning("options rotation slice failed (collection continues): %s", e)


async def _start_options_collection(sc: Any) -> None:
    """Select contracts, start the writer, subscribe, and RECORD the coverage.

    Every failure path here is soft. Options collection is additive; if any part of it cannot
    start, the equity/book stream this console actually depends on must be unaffected.
    """
    global _options_ingest, _options_rotation_task
    if not options_streaming_enabled():
        log.info("options streaming disabled (%s unset) — LEVELONE_OPTIONS/OPTIONS_BOOK "
                 "handlers registered but nothing subscribed", ED_OPTIONS_STREAM_ENV)
        return
    try:
        # RC-6 law: raw stream capture goes to stream_capture.db, NEVER ed_console.db.
        from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
        from calibration.options_stream_ingest import OptionsFrameIngest
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection unavailable: %s", e)
        return

    try:
        # The writer starts BEFORE anything is subscribed: a frame that arrives with no queue to
        # take it would be a loss the accounting could not see.
        _options_ingest = OptionsFrameIngest(_CAPTURE_DB)
        _options_ingest.start()

        # The first subscribe is just slice zero. It runs through the SAME reconciler every
        # rotation boundary uses, so start-up and steady state cannot drift apart — this used to
        # be a separate one-shot selection that subscribed the whole budget at once and never
        # rotated, which is how the core+rotating architecture existed in code and not in the
        # running system.
        await _apply_options_slice(sc, time.time(), reason="stream_start")
        if not _options_subscribed_syms:
            log.warning("options collection: slice produced no contracts — nothing subscribed "
                        "(this is a COVERAGE GAP, not a market observation)")
            return

        _options_rotation_task = asyncio.create_task(
            _options_rotation_loop(sc), name="options_rotation")
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection failed to start (equity stream unaffected): %s", e)


def _stop_options_collection(reason: str = "stream_stop") -> None:
    """Close coverage epochs and drain the writer. Called from the stream loop's finally.

    Closing epochs matters as much as stopping the writer: an epoch left open would claim we
    were observing those contracts during a window when the process was not running.
    """
    global _options_ingest, _options_subscribed_syms, _options_rotation_task, _options_last_slice
    # Stop advancing the rotation BEFORE closing epochs: a slice that fired mid-teardown would
    # open epochs for contracts this process is about to stop observing.
    task, _options_rotation_task = _options_rotation_task, None
    if task is not None:
        try:
            task.cancel()
        except Exception as e:                          # noqa: BLE001
            log.warning("cancelling options rotation: %s", e)
    _options_last_slice = None
    try:
        if _options_subscribed_syms:
            from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
            from calibration.options_stream_coverage import close_epochs
            now_ms = int(time.time() * 1000.0)
            for service in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
                close_epochs(_CAPTURE_DB, _options_subscribed_syms, service=service,
                             reason=reason, at_ms=now_ms)
    except Exception as e:                              # noqa: BLE001
        log.warning("closing options coverage epochs: %s", e)
    finally:
        _options_subscribed_syms = []
    try:
        if _options_ingest is not None:
            stats = _options_ingest.stop(timeout=30.0)
            log.info("OPTIONS ingest stopped: %s", stats)
            _log_stream("OPTIONS_INGEST_STOPPED", **{
                k: stats.get(k) for k in ("offered", "written", "dropped", "write_errors",
                                          "max_queue_depth", "accounting_complete")})
    except Exception as e:                              # noqa: BLE001
        log.warning("stopping options ingest: %s", e)
    finally:
        _options_ingest = None


def options_stream_status() -> dict[str, Any]:
    """Live options-collection health, for the diagnostics surface."""
    ing = _options_ingest
    out: dict[str, Any] = {
        "enabled": options_streaming_enabled(),
        "subscribed_contracts": len(_options_subscribed_syms),
        "last_receipt": _options_last_receipt,
        # ROTATION VISIBILITY. Frames arriving proves collection; only this proves the rotation
        # is advancing, which is what makes coverage universal rather than a fixed sliver.
        "last_slice": _options_last_slice,
        "rotation_running": bool(_options_rotation_task is not None
                                 and not _options_rotation_task.done()),
        "ingest": None,
    }
    if ing is not None:
        s = ing.stats.snapshot()
        s["queue_depth"] = ing.queue_depth()
        out["ingest"] = s
    return out


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

            # Registered on the SAME client — no second socket, no second source of truth.
            # Registering a handler is inert until something subscribes, so this cannot change
            # existing stream behaviour on its own.
            _register_options_handlers(sc, _options_frame_handler)

            await sc.login()
            _streaming_logged_in = True
            _log_stream("STREAM_CLIENT_CONNECTED")

            with _pending_lock:
                first = _pending_post_login_ticker or initial_ticker
                _pending_post_login_ticker = None
            await _resubscribe_to_ticker(sc, first)

            # Options coverage is deliberately NOT tied to the viewer's ticker. Inheriting the
            # equity path's single-active-symbol behaviour would make options HISTORY a
            # function of what someone happened to be looking at.
            await _start_options_collection(sc)

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
            # Before the socket goes: close coverage epochs and drain the options writer, so
            # retained history does not claim observability past the end of the session.
            try:
                _stop_options_collection("stream_stop")
            except Exception as e:                      # noqa: BLE001
                log.warning("OPTIONS_STOP_EXCEPTION err=%s", e)
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
