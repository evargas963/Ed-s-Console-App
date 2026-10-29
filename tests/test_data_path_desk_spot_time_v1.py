"""Schwab -> the trade desk. The Right Now spot carries Schwab's trade time."""
from __future__ import annotations

from datetime import datetime

import live_market_plane as lmp
import live_price_rows
import server
from app.options.order_flow import streaming as ofs
from time_et import ET


def test_the_desk_spot_carries_schwabs_trade_time_when_the_feed_is_down():
    """Friday 2026-10-02 11:00 ET. The desk's spot is Schwab's last trade, and the time beside
    it is that trade's time. The feed being down does not remove either."""
    at = datetime(2026, 10, 2, 11, 0, tzinfo=ET).timestamp()
    lmp.record_from_level_one_equity(
        "SPY", {"LAST_PRICE": 767.39, "TRADE_TIME_MILLIS": int(at * 1000)}, received_ts=at)
    ofs._price_rows["SPY"] = live_price_rows.price_row("SPY", at)
    try:
        body = server.levels_payload("SPY", "1", datetime.fromtimestamp(at, ET))
    finally:
        ofs._price_rows.pop("SPY", None)
        lmp.record_feed_down()
    assert body["spot"] == 767.39
    assert body["spot_time_ct"] == "Fri 10/02 10:00 AM CT"
    assert body["spot_as_of_ts_utc"] == at
