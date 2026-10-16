"""Schwab -> the key levels. A price that has stopped marks the levels, and the wall stays."""
from __future__ import annotations

import time

import live_market_plane as lmp
import server as srv
from tests.feed_live_helper import mark_feed_live


def test_a_down_price_marks_the_levels_and_the_wall_stays():
    """The chain is current, so the levels are not stale. The equity feed is down, so the rail
    is told the price they were built from has stopped. The wall is the last one published."""
    tk = "ZZLVSPOT"
    now = time.time()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": tk, "call_wall": 586.0, "spot": 583.41, "computed_ts_utc": now,
        }
    try:
        down = srv.get_terrain(ticker=tk)
        mark_feed_live(tk)
        live = srv.get_terrain(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp.record_feed_down()
    assert down["call_wall"] == live["call_wall"] == 586.0
    assert down["levels_stale"] is False
    assert down["spot_feed_live"] is False
    assert down["spot_outage"].startswith("Schwab LEVELONE_EQUITIES feed down during ")
    assert live["spot_feed_live"] is True
    assert live["spot_outage"] is None
    assert live["levels_stale"] is False
