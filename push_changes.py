"""The console's push: which of a ticker's served values changed (the panels they move are pushed
again).

Every open page holds one connection (/api/live, server.live_values) on its ticker, kept in the
order they opened, with the panels its view shows (`Client.panels`: name -> route).
A changed value (`changed`) reaches the pages open on its ticker on the event loop, and counts
toward the ticker's generation of that kind: an answer computed at one count is current until the
next.
"""
from __future__ import annotations

import asyncio
from collections import Counter

LEVELS, CHAIN, FLOW, LIQUIDITY = "levels", "chain", "flow", "liquidity"

_loop: asyncio.AbstractEventLoop | None = None
#: (ticker, connection) of every open page, oldest first
_open: "list[tuple[str, Client]]" = []
#: each (ticker, kind)'s changes so far
_count: "Counter[tuple[str, str]]" = Counter()


class Client:
    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.wake = asyncio.Event()
        #: each panel the page's view shows -> the route whose answer it shows
        self.panels: dict[str, str] = {}


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def watched() -> list[str]:
    """Every ticker an open page shows, on any workspace."""
    return list(dict.fromkeys(tk for tk, _c in list(_open)))


def shown() -> set[str]:
    """Every route an open page shows."""
    return {url for _tk, c in list(_open) for url in c.panels.values()}


def generation(tk: str, kinds: set[str]) -> tuple[int, ...]:
    """`tk`'s count of changes of each of `kinds` (on the event loop)."""
    return tuple(_count[(tk, k)] for k in sorted(kinds))


def subscribe(tk: str, c: "Client | None" = None) -> Client:
    """A page opened on `tk` (on the event loop), as connection `c` (a new one when not given:
    a caller that must close it whatever happens creates it first)."""
    c = Client() if c is None else c
    _open.append((tk, c))
    return c


def unsubscribe(tk: str, c: Client) -> None:
    """The page closed (on the event loop)."""
    _open[:] = [(t, x) for t, x in _open if x is not c]


def changed(tk: str, kind: str) -> None:
    """Callable from any thread."""
    if _loop is not None and tk in watched():
        _loop.call_soon_threadsafe(_mark, tk, kind)


def _mark(tk: str, kind: str) -> None:
    _count[(tk, kind)] += 1
    for t, c in _open:
        if t == tk:
            c.kinds.add(kind)
            c.wake.set()


async def next_changes(c: Client, timeout: float) -> set[str]:
    """The kinds changed since the last call; empty after `timeout` seconds with none."""
    try:
        await asyncio.wait_for(c.wake.wait(), timeout)
    except asyncio.TimeoutError:
        return set()
    c.wake.clear()
    kinds, c.kinds = c.kinds, set()
    return kinds
