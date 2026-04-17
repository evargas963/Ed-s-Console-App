"""
Track Schwab HTTP signals that look like rate / throttle pressure (e.g. 429),
for dashboard warnings without requiring users to watch server logs.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

_log = logging.getLogger("ed_console.api_pressure")

_events: deque = deque(maxlen=60)
_lock = threading.Lock()

# How long a 429 keeps the UI warning visible (seconds)
THROTTLE_WARN_WINDOW_SEC: float = 180.0


def record_schwab_http_response(resp, endpoint: str) -> None:
    """Call with raw schwab-py HTTP response objects after each request."""
    if resp is None:
        return
    code = getattr(resp, "status_code", None)
    if code is None:
        return
    try:
        ic = int(code)
    except (TypeError, ValueError):
        return
    if ic != 429:
        return
    ep = str(endpoint or "api")[:120]
    now = time.time()
    with _lock:
        _events.append((now, ic, ep))
    _log.warning("Schwab HTTP %s on %s — possible rate limit (UI banner active ~%ds)", ic, ep, int(THROTTLE_WARN_WINDOW_SEC))


def throttle_ui_payload(window_sec: float | None = None) -> dict:
    """
    Return a small dict for JSON / UI:
    { active, message, hint, n_429_recent }
    """
    win = float(window_sec if window_sec is not None else THROTTLE_WARN_WINDOW_SEC)
    now = time.time()
    with _lock:
        ev = list(_events)
    hits = [(t, c, w) for t, c, w in ev if c == 429 and (now - t) <= win]
    if not hits:
        return {
            "active": False,
            "message": "",
            "hint": "",
            "n_429_recent": 0,
        }
    n = len(hits)
    last_where = hits[-1][2]
    return {
        "active": True,
        "n_429_recent": n,
        "message": (
            f"Schwab HTTP 429 (rate limit) on {last_where} — {n} hit(s) in the last ~{int(win)}s. "
            "Quotes or option data may be delayed."
        ),
        "hint": (
            "Increase refresh interval: set ED_VIEWER_SSE_REFRESH_SEC=2 (or 3) and "
            "ED_VIEWER_STATE_CACHE_TTL_SEC to the same, then restart the server."
        ),
    }
