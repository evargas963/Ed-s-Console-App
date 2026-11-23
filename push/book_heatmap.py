"""The `book_heatmap` panel: the depth heatmap of a ticker's Schwab book."""

from __future__ import annotations

from typing import Any

from app.options.order_flow.history import BOOKS_KEPT_SEC, BookHeatmap, book_heatmap_for_ticker
from push.answers import NotAvailable
from push.asked import venue_asked


def book_heatmap(ticker: str, params: dict[str, Any]) -> BookHeatmap | NotAvailable:
    """Return the `book_heatmap` panel: the depth heatmap of the ticker's Schwab book `venue`.

    history.book_heatmap_for_ticker bins the venue's recent books in the console's memory into a
    time x price grid over the newest `minutes`. The window ends at the newest book, never at
    the time of asking. A window not above 0, or longer than the books the console keeps
    (history.BOOKS_KEPT_SEC), raises.
    """
    minutes = params.get("minutes")
    # a number the page sent (JSON: an int or a float, never true or false), in the window kept
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int | float)
        or not 0 < minutes <= BOOKS_KEPT_SEC / 60
    ):
        raise ValueError(f"minutes {minutes!r} is not above 0 and at most {BOOKS_KEPT_SEC / 60:g}")
    return book_heatmap_for_ticker(ticker, venue_asked(params), minutes=minutes)
