"""compute_terrain(now=...) prices EVERY book at that one instant -- vanna included.

MEASURED 2026-09-25: the same stored SPY chain run twice with the same `now`, 3 s apart,
gave two different net vanna figures (6,975,952,365.89 vs 6,975,877,192.65): the exposure
book behind the vanna aggregate priced time-to-expiry at the wall clock, ignoring `now` -- and a
stored chain whose expiry had already passed read as ZERO vanna on replay.

Real data: TSLA's complete 2026-10-09 chain captured 2026-10-07 12:32 ET (tests/real_chains.py).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from terrain_engine import compute_terrain
from tests.real_chains import TSLA


def _real_chain():
    chain = TSLA.chain
    expiry = datetime.fromisoformat(chain[0]["expirationDate"].replace("Z", "+00:00"))
    strikes = sorted(float(c["strikePrice"]) for c in chain)
    return chain, expiry, strikes[len(strikes) // 2]


def test_the_same_chain_at_the_same_instant_gives_the_same_vanna():
    chain, expiry, spot = _real_chain()
    now = expiry - timedelta(days=1)
    a = compute_terrain("TSLA", chain, spot, now=now).vanna_agg
    time.sleep(1.5)
    b = compute_terrain("TSLA", chain, spot, now=now).vanna_agg
    assert a is not None and a == b, (a, b)
    # a replayed chain is priced at ITS instant: before the fix, a stored chain whose expiry had
    # passed by the wall clock got T <= 0 for every contract and read as zero vanna
    assert a["net_vanna_shares_per_volpt"] != 0, a


def test_the_valuation_instant_reaches_the_vanna_book():
    chain, expiry, spot = _real_chain()
    early = compute_terrain("TSLA", chain, spot, now=expiry - timedelta(days=2)).vanna_agg
    late = compute_terrain("TSLA", chain, spot, now=expiry - timedelta(hours=8)).vanna_agg
    assert early is not None and late is not None
    assert early != late, "vanna must be priced at the given instant, not the wall clock"
