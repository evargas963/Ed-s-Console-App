"""
L1 trigger hooks — quote/stream, L2 snapshot ready, ticker/expiry scope change.

Handlers use lazy import of server to avoid import cycles at startup.
Debounce quote storms; L2-ready and scope changes are immediate.

Tier B HTTP (notify_ticker_expiry_changed): returns server._l1_http_get_projection — the same full_overlay
assembly as HTTP GET /api/analytics/light and as the SSE event payload body (Issue 28; see
server.L1_TIER_B_CHANNEL_PAYLOAD_MODE).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional
from instrument_identity import ticker_storage_key

log = logging.getLogger("ed.planes.l1_events")

#: per ticker: a rebuild is running ("running") and another quote arrived meanwhile ("dirty")
_inflight: dict[str, dict[str, bool]] = {}
_inflight_lock = threading.Lock()
_executor = None


def _quote_executor():
    global _executor
    if _executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="l1-quote")
    return _executor

# Optional test hook
_rebuild_quote_fn: Optional[Callable[[str], None]] = None

#: failures on the displayed-price path, by stage -- surfaced in /api/live/plane diagnostics.
#: A failing quote_tick used to log at DEBUG only: the header held on the 1 s beat and nothing
#: said the per-tick push was broken (audit of #280).
quote_path_failures: dict[str, int] = {"subscriber_gate": 0}


def _note_quote_path_failure(stage: str, ticker: str, ex: BaseException) -> None:
    n = quote_path_failures[stage] = quote_path_failures[stage] + 1
    if n & (n - 1) == 0:                  # 1st, 2nd, 4th, 8th ... -- loud, never a flood
        log.warning("L1 %s failed for %s (%s failures so far): %s: %s",
                    stage, ticker, n, type(ex).__name__, ex)


def notify_quote_updated(ticker: str) -> None:
    """Plane row listener (registered by the console): rebuild the L1 analytics projection for
    this ticker when someone is subscribed to its analytics stream -- a 43-symbol roster must
    not _project_l1 for names nobody is viewing. Leading-edge coalesce (one running + one
    trailing), no timer. Prices are not pushed from here (the capture daemon serves them)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical L1 key (write+read consistent; idempotent on stream symbols)
    if not t:
        return
    # Test hook drives the coalesce proof without an SSE client. Production rebuilds
    # only when someone is subscribed to this ticker's L1 stream.
    if _rebuild_quote_fn is None:
        try:
            import server as srv

            if not srv._l1_ticker_has_projection_subscriber(t):
                return
        except Exception as ex:  # noqa: BLE001 -- counted + WARNING; no rebuild on an unknown gate
            _note_quote_path_failure("subscriber_gate", t, ex)
            return
    with _inflight_lock:
        st = _inflight.setdefault(t, {"running": False, "dirty": False})
        if st["running"]:
            st["dirty"] = True
            return
        st["running"] = True
    _quote_executor().submit(_rebuild_until_clean, t)


def _rebuild_until_clean(t: str) -> None:
    while True:
        try:
            if _rebuild_quote_fn is not None:
                _rebuild_quote_fn(t)
            else:
                import server as srv

                srv._l1_on_quote_updated(t)
        except Exception as ex:
            log.warning("L1 quote rebuild failed for %s: %s", t, ex)
        with _inflight_lock:
            st = _inflight[t]
            if not st["dirty"]:
                st["running"] = False
                return
            st["dirty"] = False


def notify_l2_snapshot_ready(ticker: str, expiry: Optional[str]) -> None:
    """Call when L2 cache has a new acknowledged snapshot for (ticker, expiry)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical L1 key (write+read consistent; idempotent on stream symbols)
    if not t:
        return
    try:
        import server as srv

        srv._l1_on_l2_snapshot_ready(t, expiry)
    except Exception as ex:
        log.debug("L1 L2-ready hook: %s", ex)


def notify_ticker_expiry_changed(
    ticker: str, expiry: Optional[str], *, force: bool = False
) -> dict[str, Any]:
    """HTTP L1 read path — authoritative cache + optional explicit recompute (force)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical L1 key (write+read consistent; idempotent on stream symbols)
    if not t:
        raise ValueError("notify_ticker_expiry_changed: ticker is required")
    import server as srv

    return srv._l1_http_get_projection(t, expiry, force=force)
