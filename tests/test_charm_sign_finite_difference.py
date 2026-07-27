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
