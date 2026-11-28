"""Ground-truth sign lock for charm (RC-CHARM-SIGN).

OBSERVED (2026-07-25): compute_net_charm shipped charm_unit = -phi(d1)*d2/(2T) — the exact
NEGATIVE of calendar-time charm — so charm_direction was inverted ("buying" when dealer flow
was selling), disagreeing with the correct per-strike bs_charm path on 70-79% of real states.
It survived because the only "verification" checked ALGEBRA against a textbook formula, not
GROUND TRUTH. A sign this consequential (it feeds a displayed note + a model feature) must be
locked against an empirical derivative, so no future revision can silently flip it again.

VALIDATED: this finite-difference IS the ground truth — d(Delta)/dt as calendar time advances
(T shrinks) — computed independently of both implementations. The charm the terrain computes
(math_exposure_core.bs_charm_array) must match its sign for every moneyness, or the build fails.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pytest

from calc.math_exposure_core import (
    bs_charm_array,
    bs_vanna_array,
    compute_exposures_by_strike,
    schwab_iv_to_sigma,
)
from calc.math_levels import compute_charm_by_strike
from option_contract import read_chain
from tests.one_contract_greeks import charm, vanna
from tests.real_chains import MRVL, SPY_0DTE, SPY_FULL, delta_derivatives
from tests.shared_helpers import norm_cdf
from time_et import ET, option_close_product, sessions, time_to_expiry_years

SIGMA = 0.20
K = 100.0
# (label, spot, dte_days) — a NON-zero calendar-time charm is expected for each.
CASES = [
    ("slightITM", 101.0, 5),
    ("slightOTM", 99.0, 5),
    ("ITM", 105.0, 5),
    ("OTM", 95.0, 5),
    ("ATM", 100.0, 5),
    ("ITM_20DTE", 104.0, 20),
]


def _call_delta(spot: float, years: float) -> float:
    d1 = (math.log(spot / K) + 0.5 * SIGMA * SIGMA * years) / (SIGMA * math.sqrt(years))
    return norm_cdf(d1)


def _fd_calendar_charm(spot: float, dte: int) -> float:
    """Ground truth: (delta(T - 1 day) - delta(T)) / dt — the day passes, T shrinks."""
    years = dte / 365.0
    dt = 1.0 / 365.0
    return (_call_delta(spot, years - dt) - _call_delta(spot, years)) / dt


@pytest.mark.parametrize("label,spot,dte", CASES)
def test_bs_charm_sign_matches_finite_difference(label, spot, dte):
    fd = _fd_calendar_charm(spot, dte)
    bs = charm(spot, K, dte / 365.0, SIGMA)
    assert bs is not None
    assert fd * bs > 0, (
        f"{label}: bs_charm sign {bs:+.4f} disagrees with FD calendar charm {fd:+.4f}"
    )


def test_near_expiry_minutes_to_close_matches_finite_difference():
    """RC-179 LOCK 3 — the regime the retired 0.5-day floor used to flatten.

    One hour to the bell: analytic charm must match a finite-difference of BS delta over the
    final minutes, in MAGNITUDE, not just sign. This is the test that would have caught the floor.
    """
    hour = 1.0 / (24.0 * 365.0)
    dt = 1.0 / (3600.0 * 24.0 * 365.0)  # one second of calendar time
    spot = 100.5  # slightly ITM — charm is finite and nonzero here
    # a central difference, a second each side: its own error is a few parts in a hundred million
    # an hour from the bell, where delta bends fast
    fd = (_call_delta(spot, hour - dt) - _call_delta(spot, hour + dt)) / (2.0 * dt)
    analytic = charm(spot, K, hour, SIGMA)
    assert analytic is not None
    assert analytic == pytest.approx(fd), (
        f"one hour from the close, analytic charm {analytic:.2f} vs FD {fd:.2f} — a T floor "
        "or convention drift is flattening the near-expiry spike again"
    )


# ── at Schwab's own rate and dividend yield, on real chains (operator 2026-11-12: "yes, but
# make sure the calculations are correct") ──


@pytest.mark.parametrize("book", [SPY_FULL, MRVL, SPY_0DTE], ids=lambda b: b.ticker)
def test_charm_and_vanna_are_the_bsm_deltas_derivatives_at_schwabs_rate_and_yield(book):
    """Every contract of three real chains, each with a dividend yield above 0.

    The program's charm and vanna equal the finite-difference derivatives of the textbook
    Black-Scholes-Merton delta in time and in volatility, at Schwab's rate and yield; and a
    call's charm is not its put's, as a yield above 0 requires.
    """
    (k, t, sigma, sign, r, q, _size), charm_fd, vanna_fd = delta_derivatives(book)
    got_charm = bs_charm_array(book.spot, k, t, sigma, sign, r, q)
    got_vanna = bs_vanna_array(book.spot, k, t, sigma, r, q)
    assert len(k) > 30 and (q > 0).all() and (r > 0).all()
    np.testing.assert_allclose(got_charm, charm_fd, rtol=1e-4, atol=1e-6 * np.abs(charm_fd).max())
    np.testing.assert_allclose(got_vanna, vanna_fd, rtol=1e-4, atol=1e-6 * np.abs(vanna_fd).max())
    flipped = bs_charm_array(book.spot, k, t, sigma, -sign, r, q)
    assert np.abs(got_charm - flipped).max() > 0, "with a yield a call's charm is not its put's"


def test_the_per_strike_charm_and_vanna_are_those_derivatives_summed_on_spys_whole_chain():
    """SPY's whole chain of 2026-11-09 through the two producers the levels read.

    Each strike's call charm (delta-shares a day) and call vanna (per vol point) are the
    finite-difference derivatives of every call there, times open interest and multiplier.
    """
    (k, _t, _sigma, sign, _r, _q, size), charm_fd, vanna_fd = delta_derivatives(SPY_FULL)
    contracts = read_chain(SPY_FULL.chain)
    product = option_close_product(SPY_FULL.ticker)
    held = sessions()
    charm_by = compute_charm_by_strike(
        contracts, SPY_FULL.spot, now=SPY_FULL.now, sessions=held, product=product
    )
    vanna_by, _ = compute_exposures_by_strike(
        contracts, spot=SPY_FULL.spot, now=SPY_FULL.now, sessions=held, product=product
    )
    calls = sign > 0
    checked = 0
    for strike in np.unique(k[calls]).tolist():
        here = calls & (k == strike)
        want_charm = float((charm_fd[here] * size[here]).sum() / 365.0)
        want_vanna = float((vanna_fd[here] * size[here]).sum() * 0.01)
        got_charm, got_vanna = charm_by[strike]["call_charm"], vanna_by[strike]["call_vanna"]
        if got_charm is None or got_vanna is None:  # a call there the program could not price
            continue
        # against a central difference of Black-Scholes delta (a step of 1e-4 of each input):
        # its own error is under a part in a million
        assert got_charm == pytest.approx(want_charm), strike
        assert got_vanna == pytest.approx(want_vanna), strike
        checked += 1
    assert checked > 200, f"{checked} strikes checked"


# ── RC-211: the SAME ground-truth lock for VANNA (operator spec, independently verified) ──


def test_vanna_is_identical_for_calls_and_puts_in_the_bucket_path():
    """RC-211: put-call parity kills any call/put vanna split.

    Same strike/expiry/IV must aggregate the SAME per-contract vanna into both bucket sides
    (splits come from OI only).
    """
    # valued 30 days before a fixed expiry Schwab's /markets answers (an input: the date never
    # ages out)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=ET)
    expiry = "2026-10-28"
    base = {
        "strikePrice": 100.0,
        "expirationDate": expiry,
        "gamma": 0.05,
        "delta": 0.5,
        "volatility": 20.0,
        "openInterest": 100,
        "multiplier": 100,
        "daysToExpiration": 30,
        "vega": 0.11,
        "bidSize": 1,
        "askSize": 1,
        "totalVolume": 10,
        "interestRate": 0.0,
        "dividendYield": 0.0,
    }
    # exact-identity math lock needs controlled equal inputs;
    # a captured chain cannot pin call_vanna == put_vanna at equal OI.
    call = dict(base, putCall="CALL")
    put = dict(base, putCall="PUT")
    per, _ = compute_exposures_by_strike(
        read_chain([call, put]), spot=98.0, now=now, sessions=sessions()
    )
    b = per[100.0]
    assert b["call_vanna"] != 0.0, "call vanna did not compute"
    assert abs(b["call_vanna"] - b["put_vanna"]) < 1e-9, (
        f"call/put vanna split at equal OI: {b['call_vanna']} vs {b['put_vanna']} — "
        f"the math invented a split parity forbids"
    )
    assert b["call_vanna"] > 0, "strike above spot (100 > 98) must have positive vanna"


def test_vanna_uses_the_single_iv_conversion_authority_f7():
    """The per-strike vanna converts Schwab IV through schwab_iv_to_sigma, the ONE authority.

    Schwab's volatility is a PERCENT (measured 2026-09-27 on 49,244 contracts, min 7.967), so
    20.0 is sigma 0.20 -- equal to bs_vanna at sigma 0.20 -- and 0.20 is 0.2%, not 20%.
    """
    # valued a month before an expiry Schwab's /markets answers (an input)
    now = datetime(2027, 6, 17, 12, 0, tzinfo=ET)

    def one(iv):
        # a units-flip discriminator needs the SAME contract with IV in
        # percent vs decimal form — a captured real chain cannot pin that controlled pair.
        return {
            "strikePrice": 100.0,
            "expirationDate": "2027-07-16",
            "gamma": 0.05,
            "delta": 0.5,
            "volatility": iv,
            "openInterest": 100,
            "multiplier": 100,
            "daysToExpiration": 30,
            "vega": 0.11,
            "bidSize": 1,
            "askSize": 1,
            "totalVolume": 10,
            "putCall": "CALL",
            "interestRate": 0.0,
            "dividendYield": 0.0,
        }

    held = sessions()
    per_pct, _ = compute_exposures_by_strike(
        read_chain([one(20.0)]), spot=98.0, now=now, sessions=held
    )
    v_pct = per_pct[100.0]["call_vanna"]
    assert v_pct not in (None, 0.0), "percent-form vanna did not compute"
    assert schwab_iv_to_sigma(20.0) == 0.20 and schwab_iv_to_sigma(0.20) == 0.002
    t = time_to_expiry_years("2027-07-16", now, sessions=held)
    v_dec = vanna(98.0, 100.0, t, 0.20) * 0.01 * 100 * 100
    # RELATIVE tolerance: these aggregates are ~1e3-1e4, where one float ULP is ~1e-12 relative but
    # ~1e-9 ABSOLUTE — an absolute 1e-9 bound is tighter than the arithmetic can hold and failed on
    # CI's platform while passing locally (got 4731.665262145597 vs 4731.665262144535). The claim
    # under test is "the same sigma", i.e. equality to floating-point precision, which is a relative
    # statement; an inline /100 would differ by a FACTOR OF 100, not by 1e-12.
    assert math.isclose(v_pct, v_dec, rel_tol=1e-9), (
        f"vanna at IV 20.0 must be bs_vanna at sigma 0.20; got {v_pct} vs {v_dec}"
    )
    # IV absent, 0 or negative: schwab_iv_to_sigma gives no sigma, so the contract adds no vanna
    # (the vanna path checks IV once, there); the same contract at IV 20.0 adds v_pct
    for bad in (None, 0.0, -5.0):
        assert schwab_iv_to_sigma(bad) is None, bad
        per_bad, _ = compute_exposures_by_strike(
            read_chain([one(bad)]), spot=98.0, now=now, sessions=held
        )
        assert per_bad[100.0]["call_vanna"] == 0.0 != v_pct, bad
