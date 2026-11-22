"""The `tape` panel: the newest option trade prints of a ticker."""

from __future__ import annotations

import heapq
from typing import Literal, TypedDict

import live_market_plane as lmp
from app.options.order_flow.history import TapeRow, tape_row
from app.options.order_flow.state import prints
from state.level_store import published_levels

#: the most prints the `tape` panel shows
TAPE_ROWS = 100


class NoTape(TypedDict):
    """The `tape` panel's answer while the console has no tape of the ticker: why."""

    ticker: str
    available: Literal[False]
    rows: list[TapeRow]
    reason: str


class TapePanel(TypedDict):
    """The `tape` panel (tape): the newest prints as rows; with none, why."""

    available: bool
    rows: list[TapeRow]
    reason: str | None


def tape(ticker: str, now: float) -> TapePanel | NoTape:
    """Return the `tape` panel at `now`: the newest option trade prints of the ticker.

    The prints the console keeps of Schwab's LEVELONE_OPTIONS as the daemon pushes them (the
    live state's prints), of every contract of `ticker` the daemon
    streams (live_market_plane.held_option_symbols), merged newest trade first by Schwab's own
    trade time (TRADE_TIME_MILLIS, Schwab's data, not our receive order),
    prints of one trade time in the order received, a print Schwab sent no trade time with after
    every one that has one; capped at TAPE_ROWS across the merge, each with its contract's terms
    and open interest from the chain record and its premium (history.tape_row). No aggressor
    side. `ticker` is the levels' own key.
    """
    held = published_levels(ticker)
    symbols = [] if held is None else lmp.held_option_symbols(held.contracts, now)
    if held is None or not symbols:
        return {
            "ticker": ticker,
            "available": False,
            "rows": [],
            "reason": (
                "the console holds no chain of this ticker yet"
                if held is None
                else "the daemon streams no option contract of this ticker"
            ),
        }
    # the newest TAPE_ROWS of all the contracts' kept prints are picked first, and only those are
    # made rows: each contract's last TAPE_ROWS received are the ones looked at
    newest = heapq.nlargest(
        TAPE_ROWS,
        ((p, sym) for sym in symbols for p in reversed(prints(sym)[-TAPE_ROWS:])),
        key=lambda kept: (
            kept[0].time_millis is not None,
            kept[0].time_millis,
            kept[0].server_received_ts,
        ),
    )
    rows = [tape_row(sym, p, held.contracts[sym]) for p, sym in newest]
    return {
        "available": bool(rows),
        "rows": rows,
        "reason": None if rows else "no trade prints for these contracts since the console started",
    }
