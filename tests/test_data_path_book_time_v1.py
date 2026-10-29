"""Schwab -> the book panel. The quote time and the book time stay when the feed is down."""

from __future__ import annotations

import time

import live_market_plane as lmp
import live_price_rows
import server
from app.options.order_flow import state as of_state
from app.options.order_flow import streaming as ofs
from tests.feed_live_helper import mark_feed_live

_TK = "ZZBKTIME"
_WHEN = 1790380799830  # Fri 09/25 06:59 PM CT


def test_a_down_feed_keeps_schwabs_quote_time_and_book_time_on_the_book():
    """QUOTE_TIME and BOOK_TIME are on the book the page paints. A feed that stops does not
    remove them, and the last bid stays."""
    mark_feed_live(_TK)
    lmp.record_from_level_one_equity(
        _TK,
        {
            "LAST_PRICE": 772.04,
            "BID_PRICE": 772.00,
            "ASK_PRICE": 772.08,
            "QUOTE_TIME_MILLIS": _WHEN,
            "TRADE_TIME_MILLIS": _WHEN,
        },
        received_ts=time.time(),
    )
    of_state.push_book(
        _TK,
        {
            "BIDS": [{"BID_PRICE": 772.00, "TOTAL_VOLUME": 10}],
            "ASKS": [{"ASK_PRICE": 772.08, "TOTAL_VOLUME": 8}],
            "BOOK_TIME": _WHEN,
        },
        "NASDAQ_BOOK",
    )
    try:
        lmp.record_feed_down()
        ofs._price_rows[_TK] = live_price_rows.price_row(_TK, time.time())
        body = server.order_flow_microstructure(_TK, "NASDAQ_BOOK", time.time())
    finally:
        ofs._price_rows.pop(_TK, None)
        of_state._LIVE_STATE._book.pop(_TK, None)
        lmp.record_feed_down()
    assert body["top_of_book"]["bid"] == 772.00
    assert body["top_outage"] is not None
    assert body["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert body["book_time_ct"] == "Fri 09/25 06:59 PM CT"
