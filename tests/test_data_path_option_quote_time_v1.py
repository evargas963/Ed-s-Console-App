"""Schwab -> the Flow panel. A contract's quote time and book time stay when the feed is down."""
from __future__ import annotations

import time

import live_market_plane as lmp
import server
from app.options.order_flow import state as of_state

_SYM = "ZZOPT  261016C00100000"
_WHEN = 1790380799830  # Fri 09/25 06:59 PM CT


def test_a_down_feed_keeps_the_contracts_quote_time_and_book_time():
    """QUOTE_TIME_MILLIS stays on the option top, and BOOK_TIME stays on the book. The Flow
    panel still shows the last bid, with both times."""
    of_state.push_option_top(_SYM, {
        "BID_PRICE": 1.25, "ASK_PRICE": 1.40, "QUOTE_TIME_MILLIS": _WHEN,
    })
    of_state.push_book(_SYM, {
        "BIDS": [{"BID_PRICE": 1.25, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 1.40, "TOTAL_VOLUME": 8}],
        "BOOK_TIME": _WHEN,
    }, "OPTIONS_BOOK")
    try:
        lmp.record_feed_down()
        body = server.options_microstructure(_SYM, time.time())
    finally:
        of_state._LIVE_STATE._top.pop(_SYM, None)
        of_state._LIVE_STATE._book.pop(_SYM, None)
        lmp.record_feed_down()
    assert body["top_of_book"]["bid"] == 1.25
    assert body["top_outage"] is not None
    assert body["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert body["book_time_ct"] == "Fri 09/25 06:59 PM CT"
