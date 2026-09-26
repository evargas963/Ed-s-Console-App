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


