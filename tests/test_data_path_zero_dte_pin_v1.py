"""The 0DTE gamma pin has one producer: the same-day absolute gamma, for every ticker."""

from __future__ import annotations

import server
from terrain_engine import compute_terrain
from tests.real_chains import MRVL, SPY_0DTE


def test_the_0dte_pin_has_one_producer():
    """SPY 2026-10-07 12:32 ET and MRVL 2026-10-07 10:31 ET. The pin is the same-day
    absolute gamma. The old listed-expiry pin is not a second field and not a levels row."""
    spy = compute_terrain("SPY", SPY_0DTE.chain, SPY_0DTE.spot, now=SPY_0DTE.now).to_dict()
    assert "zero_dte_abs_gamma_strike" not in spy
    assert spy["same_day"]["absolute_gamma_strike"] is not None

    mrvl = compute_terrain("MRVL", MRVL.chain, MRVL.spot, now=MRVL.now).to_dict()
    assert "zero_dte_abs_gamma_strike" not in mrvl
    assert mrvl["same_day"]["absolute_gamma_strike"] is not None
    assert mrvl["same_day"]["absolute_gamma_strike"] != mrvl["absolute_gamma_strike"]

    assert ("zero_dte_abs_gamma_strike", "0DTE Γ pin") not in server.GAMMA_LEVELS
