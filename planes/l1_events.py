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


def notify_quote_updated(ticker: str) -> None:
    """Call when the streamed quote row changes.

    quote_tick goes out first (plane row, no projection). L1 rebuild runs only when this
    ticker has an L1 SSE subscriber — a 43-symbol roster must not _project_l1 for names
    nobody is viewing. Leading-edge coalesce (one running + one trailing), no timer."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical L1 key (write+read consistent; idempotent on stream symbols)
    if not t:
        return
    try:
        import server as srv

        srv._notify_quote_tick(t)
    except Exception as ex:
        log.debug("quote_tick notify: %s", ex)
    # Test hook drives the coalesce proof without an SSE client. Production rebuilds
    # only when someone is subscribed to this ticker's L1 stream.
    if _rebuild_quote_fn is None:
        try:
            import server as srv

            if not srv._l1_ticker_has_projection_subscriber(t):
                return
        except Exception as ex:
            log.debug("L1 subscriber gate: %s", ex)
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
