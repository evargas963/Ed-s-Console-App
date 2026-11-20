"""Every ticker's level crosses over the longest window a screen reads, oldest first, as stored.

Loaded from level_crosses once the watchlist is known (load), then each cross as it is recorded
(add, from server._log_level_crosses). Every live reader reads them here, never the database
(docs/DATA_FLOW.md §2 D6).
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from dataclasses import dataclass

from db import StoredCross, get_db

#: the longest window a screen reads crosses over, seconds: the Trade Desk's daily chart's 20
#: days (push.desk.DESK_LOOKBACK). Every cross since the newest held one less this is held.
CROSSES_HELD_SEC = 20 * 86400
_crosses: dict[str, list[StoredCross]] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class MergedCross:
    """One price crossing one level value at one time, with every level named there.

    `cross` is the first stored row of them (its time, value, direction, spot and id).
    """

    cross: StoredCross
    level_names: list[str]


def _held(tk: str) -> list[StoredCross]:
    """Return the ticker's held level crosses, oldest first.

    The one database read of them, the first time they are needed (the console's start, or a
    cross found before it), then fed live. Called holding _lock.
    """
    if tk not in _crosses:
        _crosses[tk] = get_db().get_recent_crosses(ticker=tk, within_sec=CROSSES_HELD_SEC)[::-1]
    return _crosses[tk]


def load(watchlist: list[str]) -> None:
    """Load the watchlist's held level crosses, at the console's start."""
    with _lock:
        for tk in watchlist:
            _held(tk)


def add(tk: str, logged: list[StoredCross]) -> None:
    """Hold the crosses just stored (`logged`, the rows record_level_crosses returned).

    Those older than CROSSES_HELD_SEC before the newest held are let go.
    """
    with _lock:
        held = _held(tk)
        held.extend(logged)
        if held:
            oldest = held[-1].ts_utc - CROSSES_HELD_SEC
            del held[: bisect_left(held, oldest, key=lambda c: c.ts_utc)]


def merged_since(ticker: str, start: float) -> list[MergedCross]:
    """Return the level crosses at or after `start` (epoch seconds), newest first, each (time,
    value, direction) one event.

    Each event names every level there (`level_names`). The one reader of level crosses for every
    route. Price crossing one strike writes one stored row per named level sitting there; they
    are merged here, at the read, so the stored history keeps its per-level rows.
    """
    with _lock:
        held = _held(ticker)
        raw = held[bisect_left(held, start, key=lambda c: c.ts_utc) :][::-1]
    merged: list[MergedCross] = []
    seen: dict[tuple[float, float, str], MergedCross] = {}
    for r in raw:
        key = (r.ts_utc, r.level_value, r.direction)
        hit = seen.get(key)
        if hit is None:
            hit = seen[key] = MergedCross(r, [])
            merged.append(hit)
        if r.level_name not in hit.level_names:
            hit.level_names.append(r.level_name)
    return merged
