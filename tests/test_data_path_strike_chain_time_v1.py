"""Schwab -> the GEX-by-strike badge. The chain's time stands beside the chain's age."""

from __future__ import annotations

import server as srv
from option_contract import read_chain
from tests.real_chains import CRWD


def test_the_strike_panel_carries_the_chain_time():
    """The per-strike rows' time is the newest Schwab value in them: the chain they were built
    from when nothing was pushed since. The badge shows that instant beside the age. CRWD's
    real chain, published by the one producer (_publish_levels) as chain time 1790380799.830.
    """
    tk = "ZZSTRIKETIME"
    fetched = 1790380799.830
    try:
        srv._publish_levels(
            tk, read_chain(CRWD.chain), fetched, chain_spot=(CRWD.spot, fetched), now=CRWD.now
        )
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
