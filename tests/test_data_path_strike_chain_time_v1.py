"""Schwab -> the GEX-by-strike badge. The chain's time stands beside the chain's age."""

from __future__ import annotations

import server as srv


def test_the_strike_panel_carries_the_chain_time():
    """computed_ts_utc is the chain the per-strike rows were built from. The badge shows
    that instant beside the age."""
    tk = "ZZSTRIKETIME"
    fetched = 1790380799.830
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": tk,
            "spot": 100.0,
            "computed_ts_utc": fetched,
            "_per_strike": {"all": [[100.0, 1.0, 2.0]], "near": [], "far": []},
        }
    try:
        body = srv.terrain_strikes_payload(tk, "auto", None, 0, fetched + 21)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
    assert body["levels_age_sec"] == 21
    assert body["levels_time_ct"] == "Fri 09/25 06:59 PM CT"
    # 2026-09-25 has no /markets answer held: the rows' verdict is NOT LIVE
    assert (body["levels_state"], body["levels_stale_reason"]) == (
        "NOT LIVE",
        "the market session is unknown",
    )
