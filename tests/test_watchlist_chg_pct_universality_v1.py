"""The streamed percent change (NET_CHANGE_PERCENT) on the price row, the same rule for every
ticker: Schwab's value as sent, 0 a value, its feed live."""
from __future__ import annotations

import time

import live_market_plane as lmp
import live_price_rows
from tests.feed_live_helper import mark_feed_down, mark_feed_live


def test_the_price_row_serves_schwabs_percent_change_as_sent():
    mark_feed_live("ZZCHG", "ZZNEVER")
    try:
        lmp.record_from_level_one_equity("ZZCHG", {"LAST_PRICE": 10.0, "NET_CHANGE_PERCENT": 3.33},
                                         received_ts=time.time())
        assert live_price_rows.price_row("ZZCHG")["chg_pct"] == 3.33
        lmp.record_from_level_one_equity("ZZCHG", {"NET_CHANGE_PERCENT": 0.0}, received_ts=time.time())
        assert live_price_rows.price_row("ZZCHG")["chg_pct"] == 0.0          # a flat day is a value
        assert live_price_rows.price_row("ZZNEVER")["chg_pct"] is None      # Schwab sent nothing
    finally:
        mark_feed_down()
