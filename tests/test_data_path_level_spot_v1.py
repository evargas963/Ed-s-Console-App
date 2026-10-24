"""Schwab -> the key levels. A price that has stopped marks the levels, and the wall stays."""
from __future__ import annotations

import time

import live_market_plane as lmp
import server as srv
from terrain_engine import compute_terrain
from tests.feed_live_helper import mark_feed_live
from tests.real_chains import CRWD


def test_a_down_price_marks_the_levels_and_the_wall_stays():
    """The chain is current, so the levels are not stale. The equity feed is down, so the rail
    is told the price they were built from has stopped. The wall is the last one published
    (CRWD's real chain)."""
    tk = "ZZLVSPOT"
    now = time.time()
    published = compute_terrain(tk, [dict(c) for c in CRWD.chain], CRWD.spot, now=CRWD.now).to_dict()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = published | {"computed_ts_utc": now}
    try:
        down = srv.get_terrain(ticker=tk)
        mark_feed_live(tk)
        live = srv.get_terrain(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp.record_feed_down()
    assert down["call_wall"] == live["call_wall"] == published["call_wall"] is not None
    assert down["levels_stale"] is False
    assert down["spot_feed_live"] is False
    assert down["spot_outage"].startswith("Schwab LEVELONE_EQUITIES feed down during ")
    assert live["spot_feed_live"] is True
    assert live["spot_outage"] is None
    assert live["levels_stale"] is False
