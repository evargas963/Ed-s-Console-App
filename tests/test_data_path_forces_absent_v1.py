"""The Trade Desk forces are the chain now against the prior day's close capture.

No prior day's close captured, or no published levels, leaves each number absent. The producer
attaches no sentence.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET with Schwab's
underlying price (tests/real_chains.py): one capture day.
"""

from __future__ import annotations

import server
from option_contract import read_chain
from push import forces as push_forces
from state import level_store
from tests.real_chains import CRWD


def test_forces_with_no_prior_day_captured_are_absent():
    one = [
        {
            "et_date": CRWD.now.date().isoformat(),
            "spot": CRWD.spot,
            "spot_ts": CRWD.now.timestamp(),
            "basis": "",
            "contracts": read_chain(CRWD.chain),
            "ts_utc": CRWD.now.timestamp(),
        }
    ]
    try:
        server._publish_levels("CRWD", captures=one, now=CRWD.now)
        levels = level_store.published_levels("CRWD")
        assert levels is not None
        forces = levels.forces
    finally:
        with level_store._lock:
            level_store._levels.pop("CRWD", None)
    assert forces["available"] is False
    assert (
        forces["doi_below"],
        forces["doi_above"],
        forces["dex_below_dollars"],
        forces["dex_above_dollars"],
        forces["charm_below"],
        forces["charm_above"],
    ) == (None, None, None, None, None, None)
    assert "reason" not in forces


def test_forces_before_levels_are_published_are_absent():
    body = push_forces.forces("ZZNOFORCES")
    assert body["doi_below"] is None and body["charm_above"] is None
    assert "reason" not in body
