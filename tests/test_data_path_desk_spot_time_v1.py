"""Schwab -> the trade desk. The Right Now spot carries Schwab's trade time.

Real data: SPY's LEVELONE_EQUITIES message of 2026-10-23 15:59:01 ET as Schwab sent it
(real_spy_level_one_2026_10_23.json): LAST_PRICE 760.07, traded at 15:59:01.034 ET.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import server
from time_et import ET

_SENT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_spy_level_one_2026_10_23.json").read_text(
        encoding="utf-8"
    )
)["messages"][1]


def test_the_desk_spot_carries_schwabs_trade_time_when_the_feed_is_down():
    """Friday 2026-10-23, a minute before the close.

    The desk's spot is Schwab's last trade, and the time beside it is that trade's time. The
    feed being down does not remove either.
    """
    item = _SENT["item"]
    at = item["TRADE_TIME_MILLIS"] / 1000
    lmp._by_ticker.pop("SPY", None)
    lmp._fields_by_ticker.pop("SPY", None)
    lmp.record_from_level_one_equity("SPY", item, received_ts=_SENT["ts_recv"])
    try:
        body = server.levels_payload("SPY", "1", datetime.fromtimestamp(_SENT["ts_recv"], ET))
    finally:
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
        lmp.record_feed_down()
    assert body["spot"] == item["LAST_PRICE"] == 760.07
    assert body["spot_time_ct"] == "Fri 10/23 02:59 PM CT"
    assert body["spot_as_of_ts_utc"] == at
