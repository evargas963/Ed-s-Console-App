"""Ground-truth sign lock for charm (RC-CHARM-SIGN).

OBSERVED (2026-07-25): compute_net_charm shipped charm_unit = -phi(d1)*d2/(2T) — the exact
NEGATIVE of calendar-time charm — so charm_direction was inverted ("buying" when dealer flow
was selling), disagreeing with the correct per-strike bs_charm path on 70-79% of real states.
It survived because the only "verification" checked ALGEBRA against a textbook formula, not
GROUND TRUTH. A sign this consequential (it feeds a displayed note + a model feature) must be
locked against an empirical derivative, so no future revision can silently flip it again.

VALIDATED: this finite-difference IS the ground truth — d(Delta)/dt as calendar time advances
(T shrinks) — computed independently of both implementations. Both bs_charm and the scalar
compute_net_charm must match its sign for every moneyness, or the build fails.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from math_levels import bs_charm

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


def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _call_delta(S: float, T: float) -> float:
    d1 = (math.log(S / K) + 0.5 * SIGMA * SIGMA * T) / (SIGMA * math.sqrt(T))
    return _N(d1)


def _fd_calendar_charm(S: float, dte: int) -> float:
    """Ground truth: (delta(T - 1 day) - delta(T)) / dt — the day passes, T shrinks."""
    T = dte / 365.0
    dt = 1.0 / 365.0
    return (_call_delta(S, T - dt) - _call_delta(S, T)) / dt


@pytest.mark.parametrize("label,S,dte", CASES)
def test_bs_charm_sign_matches_finite_difference(label, S, dte):
    fd = _fd_calendar_charm(S, dte)
    bs = bs_charm(S, K, dte / 365.0, SIGMA, rate=0.0)
    assert bs is not None
    assert fd * bs > 0, f"{label}: bs_charm sign {bs:+.4f} disagrees with FD calendar charm {fd:+.4f}"








def test_near_expiry_minutes_to_close_matches_finite_difference():
    """RC-179 LOCK 3 — the regime the retired 0.5-day floor used to flatten. One hour to the
    bell: analytic charm must match a finite-difference of BS delta over the final minutes,
    in MAGNITUDE, not just sign. This is the test that would have caught the floor."""
    T_1h = 1.0 / (24.0 * 365.0)
    dt = 1.0 / (60.0 * 24.0 * 365.0)  # one minute of calendar time
    S = 100.5  # slightly ITM — charm is finite and nonzero here
    fd = (_call_delta(S, T_1h - dt) - _call_delta(S, T_1h)) / dt
    analytic = bs_charm(S, K, T_1h, SIGMA, rate=0.0)
    assert analytic is not None
    assert analytic == pytest.approx(fd, rel=0.05), (
        f"one hour from the close, analytic charm {analytic:.2f} vs FD {fd:.2f} — a T floor "
        "or convention drift is flattening the near-expiry spike again"
    )








# ── RC-211: the SAME ground-truth lock for VANNA (operator spec, independently verified) ──









def test_vanna_is_identical_for_calls_and_puts_in_the_bucket_path(pin_clock):
    """RC-211: put-call parity kills any call/put vanna split — same strike/expiry/IV must
    aggregate the SAME per-contract vanna into both bucket sides (splits come from OI only)."""
    from math_exposure_core import compute_exposures_by_strike

    # valued at a pinned instant 30 days before a fixed expiry: the date never ages out, and
    # never lands on a holiday (a rolling today+30 did on 2026-10-27, 11-25, ...)
    pin_clock(2026, 9, 28, 12, 0)
    expiry = "2026-10-28"
    base = {"strikePrice": 100.0, "expirationDate": expiry, "gamma": 0.05,
            "delta": 0.5, "volatility": 20.0, "openInterest": 100, "multiplier": 100,
            "daysToExpiration": 30, "vega": 0.11, "bidSize": 1, "askSize": 1,
            "totalVolume": 10}
    # institutional-synthetic-ok: exact-identity math lock needs controlled equal inputs;
    # a captured chain cannot pin call_vanna == put_vanna at equal OI.
    call = dict(base, putCall="CALL")
    put = dict(base, putCall="PUT")
    per, _ = compute_exposures_by_strike([call, put], spot=98.0)
    b = per[100.0]
    assert b["call_vanna"] != 0.0, "call vanna did not compute"
    assert abs(b["call_vanna"] - b["put_vanna"]) < 1e-9, (
        f"call/put vanna split at equal OI: {b['call_vanna']} vs {b['put_vanna']} — "
        f"the math invented a split parity forbids")
    assert b["call_vanna"] > 0, "strike above spot (100 > 98) must have positive vanna"


def test_vanna_uses_the_single_iv_conversion_authority_f7():
    """The per-strike vanna converts Schwab IV through schwab_iv_to_sigma, the ONE authority:
    Schwab's volatility is a PERCENT (measured 2026-09-27 on 49,244 contracts, min 7.967), so
    20.0 is sigma 0.20 -- equal to bs_vanna at sigma 0.20 -- and 0.20 is 0.2%, not 20%."""
    from math_exposure_core import compute_exposures_by_strike

    def one(iv):
        # institutional-synthetic-ok: a units-flip discriminator needs the SAME contract with IV in
        # percent vs decimal form — a captured real chain cannot pin that controlled pair.
        return {"strikePrice": 100.0, "expirationDate": "2030-01-18", "gamma": 0.05,
                "delta": 0.5, "volatility": iv, "openInterest": 100, "multiplier": 100,
                "daysToExpiration": 30, "vega": 0.11, "bidSize": 1, "askSize": 1,
                "totalVolume": 10, "putCall": "CALL"}

    from math_exposure_core import schwab_iv_to_sigma
    from math_levels import bs_vanna
    from time_et import time_to_expiry_years
    per_pct, _ = compute_exposures_by_strike([one(20.0)], spot=98.0)
    v_pct = per_pct[100.0]["call_vanna"]
    assert v_pct not in (None, 0.0), "percent-form vanna did not compute"
    assert schwab_iv_to_sigma(20.0) == 0.20 and schwab_iv_to_sigma(0.20) == 0.002
    v_dec = bs_vanna(98.0, 100.0, time_to_expiry_years("2030-01-18"), 0.20) * 0.01 * 100 * 100
    # RELATIVE tolerance: these aggregates are ~1e3-1e4, where one float ULP is ~1e-12 relative but
    # ~1e-9 ABSOLUTE — an absolute 1e-9 bound is tighter than the arithmetic can hold and failed on
    # CI's platform while passing locally (got 4731.665262145597 vs 4731.665262144535). The claim
    # under test is "the same sigma", i.e. equality to floating-point precision, which is a relative
    # statement; an inline /100 would differ by a FACTOR OF 100, not by 1e-12.
    assert math.isclose(v_pct, v_dec, rel_tol=1e-9), (
        f"vanna at IV 20.0 must be bs_vanna at sigma 0.20; got {v_pct} vs {v_dec}")
