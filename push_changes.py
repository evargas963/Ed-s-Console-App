"""The console's push: which of a ticker's served values changed (the page reloads what changed).

Every open page holds one connection (/api/changes) on its ticker, kept in the order they opened.
A changed value (`changed`) reaches the pages open on its ticker on the event loop.
"""

from __future__ import annotations

import asyncio

import time_et

LEVELS, CHAIN, FLOW, LIQUIDITY = "levels", "chain", "flow", "liquidity"

_loop: asyncio.AbstractEventLoop | None = None
#: (ticker, connection) of every open page, oldest first
_open: list[tuple[str, Client]] = []


class Client:
    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.wake = asyncio.Event()
        #: the program is stopping: the page's stream ends (the page reconnects to the next one)
        self.closed = False


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def watched() -> list[str]:
    """Every ticker an open page shows, on any workspace."""
    return list(dict.fromkeys(tk for tk, _c in list(_open)))


def subscribe(tk: str, c: Client | None = None) -> Client:
    """Record a page opened on `tk` (on the event loop), as connection `c`.

    A new connection when not given: a caller that must close it whatever happens creates it
    first.
    """
    c = Client() if c is None else c
    _open.append((tk, c))
    return c


def unsubscribe(tk: str, c: Client) -> None:
    """Record that the page closed (on the event loop)."""
    _open[:] = [(t, x) for t, x in _open if x is not c]


def close_all() -> None:
    """Record that the program is stopping (on the event loop).

    Every open page's stream ends now, so the web server closes without waiting out its
    graceful timeout.
    """
    for _t, c in _open:
        c.closed = True
        c.wake.set()


def changed(tk: str, kind: str) -> None:
    """Callable from any thread."""
    if _loop is not None and tk in watched():
        _loop.call_soon_threadsafe(_mark, tk, kind)


def _mark(tk: str, kind: str) -> None:
    for t, c in _open:
        if t == tk:
            c.kinds.add(kind)
            c.wake.set()


async def next_changes(c: Client, timeout: float) -> set[str]:
    """Return the kinds changed since the last call; empty after `timeout` seconds with none."""
    if not await time_et.set_within(c.wake, timeout):
        return set()
    c.wake.clear()
    kinds, c.kinds = c.kinds, set()
    return kinds
