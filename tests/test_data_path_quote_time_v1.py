"""Schwab -> the price row. The quote time stays on the row when the feed is down."""
from __future__ import annotations

import time

import live_price_rows
from tests.feed_live_helper import mark_feed_live
import live_market_plane as lmp


def test_a_down_feed_keeps_schwabs_quote_time_and_trade_time():
    """QUOTE_TIME and TRADE_TIME are on the row the page paints. A feed that stops does not
    remove them."""
    mark_feed_live("SPY")
    lmp.record_from_level_one_equity(
        "SPY",
        {"LAST_PRICE": 772.04, "BID_PRICE": 772.00, "ASK_PRICE": 772.08,
         "TRADE_TIME_MILLIS": 1790380799830, "QUOTE_TIME_MILLIS": 1790380799830},
        received_ts=time.time(),
    )
    try:
        live = live_price_rows.price_row("SPY", time.time())
        lmp.record_feed_down()
        down = live_price_rows.price_row("SPY", time.time())
    finally:
        lmp.record_feed_down()
    assert live["trade_time_ct"] == live["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert down["spot"] == 772.04
    assert down["trade_time_ct"] == down["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert down["feed_live"] is False
