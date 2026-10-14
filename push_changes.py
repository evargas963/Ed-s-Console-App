"""The console's push: which of a symbol's served values changed (the panels they move are pushed
again).

Every open page holds one connection (/api/live, server.live_values) on its ticker, kept in the
order they opened, with the panels its view shows (`Client.panels`: name -> server._Panel); its
Schwab values come from the daemon's socket (live_ui). Every change of every symbol
(`changed`) counts toward that symbol's generation of its kind, whether or not a page shows it --
an answer computed at one count is current until the next -- and reaches the pages that show it,
on the event loop.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

LEVELS, CHAIN, FLOW, LIQUIDITY = "levels", "chain", "flow", "liquidity"
#: a Schwab feed a panel is read from went down or came back (streaming._mark_liveness)
LIVE = "live"

_loop: asyncio.AbstractEventLoop | None = None
#: (ticker, connection) of every open page, oldest first
_open: "list[tuple[str, Client]]" = []
#: each (symbol, kind)'s changes so far
_count: "Counter[tuple[str, str]]" = Counter()


class Client:
    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.wake = asyncio.Event()
        #: each panel the page's view shows -> its value (server._Panel)
        self.panels: dict[str, Any] = {}


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def watched() -> list[str]:
    """Every ticker an open page shows, on any workspace (a page with none chosen shows none)."""
    return list(dict.fromkeys(tk for tk, _c in list(_open) if tk is not None))


def feeds() -> "set[tuple[str, str, str]]":
    """(ticker, symbol, Schwab service) of each feed a panel an open page shows is read from."""
    return {(tk, s, svc) for tk, c in list(_open) for p in c.panels.values() for s, svc in p.feeds_now()}


def shown() -> set[str]:
    """Every panel value (its source) an open page shows."""
    return {p.source for _tk, c in list(_open) for p in c.panels.values()}


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
    loop = _loop                      # read once: the console's stop may unbind it meanwhile
    if loop is not None:
        loop.call_soon_threadsafe(_mark, tk, kind)


def _mark(tk: str, kind: str) -> None:
    _count[(tk, kind)] += 1
    for t, c in _open:
        if t == tk:
            c.kinds.add(kind)
            c.wake.set()


async def next_changes(c: Client, timeout: float) -> "set[str]":
    """The kinds changed for the page's ticker since the last call; empty after `timeout`
    seconds with none."""
    try:
        await asyncio.wait_for(c.wake.wait(), timeout)
    except asyncio.TimeoutError:
        return set()
    c.wake.clear()
    kinds, c.kinds = c.kinds, set()
    return kinds
