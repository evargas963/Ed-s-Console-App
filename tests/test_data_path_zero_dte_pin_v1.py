"""The 0DTE gamma pin: absolute gamma of the same-day expiry's book alone, served beside the
whole-book Abs Γ on every ticker's terrain and drawn among its key levels."""
from __future__ import annotations

import server
from terrain_engine import compute_terrain
from tests.real_chains import MRVL, SPY_0DTE


def test_the_0dte_pin_is_the_same_day_books_absolute_gamma_and_absent_with_why_without_one():
    """SPY 2026-10-07 12:32 ET, its same-day expiry only: the pin is that book's absolute gamma
    strike. MRVL 2026-10-07 10:31 ET, all 20 expiries, the nearest two days out: no pin, the
    reason named, while the whole-book Abs Γ stands."""
    spy = compute_terrain("SPY", SPY_0DTE.chain, SPY_0DTE.spot, now=SPY_0DTE.now).to_dict()
    assert spy["zero_dte_abs_gamma_strike"] == spy["absolute_gamma_strike"] == 778.0
    assert spy["zero_dte_abs_gamma_reason"] is None

    mrvl = compute_terrain("MRVL", MRVL.chain, MRVL.spot, now=MRVL.now).to_dict()
    assert mrvl["absolute_gamma_strike"] is not None
    assert mrvl["zero_dte_abs_gamma_strike"] is None
    assert mrvl["zero_dte_abs_gamma_reason"] == "no same-day expiry in the chain"

    assert ("zero_dte_abs_gamma_strike", "0DTE Γ pin") in server.GAMMA_LEVELS
