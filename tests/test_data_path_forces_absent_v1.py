"""The Trade Desk forces are the two-day capture diff. Fewer than two market days, or no
published levels, leaves each number absent. The producer attaches no sentence."""
from __future__ import annotations

import json

import server


def test_forces_before_two_capture_days_are_absent():
    one = [{"et_date": "2026-09-28", "spot": 5.0, "contracts": [], "ts_utc": 1.0}]
    forces = server._forces_from_captures("ZZ", one)
    assert forces["available"] is False
    assert (forces["doi_below"], forces["doi_above"], forces["dex_below_dollars"],
            forces["dex_above_dollars"], forces["charm_below"], forces["charm_above"]) == (
                None, None, None, None, None, None)
    assert "reason" not in forces


def test_forces_before_levels_are_published_are_absent():
    body = json.loads(server.get_forces(ticker="ZZNOFORCES").body)
    assert body["doi_below"] is None and body["charm_above"] is None
    assert "reason" not in body
