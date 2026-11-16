"""The `tape` panel: the newest option trade prints of a ticker."""

from __future__ import annotations

import heapq
from typing import Any

import live_market_plane as lmp
from app.options.order_flow.history import recent_prints, tape_row
from app.options.order_flow.state import get_content_for_symbol
from l1_trade_observation import canonical_tape_prints
from push.answers import unavailable
from state.level_store import published_levels

#: the most prints the `tape` panel shows
TAPE_ROWS = 100


def tape(ticker: str, now: float) -> dict[str, Any]:
    """Return the `tape` panel at `now`: the newest option trade prints of the ticker.

    The prints the console builds from Schwab's LEVELONE_OPTIONS as the daemon pushes them
    (the live state's prints, history.recent_prints), of every contract of `ticker` the daemon
    streams (live_market_plane.held_option_symbols), merged newest trade first by Schwab's own
    trade time (TRADE_TIME_MILLIS; operator 2026-11-12: "yes we should use schwab's data"),
    prints of one trade time in the order received, a print Schwab sent no trade time with after
    every one that has one; capped at TAPE_ROWS across the merge, each with its contract's terms
    and open interest from the chain record and its premium (history.tape_row). No aggressor
    side. `ticker` is the levels' own key.
    """
    held = published_levels(ticker)
    if held is None:
        return unavailable(ticker, "the console holds no chain of this ticker yet", rows=[])
    symbols = lmp.held_option_symbols(held.contracts, now)
    if not symbols:
        return unavailable(ticker, "the daemon streams no option contract of this ticker", rows=[])
    # the newest TAPE_ROWS of all the contracts' kept prints are picked first, and only those are
    # made rows: each contract's last TAPE_ROWS received are the ones looked at
    newest = heapq.nlargest(
        TAPE_ROWS,
        (
            (p, sym)
            for sym in symbols
            for p in reversed(canonical_tape_prints(get_content_for_symbol(sym))[-TAPE_ROWS:])
        ),
        key=lambda kept: (
            kept[0]["time_millis"] is not None,
            kept[0]["time_millis"],
            kept[0]["server_received_ts"],
        ),
    )
    rows = [tape_row(recent_prints(sym, [p], 1)[0], held.contracts[sym]) for p, sym in newest]
    return {
        "available": bool(rows),
        "rows": rows,
        "reason": None if rows else "no trade prints for these contracts since the console started",
    }
