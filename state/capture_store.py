"""Every ticker's newest chain captures, as the sweep took them: the live path's history.

A capture is the chain the sweep stored as a day's close capture (feed.chain_sweep), marked on
its chain messages; the console keeps it here as it arrives (server._on_chain), the newest of each
of the CAPTURE_DAYS newest market days, each a StoredCapture as
calibration.complete_chain_capture.last_capture_per_day reads them back. A ticker's stored
captures are loaded once, the first time it is asked for (the startup loader, rule 6); from then
on every live reader reads them here, never the database.
"""

from __future__ import annotations

import threading
from pathlib import Path

from calibration.complete_chain_capture import StoredCapture, last_capture_per_day
from instrument_identity import ticker_storage_key

#: the market days of captures the levels read (today's and the prior day: the two newest)
CAPTURE_DAYS = 2

#: ticker -> its captures, newest first, one per ET date (each a new list, never mutated)
_held: dict[str, list[StoredCapture]] = {}
_lock = threading.Lock()


def captures(db_path: Path | str, ticker: str) -> list[StoredCapture]:
    """Return the ticker's newest capture of each of its CAPTURE_DAYS newest days, newest first.

    Loaded once from the database the first time the ticker is asked for (its stored history);
    from then on what the sweep marked as captures, kept as they arrive (keep).
    """
    tk = ticker_storage_key(ticker)
    with _lock:
        if tk not in _held:
            _held[tk] = last_capture_per_day(db_path, tk, CAPTURE_DAYS)
        return _held[tk]


def keep(ticker: str, capture: StoredCapture) -> None:
    """Keep a capture the sweep just stored: the newest of its ET date, ahead of older days.

    Called on the event loop as the chain arrives, so it reads no database: a ticker whose
    captures are not loaded yet needs nothing kept, for the sweep stores a capture before it
    delivers its chain (feed.chain_sweep.deliver), and the first load reads it.
    """
    tk = ticker_storage_key(ticker)
    with _lock:
        if tk in _held:
            older = [c for c in _held[tk] if c.et_date != capture.et_date]
            _held[tk] = [capture, *older][:CAPTURE_DAYS]


def newest_ts(db_path: Path | str, ticker: str) -> float | None:
    """When the ticker's newest capture was taken; None with none."""
    held = captures(db_path, ticker)
    return held[0].ts_utc if held else None


def clear() -> None:
    """Drop every ticker's captures: each next ask loads its stored ones again (a test's start)."""
    with _lock:
        _held.clear()
