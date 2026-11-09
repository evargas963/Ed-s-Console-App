"""Schwab -> the desk map. The chain's time stands beside the chain's age."""

from __future__ import annotations

import server as srv
from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.real_chains import CRWD


def test_the_levels_time_has_one_producer_the_chains_fetch_and_the_calculator_reads_no_clock():
    """computed_ts_utc is the publication's to set, from the chain it was given.

    That is server's levels producer: the chain's fetch time. The calculator stamps none of its
    own: it takes `now` and reads no clock (SHAPE step 2; rule 3, one producer).
    """
    snap = compute_terrain("ZZCHAINTIME", read_chain(CRWD.chain), CRWD.spot, now=CRWD.now)
    assert snap.call_wall is not None
    assert snap.computed_ts_utc is None


def test_the_terrain_carries_the_chain_time():
    """The levels' time is the newest Schwab value in them.

    That is the chain they were built from when nothing was pushed since. The desk map shows that
    instant beside the age, and the wall stays. CRWD's real chain, published by the one producer
    (_publish_levels) as chain time 1790380799.830.
    """
    tk = "ZZCHAINTIME"
    fetched = 1790380799.830
    published = compute_terrain(tk, read_chain(CRWD.chain), CRWD.spot, now=CRWD.now).to_dict()
    assert published["call_wall"] is not None
    try:
        srv._publish_levels(
            tk, read_chain(CRWD.chain), fetched, chain_spot=(CRWD.spot, fetched), now=CRWD.now
        )
        body = srv.terrain(tk, fetched, {})
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
    assert body["call_wall"] == published["call_wall"]
    assert body["levels_time_ct"] == "Fri 09/25 06:59 PM CT"
