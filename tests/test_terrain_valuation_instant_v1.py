"""compute_terrain(now=...) prices EVERY book at that one instant -- vanna included.

MEASURED 2026-09-25: the same stored SPY chain run twice with the same `now`, 3 s apart,
gave two different net vanna figures (6,975,952,365.89 vs 6,975,877,192.65): the exposure
book behind the vanna aggregate priced time-to-expiry at the wall clock, ignoring `now` -- and a
stored chain whose expiry had already passed read as ZERO vanna on replay.

Real data: TSLA's complete 2026-10-09 chain captured 2026-10-07 12:32 ET (tests/real_chains.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.real_chains import TSLA


def _real_chain():
    chain = read_chain(TSLA.chain)
    expiry = datetime.fromisoformat(chain[0].expiration.replace("Z", "+00:00"))
    strikes = sorted(c.strike for c in chain)
    return chain, expiry, strikes[len(strikes) // 2]


def _vanna(chain, spot, now) -> float | None:
    """The terrain's vanna book at `now`: every strike's net vanna, per vol point, summed."""
    books = compute_terrain("TSLA", chain, spot, now=now).books
    nets = [b["net_vanna"] for book, _diag in books.values() for b in book.values()]
    return None if None in nets else sum(nets)


def test_the_same_chain_at_the_same_instant_gives_the_same_vanna():
    chain, expiry, spot = _real_chain()
    now = expiry - timedelta(days=1)
    a = _vanna(chain, spot, now)
    b = _vanna(chain, spot, now)
    assert a is not None and a == b, (a, b)
    # a replayed chain is priced at ITS instant: before the fix, a stored chain whose expiry had
    # passed by the wall clock got T <= 0 for every contract and read as zero vanna. The chain's
    # expiry is past by the wall clock, so any read of the clock in place of `now` shows here.
    assert a != 0, a


def test_the_valuation_instant_reaches_the_vanna_book():
    chain, expiry, spot = _real_chain()
    early = _vanna(chain, spot, expiry - timedelta(days=2))
    late = _vanna(chain, spot, expiry - timedelta(hours=8))
    assert early is not None and late is not None
    assert early != late, "vanna must be priced at the given instant, not the wall clock"
