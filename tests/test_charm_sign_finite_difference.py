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

from math_exposure_core import compute_net_charm
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


def _mixed_book(exp: str, call_oi: int, put_oi: int) -> list[dict]:
    """Two-sided book at one strike with controllable OI mix.

    institutional-synthetic-ok: the dealer-sign convention is a pure aggregation identity
    (net = call - put); proving it requires exact control of the OI mix, which no captured
    chain can pin.
    """
    base = {"strikePrice": K, "expirationDate": exp, "gamma": 0.05,
            "volatility": SIGMA * 100.0, "multiplier": 100}
    return [
        {**base, "putCall": "CALL", "delta": 0.55, "openInterest": call_oi},
        {**base, "putCall": "PUT", "delta": -0.45, "openInterest": put_oi},
    ]


def test_scalar_equals_per_strike_dealer_signed_sum():
    """RC-179 LOCK 1 — one convention, two engines, zero drift. The scalar's docstring once
    claimed same-sign summation while the code netted call-put; prose and code diverged for a
    week and the 'open faucet' lived on only in documentation. This binds the CODE identity:
    compute_net_charm == sum of compute_charm_by_strike net over the same book."""
    from datetime import datetime, timedelta

    from math_levels import compute_charm_by_strike
    from time_et import ET

    exp = "2026-08-03"
    now = datetime(2026, 8, 3, 16, 0, tzinfo=ET) - timedelta(days=5)
    book = _mixed_book(exp, call_oi=1000, put_oi=3000)
    scalar = compute_net_charm(book, 100.0, exp, now=now)["net_charm_daily"]
    per = compute_charm_by_strike(book, 100.0, now=now)
    per_net = sum(v["net_charm"] for v in per.values())
    assert scalar is not None
    # abs=0.005: net_charm_daily is contractually rounded to 2 decimals on return; the
    # underlying sums agree to machine precision (measured 93.38 vs 93.37892829040211).
    assert scalar == pytest.approx(per_net, abs=0.005), (
        f"the two charm engines diverged: scalar {scalar} vs per-strike {per_net} — "
        "single-faucet parity is the whole point of RC-179"
    )


def test_put_heavy_book_flips_the_dealer_signed_net():
    """RC-179 LOCK 2 — the dealer convention must be LIVE, not asserted. Same charm unit on
    both sides, so a same-sign (gross) summation could never flip with the OI mix; only
    call-minus-put can. A put-heavy book must carry the opposite net sign from a call-heavy
    one, and neither may equal the gross."""
    from datetime import datetime, timedelta

    from time_et import ET

    exp = "2026-08-03"
    now = datetime(2026, 8, 3, 16, 0, tzinfo=ET) - timedelta(days=5)
    call_heavy = compute_net_charm(_mixed_book(exp, 3000, 1000), 100.0, exp, now=now)
    put_heavy = compute_net_charm(_mixed_book(exp, 1000, 3000), 100.0, exp, now=now)
    a, b = call_heavy["net_charm_daily"], put_heavy["net_charm_daily"]
    assert a is not None and b is not None
    assert a * b < 0, (
        f"OI mix did not flip the net ({a} vs {b}) — aggregation has regressed to a "
        "same-sign magnitude and charm_direction is meaningless again"
    )
    gross = abs(call_heavy["call_charm_daily"]) + abs(call_heavy["put_charm_daily"])
    assert abs(a) != pytest.approx(gross, rel=1e-6), "net equals gross — convention lost"


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


def test_both_engines_draw_T_from_the_single_source():
    """RC-179 LOCK 4 — the unification is structural, not incidental. Both engines must call
    time_et.time_to_expiry_years; a reintroduced local T derivation is how the two-convention
    era began."""
    import inspect

    import math_levels as ml
    from math_exposure_core import compute_net_charm as cnc

    assert "time_to_expiry_years" in inspect.getsource(cnc)
    assert "time_to_expiry_years" in inspect.getsource(ml._contract_inputs)
    # and the stale disclaimer must never return to the contract text
    doc = inspect.getdoc(cnc) or ""
    assert "summed with the SAME sign" not in doc, (
        "the pre-fix docstring paragraph is back — prose contradicting code is how this "
        "faucet survived three weeks after the code was fixed"
    )
    assert "call_charm - put_charm" in inspect.getsource(cnc)


