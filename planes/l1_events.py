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

log = logging.getLogger("ed.planes.l1_events")

_DEBOUNCE_SEC = 0.12
_timers: dict[str, threading.Timer] = {}
_timer_lock = threading.Lock()

# Optional test hook
_rebuild_quote_fn: Optional[Callable[[str], None]] = None


def set_quote_rebuild_handler(fn: Optional[Callable[[str], None]]) -> None:
    global _rebuild_quote_fn
    _rebuild_quote_fn = fn


def notify_quote_updated(ticker: str) -> None:
    """Call when L0 quote row changes (stream or REST plane). Debounced per ticker."""
    t = (ticker or "").upper().strip()
    if not t:
        return

    def _run() -> None:
        try:
            if _rebuild_quote_fn is not None:
                _rebuild_quote_fn(t)
                return
            import server as srv

            srv._l1_on_quote_updated(t)
        except Exception as ex:
            log.debug("L1 quote hook: %s", ex)

    with _timer_lock:
        old = _timers.pop(t, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(_DEBOUNCE_SEC, _run)
        timer.daemon = True
        _timers[t] = timer
        timer.start()


def notify_l2_snapshot_ready(ticker: str, expiry: Optional[str]) -> None:
    """Call when L2 cache has a new acknowledged snapshot for (ticker, expiry)."""
    t = (ticker or "").upper().strip()
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
    t = (ticker or "").upper().strip()
    if not t:
        raise ValueError("notify_ticker_expiry_changed: ticker is required")
    import server as srv

    return srv._l1_http_get_projection(t, expiry, force=force)
