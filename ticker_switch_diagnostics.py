"""
In-memory ring buffer for client-reported ticker-switch timing (reviewable via GET /api/diagnostics/ticker-switch).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

_MAX = 100
_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX)
_lock = threading.Lock()
_log = logging.getLogger(__name__)


def record_switch_event(payload: dict[str, Any]) -> None:
    """Append one completed (or partial) switch record. Server adds receipt timestamp."""
    row = dict(payload) if isinstance(payload, dict) else {}
    try:
        from verification.ui_realtime_transport_audit import enrich_switch_diag_record

        row = enrich_switch_diag_record(row)
    except Exception as exc:
        _log.debug("switch diag enrich skipped: %s", exc, exc_info=True)
    row["server_received_ts"] = time.time()
    with _lock:
        _buffer.appendleft(row)


def get_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    lim = max(1, min(limit, _MAX))
    with _lock:
        return list(_buffer)[:lim]
