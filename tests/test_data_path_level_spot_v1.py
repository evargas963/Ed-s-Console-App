"""Schwab -> the key levels. A price that has stopped marks the levels, and the wall stays."""

from __future__ import annotations

import live_price_rows
import server as srv
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from push import terrain as push_terrain
from state import level_store
from tests.feed_live_helper import RTH_INSTANT, mark_feed_down, mark_feed_live
from tests.real_chains import CRWD
from time_et import sessions


def test_a_down_price_marks_the_levels_and_the_wall_stays():
    """The chain is current, so the levels are not stale.

    The equity feed is down, so the rail is told the price they were built from has stopped:
    the levels' own mark, and the price row's verdict (one producer, which the page draws beside
    them; the terrain panel serves no copy of it). The wall is the last one published (CRWD's
    real chain, published by the one producer as fetched then, valued at its capture). Served in
    regular hours (RTH_INSTANT).
    """
    tk = "ZZLVSPOT"
    now = RTH_INSTANT
    published = compute_terrain(
        tk, read_chain(CRWD.chain), CRWD.spot, now=CRWD.now, sessions=sessions()
    ).to_dict()
    srv._publish_levels(tk, read_chain(CRWD.chain), now, chain_spot=(CRWD.spot, now), now=CRWD.now)
    try:
        mark_feed_live(tk, now=now)  # the daemon was running: its last round stands while down
        mark_feed_down()
        down = push_terrain.terrain(tk, now)
        down_row = live_price_rows.price_row(tk, now)
        mark_feed_live(tk, now=now)  # the daemon's price row, read at `now`: its verdict LIVE
        live = push_terrain.terrain(tk, now)
        live_row = live_price_rows.price_row(tk, now)
    finally:
        with level_store._lock:
            level_store._levels.pop(tk, None)
    assert down["call_wall"] == live["call_wall"] == published["call_wall"] is not None
    assert down["levels_state"] == "LIVE"
    assert (down_row["feed_live"], down["levels_mark"]) == (False, "OFFLINE")
    assert down["levels_mark_reason"].startswith("Schwab LEVELONE_EQUITIES feed down during ")
    assert (live_row["feed_live"], live["levels_mark"]) == (True, "LIVE")
    assert live["levels_mark_reason"] is None
    assert live["levels_state"] == "LIVE"
    assert not {"spot_text", "spot_time_ct", "spot_not_live_text"} & (down.keys() | live.keys())
