"""Flip-drift measurement log (unproven-register row, PROVEN 2026-08-02): one JSONL row per
terrain compute during a tradable session. Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-first slice). Pure: no server runtime state.
"""
from __future__ import annotations

import json
import logging
import threading

from runtime_layout import reports_dir

log = logging.getLogger(__name__)


#: Flip-drift measurement (unproven-register row due 2026-07-31): the mechanism is
#: proven (gamma depends on spot/IV/time) but the intraday MAGNITUDE of flip movement
#: is unmeasured. Every terrain-loop compute appends one JSONL row here so a week of
#: cycles yields per-ticker intraday min/max/range. reports/ file, not a table — the
#: operational DB grows by zero bytes (RC-6 discipline). flip=None is absence and is
#: not logged; gaps read as gaps from the timestamps.
_FLIP_DRIFT_LOG_PATH = reports_dir() / "flip_drift_log.jsonl"   # RC-523: artifacts root
_flip_drift_lock = threading.Lock()


def _log_flip_drift(tk: str, payload: dict) -> None:
    """Append one flip-drift row. Never raises — terrain refresh must stay ok:x
    even if logging row assembly or disk write fails (measurement only)."""
    try:
        flip = payload.get("gamma_flip")
        if flip is None:
            return
        # CAPS RC-REHAB-1: an undated terrain payload is NOT logged. It used to be stamped with
        # the log-append wall clock, filing the flip under a time it was never computed at
        # (a measurement row with an invented timestamp). Gaps read as gaps.
        _computed_ts = payload.get("computed_ts_utc")
        if not _computed_ts:
            return
        _ts = round(float(_computed_ts), 1)
        # RC-58: INTRADAY drift is the question, so only real trading sessions may be logged.
        # The loop runs around the clock, and the first week of this log was 784 of 784 rows from
        # a single SUNDAY window — spot frozen, so it measured a median 0.023 percent movement and
        # would have been reported as "the flip is stable intraday". Market-closed rows do not
        # add noise here, they manufacture the null.
        from time_et import is_tradable_session_ts_utc as _tradable
        if not _tradable(_ts):
            return
        row = {"ts_utc": _ts,
               "ticker": tk, "flip": round(float(flip), 4),
               "spot": payload.get("spot"), "confidence": payload.get("confidence")}
        with _flip_drift_lock, open(_FLIP_DRIFT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("flip drift log append failed: %s", e)
