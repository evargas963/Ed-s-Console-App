"""The Trade Desk forces are the two-day capture diff.

Fewer than two market days, or no
published levels, leaves each number absent. The producer attaches no sentence.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET with Schwab's
underlying price (tests/real_chains.py): one capture day.
"""

from __future__ import annotations

import server
from option_contract import read_chain
from tests.real_chains import CRWD


def test_forces_before_two_capture_days_are_absent():
    one = [
        {
            "et_date": CRWD.now.date().isoformat(),
            "spot": CRWD.spot,
            "contracts": read_chain(CRWD.chain),
            "ts_utc": CRWD.now.timestamp(),
        }
    ]
    forces = server._forces_from_captures("CRWD", one)
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
    body = server.forces("ZZNOFORCES")
    assert body["doi_below"] is None and body["charm_above"] is None
    assert "reason" not in body
