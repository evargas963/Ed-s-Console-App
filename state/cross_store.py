"""Every ticker's newest CROSSES_KEPT level crosses, newest last, as stored rows.

Loaded from level_crosses once the watchlist is known (load), then each cross as it is recorded
(add, from server._log_level_crosses). Every live reader reads them here, never the database
(docs/DATA_FLOW.md §2 D6).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from db import StoredCross, get_db

CROSSES_KEPT = 1600
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
        _crosses[tk] = get_db().get_recent_crosses(ticker=tk, n=CROSSES_KEPT)[::-1]
    return _crosses[tk]


def load(watchlist: list[str]) -> None:
    """Load the watchlist's held level crosses, at the console's start."""
    with _lock:
        for tk in watchlist:
            _held(tk)


def add(tk: str, logged: list[StoredCross]) -> None:
    """Hold the crosses just stored (`logged`, the rows record_level_crosses returned)."""
    with _lock:
        held = _held(tk)
        held.extend(logged)
        del held[:-CROSSES_KEPT]


def merged_recent(ticker: str, n: int) -> list[MergedCross]:
    """Return the newest `n` level crosses, each (time, value, direction) one event.

    Each event names every level there (`level_names`). The one reader of level crosses for every
    route. Price crossing one strike writes one stored row per named level sitting there; they
    are merged here, at the read, so the stored history keeps its per-level rows.
    """
    with _lock:
        raw = _crosses[ticker][::-1][: max(int(n) * 8, 64)] if ticker in _crosses else []
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
    return merged[:n]
