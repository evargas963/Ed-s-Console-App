"""Schwab -> the desk map. The chain's time stands beside the chain's age."""

from __future__ import annotations

import server as srv
from terrain_engine import compute_terrain
from tests.real_chains import CRWD


def test_the_terrain_carries_the_chain_time():
    """computed_ts_utc is the chain the levels were built from. The desk map shows that
    instant beside the age, and the wall stays. CRWD's real chain, published as chain time
    1790380799.830."""
    tk = "ZZCHAINTIME"
    fetched = 1790380799.830
    published = compute_terrain(
        tk, [dict(c) for c in CRWD.chain], CRWD.spot, now=CRWD.now
    ).to_dict()
    assert published["call_wall"] is not None
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = published | {"computed_ts_utc": fetched}
    try:
        body = srv.get_terrain(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
    assert body["call_wall"] == published["call_wall"]
    assert body["levels_time_ct"] == "Fri 09/25 06:59 PM CT"
