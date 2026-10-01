"""The console's push: which of a ticker's served values changed. The page reloads what changed."""
from __future__ import annotations

import asyncio

LEVELS, CHAIN, FLOW = "levels", "chain", "flow"

_loop: asyncio.AbstractEventLoop | None = None
_clients: dict[str, list["Client"]] = {}


class Client:
    """One open push connection: the ticker's changes for one view (a page load)."""

    def __init__(self, view: str) -> None:
        self.view = view
        self.kinds: set[str] = set()
        self.wake = asyncio.Event()


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe(tk: str, view: str) -> Client:
    c = Client(view)
    _clients.setdefault(tk, []).append(c)
    return c


def unsubscribe(tk: str, c: Client) -> None:
    left = [x for x in _clients.get(tk, []) if x is not c]
    if left:
        _clients[tk] = left
    else:
        _clients.pop(tk, None)


def watched() -> list[str]:
    """The tickers a page has open now (an open push connection), on any workspace."""
    return list(_clients)


def view_open(view: str) -> bool:
    """Whether the view has a push connection open now, on any ticker. Callable from any thread."""
    return any(c.view == view for clients in list(_clients.values()) for c in clients)


def changed(tk: str, kind: str) -> None:
    """Callable from any thread."""
    if _loop is not None and tk in _clients:
        _loop.call_soon_threadsafe(_mark, tk, kind)


def _mark(tk: str, kind: str) -> None:
    for c in _clients.get(tk, []):
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
