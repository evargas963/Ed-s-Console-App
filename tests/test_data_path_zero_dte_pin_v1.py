"""The 0DTE gamma pin: absolute gamma of the same-day expiry's book alone, served beside the
whole-book Abs Γ on every ticker's terrain and drawn among its key levels. The same day is the
market's session date (time_et.market_session_date), never the chain's day count.

Real data: SPY's, QQQ's and IWM's last capture of 2026-10-08 (tests/real_chains.py CLOSE_1008),
the chain the console holds into Friday 2026-10-09 until the daemon's first fetch: its 10-09
contracts say daysToExpiration 1."""
from __future__ import annotations

from datetime import datetime

import pytest

import server
from math_exposure_core import (compute_exposures_by_strike, compute_zero_dte_gamma_share, exposure_books,
                                merge_exposure_books, pick_pin_and_strength)
from terrain_engine import compute_terrain
from tests.real_chains import CLOSE_1008, MRVL, SPY_0DTE
from time_et import ET


@pytest.mark.parametrize("tk", ["SPY", "QQQ", "IWM"])
def test_fridays_0dte_pin_is_the_10_09_expirys_absolute_gamma_on_the_chain_held_from_thursday(tk):
    """Friday 2026-10-09 08:00 ET (Pre-Market): the chain held is Thursday's last capture, whose
    10-09 contracts say daysToExpiration 1. Today's expiry is 10-09 by the session date, so the
    0DTE pin is the absolute-gamma strike of the 10-09 contracts alone, and the 0DTE share is of
    that same book."""
    contracts, spot = CLOSE_1008[tk].chain, CLOSE_1008[tk].spot
    now = datetime(2026, 10, 9, 8, 0, tzinfo=ET)
    expiring = [c for c in contracts if c["expirationDate"].startswith("2026-10-09")]
    assert {c["daysToExpiration"] for c in expiring} == {1}
    today, _ = compute_exposures_by_strike(expiring, spot=spot, now=now)
    expected = pick_pin_and_strength(today, sorted(today))[0]
    assert expected is not None
    snap = compute_terrain(tk, contracts, spot, now=now)
    assert snap.zero_dte_abs_gamma_strike == expected
    whole, _ = merge_exposure_books(exposure_books(contracts, spot=spot, now=now).values())
    assert snap.zero_dte_gamma_share_pct == compute_zero_dte_gamma_share(whole, today)


def test_the_0dte_pin_is_the_same_day_books_absolute_gamma_and_absent_without_one():
    """SPY 2026-10-07 12:32 ET, its same-day expiry only: the pin is that book's absolute gamma
    strike. MRVL 2026-10-07 10:31 ET, all 20 expiries, the nearest two days out: no pin, with no
    reason served, while the whole-book Abs Γ stands."""
    spy = compute_terrain("SPY", SPY_0DTE.chain, SPY_0DTE.spot, now=SPY_0DTE.now).to_dict()
    assert spy["zero_dte_abs_gamma_strike"] == spy["absolute_gamma_strike"] == 778.0

    mrvl = compute_terrain("MRVL", MRVL.chain, MRVL.spot, now=MRVL.now).to_dict()
    assert mrvl["absolute_gamma_strike"] is not None
    assert mrvl["zero_dte_abs_gamma_strike"] is None
    assert "zero_dte_abs_gamma_reason" not in mrvl

    assert ("zero_dte_abs_gamma_strike", "Abs Γ 0DTE") in server.GAMMA_LEVELS


def test_on_thursdays_own_close_the_held_chain_has_no_0dte_pin():
    """At Thursday's capture instant the session is 2026-10-08; the chain holds no 10-08 expiry, so
    there is no 0DTE pin and no 0DTE share, while the whole-book Abs Γ stands."""
    spy = CLOSE_1008["SPY"]
    snap = compute_terrain("SPY", spy.chain, spy.spot, now=spy.now)
    assert snap.absolute_gamma_strike is not None
    assert snap.zero_dte_abs_gamma_strike is None and snap.zero_dte_gamma_share_pct == 0.0
