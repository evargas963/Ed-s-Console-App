"""Schwab -> the desk map. The chain's time stands beside the chain's age."""
from __future__ import annotations

import server as srv


def test_the_terrain_carries_the_chain_time():
    """computed_ts_utc is the chain the levels were built from. The desk map shows that
    instant beside the age, and the wall stays."""
    tk = "ZZCHAINTIME"
    fetched = 1790380799.830
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": tk, "call_wall": 586.0, "spot": 583.41, "computed_ts_utc": fetched,
        }
    try:
        body = srv.get_terrain(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
    assert body["call_wall"] == 586.0
    assert body["levels_time_ct"] == "Fri 09/25 06:59 PM CT"
