"""Schwab -> the key levels. A price that has stopped marks the levels, and the wall stays."""
from __future__ import annotations

from datetime import datetime

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server as srv
from terrain_engine import compute_terrain
from tests.feed_live_helper import RTH_INSTANT, mark_feed_live, publish_daemon_rows
from time_et import ET
from tests.real_chains import CRWD


def test_a_down_price_marks_the_levels_and_the_wall_stays():
    """The chain is current, so the levels are not stale. The equity feed is down, so the rail
    is told the price they were built from has stopped. The wall is the last one published
    (CRWD's real chain). Served in regular hours (RTH_INSTANT)."""
    tk = "ZZLVSPOT"
    now = RTH_INSTANT
    at = datetime.fromtimestamp(now, ET)
    published = compute_terrain(tk, [dict(c) for c in CRWD.chain], CRWD.spot, now=CRWD.now).to_dict()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = published | {"computed_ts_utc": now}
    try:
        down = srv.terrain_answer(tk, at)
        mark_feed_live(tk, now=now)
        publish_daemon_rows(tk, now=now)                          # the daemon's price row, its verdict LIVE
        live = srv.terrain_answer(tk, at)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp.record_feed_down()
    assert down["call_wall"] == live["call_wall"] == published["call_wall"] is not None
    assert down["levels_state"] == "LIVE"
    assert (down["spot_feed_live"], down["spot_feed_label"]) == (False, "OFFLINE")
    assert down["spot_outage"].startswith("Schwab LEVELONE_EQUITIES feed down during ")
    assert (live["spot_feed_live"], live["spot_feed_label"]) == (True, "LIVE")
    assert live["spot_outage"] is None
    assert live["levels_state"] == "LIVE"
