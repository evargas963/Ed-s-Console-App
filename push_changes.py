"""The console's push: which of a ticker's served values changed (the page reloads what changed),
and the one answer to "which ticker is on screen".

Every open page holds one connection (/api/changes) on its ticker. The connections are kept in the
order they opened; the ticker on screen is the newest one still open. Everything that follows the
ticker on screen -- the books streamed, the chain fetched first, the option contract -- listens
here (`on_screen_change`) and is told on the event loop when it changes. Its changed values
(`changed`) reach the pages and the listeners of `on_change` on the event loop too.
"""
from __future__ import annotations

import asyncio

LEVELS, CHAIN, FLOW, LIQUIDITY = "levels", "chain", "flow", "liquidity"

_loop: asyncio.AbstractEventLoop | None = None
#: (ticker, connection) of every open page, oldest first
_open: "list[tuple[str, Client]]" = []
#: the listeners, each by its function's module and name: one per function, so a module that
#: registers again replaces its own
_screen_listeners: dict = {}      # fn(old, new) when the ticker on screen changes
_change_listeners: dict = {}      # fn(ticker, kind) when a value of an open ticker changes


class Client:
    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.wake = asyncio.Event()


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def on_screen_change(fn) -> None:
    _screen_listeners[f"{fn.__module__}.{fn.__qualname__}"] = fn


def on_change(fn) -> None:
    _change_listeners[f"{fn.__module__}.{fn.__qualname__}"] = fn


def on_screen() -> str | None:
    """The ticker on screen: the newest open page's; None when no page is open. Read from any
    thread: one slice of the list (which the event loop changes) is the whole read."""
    newest = _open[-1:]
    return newest[0][0] if newest else None


def watched() -> list[str]:
    """Every ticker an open page shows, on any workspace."""
    return list(dict.fromkeys(tk for tk, _c in list(_open)))


def subscribe(tk: str, c: "Client | None" = None) -> Client:
    """A page opened on `tk` (on the event loop), as connection `c` (a new one when not given:
    a caller that must close it whatever happens creates it first)."""
    c = Client() if c is None else c
    old = on_screen()
    _open.append((tk, c))
    _screen_moved(old)
    return c


def unsubscribe(tk: str, c: Client) -> None:
    """The page closed (on the event loop)."""
    old = on_screen()
    _open[:] = [(t, x) for t, x in _open if x is not c]
    _screen_moved(old)


def _screen_moved(old: str | None) -> None:
    new = on_screen()
    if new != old:
        for fn in list(_screen_listeners.values()):
            fn(old, new)


def changed(tk: str, kind: str) -> None:
    """Callable from any thread."""
    if _loop is not None and tk in watched():
        _loop.call_soon_threadsafe(_mark, tk, kind)


def _mark(tk: str, kind: str) -> None:
    for t, c in _open:
        if t == tk:
            c.kinds.add(kind)
            c.wake.set()
    for fn in list(_change_listeners.values()):
        fn(tk, kind)


async def next_changes(c: Client, timeout: float) -> set[str]:
    """The kinds changed since the last call; empty after `timeout` seconds with none."""
    try:
        await asyncio.wait_for(c.wake.wait(), timeout)
    except asyncio.TimeoutError:
        return set()
    c.wake.clear()
    kinds, c.kinds = c.kinds, set()
    return kinds
