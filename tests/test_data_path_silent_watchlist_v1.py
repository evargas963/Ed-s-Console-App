"""Schwab -> the watchlist. A missing daemon heartbeat keeps the last list and says it is not live."""
from __future__ import annotations

import time

import live_market_plane as lmp
import server


def test_a_missing_heartbeat_keeps_the_last_watchlist():
    """The daemon reported SPY and TSLA, then the heartbeat is gone: the watchlist route still
    serves those tickers and says the list is not live."""
    now = time.time()
    lmp.record_feed_down()
    with lmp._lock:
        lmp._feed["watchlist"] = None
    try:
        lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True,
                                   "watchlist": ["SPY", "TSLA"]})
        live = server.get_watchlist()
        lmp.record_feed_down()
        down = server.get_watchlist()
    finally:
        lmp.record_feed_down()
        with lmp._lock:
            lmp._feed["watchlist"] = None
    assert live["tickers"] == ["SPY", "TSLA"] and live["live"] is True
    assert down["tickers"] == ["SPY", "TSLA"] and down["live"] is False