@pytest.mark.parametrize("label,S,dte", CASES)
def test_compute_net_charm_sign_matches_finite_difference(label, S, dte):
    from datetime import datetime, timedelta
    from time_et import ET
    fd = _fd_calendar_charm(S, dte)
    # T now comes from the canonical calendar clock (time_to_expiry_years), so pin `now` to
    # exactly `dte` days before the 16:00 ET expiry — making compute_net_charm's T == dte/365,
    # matching the finite-difference's T (a weekday expiry so the session close is 16:00).
    exp = "2026-08-03"  # Monday
    now = datetime(2026, 8, 3, 16, 0, tzinfo=ET) - timedelta(days=dte)
    # single CALL contract -> net_charm_daily = call_charm, sign == per-contract charm sign
    # institutional-synthetic-ok: controlled BS inputs (K,S,dte,sigma) are REQUIRED to verify the
    # charm SIGN against a finite-difference derivative of a known analytic result; a real captured
    # chain cannot pin an exact math identity (this is a pure-math sign lock, not a domain-shape test).
    contract = {
        "strikePrice": K, "putCall": "CALL", "expirationDate": exp,
        "gamma": 0.05, "delta": 0.55, "volatility": SIGMA * 100.0,  # Schwab reports IV in percent
        "openInterest": 1000, "multiplier": 100, "daysToExpiration": dte,
    }
    out = compute_net_charm([contract], S, exp, now=now)
    ncd = out.get("net_charm_daily")
    assert ncd is not None, f"{label}: charm did not compute ({out.get('error')})"
    assert fd * ncd > 0, (
        f"{label}: compute_net_charm sign {ncd:+.1f} disagrees with FD calendar charm "
        f"{fd:+.4f} — the sign was inverted once (2026-07-25); it must never flip again."
    )


# ── RC-211: the SAME ground-truth lock for VANNA (operator spec, independently verified) ──

def _phi_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _Phi_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call_delta(S: float, K_: float, T: float, s: float) -> float:
    d1 = (math.log(S / K_) + 0.5 * s * s * T) / (s * math.sqrt(T))
    return _Phi_cdf(d1)


@pytest.mark.parametrize("K_, T, sigma, label", [
    (90.0, 30 / 365, 0.25, "below-spot (vanna must be NEGATIVE)"),
    (110.0, 30 / 365, 0.25, "above-spot (vanna must be POSITIVE)"),
    (100.0, 2 / 365, 0.20, "ATM 0DTE-adjacent (small, ~0.2*sqrt(T))"),
    (95.0, 180 / 365, 0.60, "high-vol long-dated"),
])
def test_bs_vanna_matches_finite_difference_and_gamma_identity(K_, T, sigma, label):
    """RC-211 ground truth: bs_vanna must match (1) a central finite difference of the BS
    delta w.r.t. sigma — computed here independently of the implementation — and (2) the
    gamma identity vanna = -Gamma * S * sqrt(T) * d2 (operator: 'if your analytic vanna and
    your gamma disagree under it, one of them is wrong'). The shipped vega/(S*sigma)
    shortcut failed BOTH (always positive; REFUTED 2026-08-02, max truth-gap 1.19 at
    below-spot strikes) — this lock makes that class unshippable."""
    from math_levels import bs_gamma, bs_vanna

    S = 100.0
    h = 1e-5
    fd = (_bs_call_delta(S, K_, T, sigma + h) - _bs_call_delta(S, K_, T, sigma - h)) / (2 * h)
    v = bs_vanna(S, K_, T, sigma)
    assert v is not None, f"{label}: bs_vanna returned None on valid inputs"
    assert abs(v - fd) < 1e-5, f"{label}: bs_vanna {v:+.6f} != FD ground truth {fd:+.6f}"
    g = bs_gamma(S, K_, T, sigma)
    d1 = (math.log(S / K_) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    gamma_id = -g * S * math.sqrt(T) * d2
    assert abs(v - gamma_id) < 1e-9, (
        f"{label}: vanna {v:+.6f} violates the gamma identity {gamma_id:+.6f} — "
        f"one of bs_vanna/bs_gamma is wrong")
    # EXACT sign law: sign(vanna) == sign(-d2). (The 'above spot positive / below spot
    # negative' shorthand holds only while the d2=0 boundary K = S*e^((sigma^2/2)T) sits
    # near spot — long-dated high-vol moves it; the K=95/T=180d/sigma=0.6 case here has
    # the boundary at ~109, so below-spot vanna is legitimately POSITIVE.)
    if abs(d2) > 1e-12:
        assert (v > 0) == (d2 < 0), (
            f"{label}: sign(vanna)={v:+.6f} disagrees with -d2 (d2={d2:+.4f})")


def test_vanna_is_identical_for_calls_and_puts_in_the_bucket_path():
    """RC-211: put-call parity kills any call/put vanna split — same strike/expiry/IV must
    aggregate the SAME per-contract vanna into both bucket sides (splits come from OI only)."""
    from math_exposure_core import compute_exposures_by_strike

    base = {"strikePrice": 100.0, "expirationDate": "2026-09-18", "gamma": 0.05,
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
