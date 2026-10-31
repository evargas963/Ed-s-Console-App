"""A side's charm with a contract not known is unknown, never the sum of the rest. NFLX's captured
calls of 2027-12-17 and 2028-01-21 at $3: Schwab sent their volatility as -999, open interest
known."""

from __future__ import annotations

from terrain_engine import compute_terrain
from tests.real_chains import NFLX


def test_a_contract_schwab_sent_no_volatility_leaves_its_side_and_net_unknown():
    snap = compute_terrain(NFLX.ticker, NFLX.chain, NFLX.spot, now=NFLX.now)
    bucket = snap.charm_by_strike[3.0]
    assert bucket["call_charm"] is None
    assert bucket["net_charm"] is None
    assert isinstance(bucket["put_charm"], float)
