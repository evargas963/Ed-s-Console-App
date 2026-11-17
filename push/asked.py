"""What a page's panel asks for, read from its `params`: each a value the panel serves, or why not.

A value outside what the program serves raises ValueError, which the page's socket sends as the
panel's words (live_ui).
"""

from __future__ import annotations

from typing import Any

from calc.order_flow import BOOK_VENUES

#: the chart timeframes the levels' VWAP curve is served in (aggregate_vwap)
LEVEL_TIMEFRAMES = ("1", "3", "5", "15", "30", "60", "D")


def venue_asked(params: dict[str, Any]) -> str:
    """Return the Schwab book a panel's `params` name; another raises (the socket sends why)."""
    venue = params.get("venue")
    if venue not in BOOK_VENUES:
        raise ValueError(f"venue {venue!r} is not one of {', '.join(BOOK_VENUES)}")
    return venue


def tf_asked(params: dict[str, Any]) -> str:
    """Return the chart timeframe a panel's `params` name; another raises."""
    tf = params.get("tf")
    if tf not in LEVEL_TIMEFRAMES:
        raise ValueError(f"tf {tf!r} is not one of {', '.join(LEVEL_TIMEFRAMES)}")
    return tf
