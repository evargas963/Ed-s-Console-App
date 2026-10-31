"""A side's charm with a contract not known is unknown, never the sum of the rest. NFLX's captured
calls of 2027-12-17 and 2028-01-21 at $3: Schwab sent their volatility as -999, open interest
known."""

from __future__ import annotations

from datetime import datetime

import server
from math_levels import compute_charm_by_strike
from terrain_engine import compute_terrain
from tests.real_chains import NFLX
from time_et import ET


def test_a_contract_schwab_sent_no_volatility_leaves_its_side_and_net_unknown():
    snap = compute_terrain(NFLX.ticker, NFLX.chain, NFLX.spot, now=NFLX.now)
    bucket = snap.charm_by_strike[3.0]
    assert bucket["call_charm"] is None
    assert bucket["net_charm"] is None
    assert isinstance(bucket["put_charm"], float)


def test_an_expired_contract_with_no_volatility_has_no_charm_left():
    after_all = datetime(2028, 2, 1, 12, 0, tzinfo=ET)
    assert compute_charm_by_strike(NFLX.chain, NFLX.spot, now=after_all) == {}


def test_a_forces_side_with_a_strike_not_known_is_not_known():
    """NFLX at 68.76: the $3 strike is below the price, every strike above it known or absent."""
    prior = datetime(2026, 10, 6, 12, 0, tzinfo=ET)
    caps = [
        {
            "et_date": day.date().isoformat(),
            "spot": NFLX.spot,
            "contracts": NFLX.chain,
            "ts_utc": day.timestamp(),
        }
        for day in (NFLX.now, prior)
    ]
    snap = compute_terrain(NFLX.ticker, NFLX.chain, NFLX.spot, now=NFLX.now)
    forces = server._forces_from_captures(NFLX.ticker, caps, snap.charm_by_strike)
    assert forces["charm_below"] is None
    assert forces["charm_above"] is not None
