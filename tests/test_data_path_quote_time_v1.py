"""Schwab -> the price row. The quote time stays on the row when the feed is down.

Real data: SPY's LEVELONE_EQUITIES message of 2026-10-23 15:59:01 ET as Schwab sent it
(real_spy_level_one_2026_10_23.json): LAST_PRICE 760.07, QUOTE_TIME_MILLIS and
TRADE_TIME_MILLIS both in that minute, 02:59 PM CT.
"""

from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import time_et
from tests.feed_live_helper import mark_feed_live

_SENT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_spy_level_one_2026_10_23.json").read_text(
        encoding="utf-8"
    )
)["messages"][1]


def test_a_down_feed_keeps_schwabs_quote_time_and_trade_time():
    """QUOTE_TIME and TRADE_TIME are on the row the page paints.

    A feed that stops does not remove them.
    """
    item = _SENT["item"]
    mark_feed_live("SPY")
    lmp._by_ticker.pop("SPY", None)
    lmp._fields_by_ticker.pop("SPY", None)
    lmp.record_from_level_one_equity("SPY", item, received_ts=_SENT["ts_recv"])
    try:
        live = live_price_rows.price_row("SPY", time_et.now())
        lmp.record_feed_down()
        down = live_price_rows.price_row("SPY", time_et.now())
    finally:
        lmp.record_feed_down()
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
    assert live["trade_time_ct"] == live["quote_time_ct"] == "Fri 10/23 02:59 PM CT"
    assert down["spot"] == item["LAST_PRICE"]
    assert down["trade_time_ct"] == down["quote_time_ct"] == "Fri 10/23 02:59 PM CT"
    assert down["feed_live"] is False
