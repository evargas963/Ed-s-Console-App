"""FIND-GAMMA-FLIP-METHOD-V1 — canonical gamma profile (hypothetical-spot recompute).

Proven 2026-07-19 on a real SPY reference chain that the cumulative-sum method does NOT
reproduce the published profile (corr 0.086, never crosses zero, 2.19e9 divergence).
Only recomputing every contract's gamma at each candidate price reproduces the published
flip. These tests run on a REAL captured Schwab chain, never a hand-built one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from math_levels import (
    FLIP_CURVE_NOT_FINITE,
    FLIP_FOUND,
    FLIP_NO_CROSSING,
    FLIP_UNAVAILABLE,
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_UNAVAILABLE,
    GSF_STATE_BELOW_SUPPORT,
    GSF_STATE_OK,
    GSF_STATE_UNAVAILABLE,
    compute_gamma_flip,
    compute_gamma_profile,
    compute_gamma_support_levels,
    gamma_at_price,
    profile_sign_changes,
)

import pytest
from datetime import datetime
import time_et


@pytest.fixture(autouse=True)
def _pin_now_to_fixture_session(monkeypatch):
    # The fixture is a REAL 0DTE SPY chain captured 2026-09-22 12:46 ET. The canonical intraday
    # time-to-expiry (time_et.time_to_expiry_years) measures from now_et() to the session
    # close, so replaying it today reads it as long-expired and drops every contract. Pin the
    # clock to mid-session on the fixture's expiry day so it is a live 0DTE (~6h to close).
    monkeypatch.setattr(time_et, "now_et", lambda: datetime(2026, 9, 22, 12, 46, tzinfo=time_et.ET))


_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json"


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def _flip(profile, spot):
    """compute_gamma_flip -- the one place the flip is picked -- on a hand-built curve.
    institutional-synthetic-ok: an exact sign pattern (a touch, a run of zeros, a second
    crossing at a chosen price) cannot be pinned on a captured chain."""
    strikes = [{"strikePrice": profile[0][0]}, {"strikePrice": profile[-1][0]}]
    return compute_gamma_flip(strikes, spot, profile=profile, unpriced={})


def test_profile_on_real_chain_is_finite_and_spans_spot() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot)
    assert len(prof) == 241
    assert all(math.isfinite(v) for _, v in prof)
    prices = [p for p, _ in prof]
    assert prices[0] < spot < prices[-1]
    assert prices == sorted(prices)


def test_profile_uses_dealer_sign_convention() -> None:
    """Calls add, puts subtract: an all-call book must be positive at every price."""
    chain, spot = _load_real_chain()
    calls = [c for c in chain if str(c.get("putCall", "")).upper().startswith("C")]
    assert calls, "fixture must contain calls"
    prof = compute_gamma_profile(calls, spot)
    assert prof and all(v >= 0 for _, v in prof)


def test_flip_is_interpolated_within_the_profile_span() -> None:
    """RC-467: the real chain MUST yield a flip - the old `if flip is not None` guard let
    a flip-always-None regression pass silently while asserting nothing. MEASURED on this
    fixture under the pinned session clock: 241 profile points, 2 sign crossings,
    flip = 761.0, inside the span. Existence is pinned; the exact value is not (it moves
    with vol/time inputs) - span containment is the invariant."""
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot)
    flip = compute_gamma_flip(chain, spot, profile=prof, unpriced={}).price
    assert flip is not None, (
        "the real fixture chain has a zero crossing (measured flip 761.0); a None flip "
        "here means the profile or crossing detection regressed"
    )
    assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_returns_none_when_no_zero_crossing() -> None:
    no = _flip([(100.0, 5.0), (101.0, 7.0)], 100.5)
    assert no.price is None and no.state == FLIP_NO_CROSSING and no.crossings == 0
    assert profile_sign_changes([]) == []


def test_narrow_chain_flip_is_reported_low_confidence() -> None:
    """The live 20-strike chain spans only ~+/-1.3%; its flip must never be served as
    trustworthy (measured error vs full-chain reference: 770.35 vs 745.61)."""
    chain, spot = _load_real_chain()
    flip = compute_gamma_flip(chain, spot, profile=compute_gamma_profile(chain, spot), unpriced={})
    assert flip.coverage == GAMMA_FLIP_NARROW
    # On this capture (SPY 2026-09-22 12:46 ET, strikes 764-783) the flip is 771.9, inside the
    # delivered strikes: the verdict is NARROW because 20 strikes span only ~+/-1.3% of spot,
    # not because the flip falls outside them.
    assert flip.state == FLIP_FOUND and flip.price == 771.9
    assert (flip.strike_lo, flip.strike_hi) == (764.0, 783.0)
    assert flip.covers_regime_span is False and flip.covers_level_span is False, (
        "both span-coverage flags must be False for a NARROW verdict; a tier-selection "
        "inversion would flip these while leaving the raw spans untouched")


def test_flip_fails_closed_without_inputs() -> None:
    for contracts, spot in (([], 100.0), (None, 100.0), ([{"strikePrice": 100}], 0.0),
                            ([{"strikePrice": 100}], 100.0)):
        flip = compute_gamma_flip(contracts, spot, profile=[], unpriced={})
        assert flip.price is None and flip.state == FLIP_UNAVAILABLE and flip.reason
        assert flip.coverage == GAMMA_FLIP_UNAVAILABLE


def test_a_curve_that_is_not_finite_is_no_curve_never_a_zero() -> None:
    """Operator 2026-09-30: nothing stands in for a failed calculation. A term of the profile
    that is not finite used to be replaced by 0 and the curve served as if complete.
    Stand-in: the real chain with one contract's open interest set large enough to overflow
    the sum (Schwab has not sent such a value)."""
    chain, spot = _load_real_chain()
    chain = [dict(c) for c in chain]
    next(c for c in chain if c.get("openInterest")).update(openInterest=1e308)
    prof = compute_gamma_profile(chain, spot)
    assert not all(math.isfinite(v) for _, v in prof)
    flip = compute_gamma_flip(chain, spot, profile=prof, unpriced={})
    assert (flip.state, flip.reason, flip.price) == (FLIP_UNAVAILABLE, FLIP_CURVE_NOT_FINITE, None)
    assert flip.curve_gamma_at_spot is None and flip.crossings == 0

def test_regime_is_defined_even_when_the_profile_never_crosses_zero() -> None:
    """RC-11: no zero-crossing means no FLIP LEVEL, never an unknown regime.

    A chain whose dealer gamma holds one sign at every price has an unambiguous regime --
    arguably more certain than one with a flip beside spot. Before this was corrected, 20
    of 51 live tickers reported UNAVAILABLE while their gamma was uniformly signed.
    """
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot)
    assert prof, "real chain must produce a profile"

    at_spot = gamma_at_price(prof, spot)
    assert at_spot is not None and math.isfinite(at_spot)

    # interpolation must sit inside the bracketing profile values
    pts = sorted(prof)
    below = [v for x, v in pts if x <= spot]
    above = [v for x, v in pts if x >= spot]
    if below and above:
        lo, hi = min(below[-1], above[0]), max(below[-1], above[0])
        assert lo - 1e-6 <= at_spot <= hi + 1e-6

    # a strictly one-signed profile yields no flip but still reports a usable verdict
    assert profile_sign_changes([(100.0, 5.0), (101.0, 7.0)]) == []
    assert gamma_at_price([(100.0, 5.0), (101.0, 7.0)], 100.5) == 6.0


def test_gamma_at_price_has_no_value_outside_the_profile() -> None:
    """The curve was not evaluated off the profile, so it has no value there; the edge
    value never stands in."""
    prof = [(100.0, -2.0), (110.0, 4.0)]
    assert gamma_at_price(prof, 100.0) == -2.0 and gamma_at_price(prof, 110.0) == 4.0
    assert gamma_at_price(prof, 50.0) is None
    assert gamma_at_price(prof, 500.0) is None
    assert gamma_at_price([], 100.0) is None
    assert gamma_at_price(prof, None) is None


# ── STRIKE WIDTH IS DERIVED, NOT TABULATED (root fix for RC-12) ─────────────
# RC-12 found the cause -- "a fixed strike count cannot satisfy a percentage-based span
# requirement across instruments with different strike spacing" -- then answered it with a
# hardcoded table for three tickers, leaving every other ticker on a fixed 40. MEASURED
# across 52 stored chains 2026-07-20: that table was wrong in BOTH directions. $SPX needed
# 150 and got 40; IWM needed 30 and got 80; ~48 equities needed under 20 and got 40.


# ── FLIP DETECTION IS DIRECTION-BLIND (Bugbot 2026-07-20, HIGH — confirmed) ──
# `v0 < 0 <= v1` found only rising neg->pos crossings. A profile that is long-gamma below
# and short-gamma above (pos->neg) has a real regime boundary that returned None — the
# flip vanished and the verdict claimed "no crossing" on a chain that crosses.


def test_flip_detects_positive_to_negative_crossing():
    prof = [(90.0, 5.0), (95.0, 2.0), (100.0, -1.0), (105.0, -4.0)]
    flip = _flip(prof, 97.0).price
    assert flip is not None, "pos->neg crossing missed — the direction-blind defect"
    assert 95.0 < flip < 100.0, flip


def test_flip_still_detects_negative_to_positive():
    prof = [(90.0, -4.0), (95.0, -1.0), (100.0, 2.0), (105.0, 5.0)]
    flip = _flip(prof, 97.0).price
    assert flip is not None and 95.0 < flip < 100.0, flip


def test_flip_picks_the_crossing_nearest_spot():
    """Multi-cross profile: the boundary that governs the trade is the one beside spot."""
    prof = [(80.0, -2.0), (90.0, 3.0), (100.0, 1.0), (110.0, -2.0), (120.0, -5.0)]
    low, high = _flip(prof, spot=85.0), _flip(prof, spot=108.0)
    assert low.price is not None and 80.0 < low.price < 90.0, low.price
    assert high.price is not None and 100.0 < high.price < 110.0, high.price
    assert low.crossings == high.crossings == 2
    assert profile_sign_changes(prof) == [low.price, high.price]   # every sign change, ascending


def test_flip_none_when_one_signed():
    assert profile_sign_changes([(90.0, -1.0), (100.0, -2.0)]) == []
    assert profile_sign_changes([(90.0, 1.0), (100.0, 2.0)]) == []


def test_a_zero_touch_is_not_a_flip_only_a_sign_change_is():
    """Operator 2026-09-30: the flip requires an actual sign change. A curve that starts or
    ends at exactly zero, or touches zero and keeps its sign, used to report a flip at the
    zero point (the 2026-07-20 rule this replaces treated a zero point as a boundary)."""
    assert profile_sign_changes([(100.0, 0.0), (110.0, 1.0), (120.0, 2.0)]) == []      # starts at zero
    assert profile_sign_changes([(100.0, -2.0), (110.0, -1.0), (120.0, 0.0)]) == []    # ends at zero
    assert profile_sign_changes([(100.0, 1.0), (110.0, 0.0), (120.0, 1.0)]) == []      # touches, same sign
    assert profile_sign_changes([(100.0, 0.0), (110.0, 0.0)]) == []                    # no sign at all
    touch = _flip([(100.0, 1.0), (110.0, 0.0), (120.0, 1.0)], 110.0)
    assert touch.price is None and touch.state == FLIP_NO_CROSSING
    # through zero, negative to positive: the change is at the zero point
    assert profile_sign_changes([(100.0, -1.0), (110.0, 0.0), (120.0, 1.0)]) == [110.0]
    # across a run of exact zeros: the middle of the run
    assert profile_sign_changes([(100.0, 1.0), (110.0, 0.0), (120.0, 0.0), (130.0, -1.0)]) == [115.0]


# ── RC-354: Gamma Support Floor / Gamma Resistance Ceiling ──────────────────────


def _linear_profile(lo_px, hi_px, lo_v, hi_v, steps=100):
    """Synthetic ascending profile with net GEX linear from lo_v to hi_v."""
    return [
        (round(lo_px + (hi_px - lo_px) * i / steps, 4),
         lo_v + (hi_v - lo_v) * i / steps)
        for i in range(steps + 1)
    ]


def test_gsf_sits_between_flip_and_spot_and_grc_mirrors_above():
    # N(s) rises linearly from -2e9 at 90 to +6e9 at 110; spot 105 -> N(spot)=+4e9.
    # target = 0.5*N(spot) = 2e9. Crossing below spot at s where N=2e9 -> s=100.
    # Flip (N=0) at 95: GSF must sit ABOVE the flip (support ends before the zero).
    prof = _linear_profile(90.0, 110.0, -2e9, 6e9)
    out = compute_gamma_support_levels(prof, 105.0)
    assert out["state"] == GSF_STATE_OK
    assert out["gsf"] is not None
    flip = _flip(prof, 105.0).price
    assert flip is not None and out["gsf"] > flip           # above the flip
    assert flip < out["gsf"] < 105.0                        # between flip and spot
    assert abs(out["gsf"] - 100.0) < 0.5                    # analytic crossing
    # monotone-rising profile above spot never decays below target -> no ceiling
    assert out["grc"] is None


def test_grc_found_when_cushion_decays_above_spot():
    # Tent profile: rises to a peak above spot then decays — the ceiling lands on the
    # DECAYING shoulder past the peak (resistance strengthens before it exhausts).
    up = _linear_profile(100.0, 106.0, 4e9, 8e9, steps=60)
    down = _linear_profile(106.1, 112.0, 7.9e9, 0.0, steps=59)
    prof = up + down
    out = compute_gamma_support_levels(prof, 102.0)
    assert out["state"] == GSF_STATE_OK
    assert out["grc"] is not None and out["grc"] > 106.0    # beyond the peak/wall
    n_spot = out["n_at_spot"]
    # value at the ceiling is ~phi * N(spot)
    assert abs(gamma_at_price(prof, out["grc"]) - 0.5 * n_spot) / n_spot < 0.05


def test_below_support_state_never_fabricates_a_price():
    # Negative-gamma regime at spot: honest STATE, both levels None.
    prof = _linear_profile(90.0, 110.0, -6e9, -1e9)
    out = compute_gamma_support_levels(prof, 100.0)
    assert out["state"] == GSF_STATE_BELOW_SUPPORT
    assert out["gsf"] is None and out["grc"] is None


def test_unavailable_on_empty_or_bad_inputs():
    assert compute_gamma_support_levels([], 100.0)["state"] == GSF_STATE_UNAVAILABLE
    assert compute_gamma_support_levels(_linear_profile(90, 110, 1e9, 2e9), None)["state"] == GSF_STATE_UNAVAILABLE
    assert compute_gamma_support_levels(_linear_profile(90, 110, 1e9, 2e9), -5)["state"] == GSF_STATE_UNAVAILABLE


def test_rc358_25d_risk_reversal_30_day_tenor_and_fail_closed():
    """RC-358: RR = IV(25Δ call) − IV(25Δ put) on the expiry nearest 30 days out (the published
    fixed tenor; 2026-09-27), tolerance-gated; an unusable wing yields None."""
    from math_volatility import compute_25d_risk_reversal

    def ct(side, delta, iv, dte):
        return {"putCall": side, "delta": delta, "volatility": iv, "daysToExpiration": dte}

    chain = [
        # the ~30-day expiry (28d): usable 25Δ wings — RR = 17.0 − 21.5 = −4.5
        ct("CALL", 0.27, 17.0, 28), ct("PUT", -0.24, 21.5, 28),
        # noise wings far from 25Δ on the same expiry
        ct("CALL", 0.55, 15.0, 28), ct("PUT", -0.60, 25.0, 28),
        # the front (1d) and a far (60d) expiry are IGNORED even with perfect deltas
        ct("CALL", 0.25, 30.0, 1), ct("PUT", -0.25, 10.0, 1),
        ct("CALL", 0.25, 40.0, 60), ct("PUT", -0.25, 12.0, 60),
    ]
    out = compute_25d_risk_reversal(chain)
    assert out is not None and out["dte"] == 28
    assert out["rr_pts"] == -4.5
    assert out["call_iv_25d"] == 17.0 and out["put_iv_25d"] == 21.5

    # tolerance gate: nearest call delta 0.45 is > 0.10 from target -> fail closed
    bad = [ct("CALL", 0.45, 17.0, 28), ct("PUT", -0.25, 21.5, 28)]
    assert compute_25d_risk_reversal(bad) is None
    # one-sided chain, empty chain, missing greeks -> fail closed
    assert compute_25d_risk_reversal([ct("CALL", 0.25, 17.0, 28)]) is None
    assert compute_25d_risk_reversal([]) is None
    assert compute_25d_risk_reversal([{"putCall": "CALL", "daysToExpiration": 1}]) is None


def test_rc362_net_vanna_math_and_fail_closed():
    """RC-362: net vanna = Σcall_vanna − Σput_vanna shares per vol-pt (the book is per vol point
    since 2026-09-27, one unit everywhere), ×spot in $; None on empty/valueless book or missing
    spot."""
    import json
    from pathlib import Path
    import time_et
    from math_exposure_core import compute_exposures_by_strike, compute_net_vanna

    # Schwab's real CRWD chain (captured 2026-09-02), valued at its capture time; each strike's
    # net_vanna is the producer's own, the expectation is worked out here from the legs
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                    .read_text(encoding="utf-8"))
    real_now = time_et.now_et
    from datetime import datetime
    time_et.now_et = lambda: datetime(2026, 9, 2, 10, 5, tzinfo=time_et.ET)
    try:
        book, _ = compute_exposures_by_strike(fx["chain"], spot=fx["spot"])
    finally:
        time_et.now_et = real_now
    want = sum(b["call_vanna"] for b in book.values()) - sum(b["put_vanna"] for b in book.values())
    assert want != 0
    out = compute_net_vanna(book, 800.0)
    assert out["net_vanna_shares_per_volpt"] == round(want, 2)
    assert out["net_vanna_dollars_per_volpt"] == round(want * 800.0, 2)
    assert compute_net_vanna({}, 800.0) is None
    assert compute_net_vanna(book, None) is None
    assert compute_net_vanna({700.0: {"other": 1}}, 800.0) is None


def test_a_contract_with_no_usable_volatility_is_left_out_of_the_flip_and_counted():
    """M-10: Schwab sent volatility 0 on 5 SNDK contracts with open interest (real 09-25
    capture); the profile cannot price them. Operator 2026-09-30 (second ruling): the flip is
    the curve of the contracts that can be priced, from Schwab's own inputs, with no volatility
    made up for the rest; how many were left out stays in the diagnostics. Measured the same
    day: withholding the flip for them left $SPX, MU, NFLX and SMCI with none, for 1 to 16
    far-dated contracts holding at most 0.118% of open interest."""
    from datetime import timezone
    from math_levels import contract_inputs
    from terrain_engine import compute_terrain
    cap = json.loads((Path(__file__).parent / "fixtures" / "real_sndk_chain_no_volatility.json")
                     .read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(cap["ts_utc"], timezone.utc).astimezone(time_et.ET)
    priced, unpriced = contract_inputs(cap["chain"], now)
    assert (len(priced), unpriced) == (476, {"no_volatility": 5})
    served = compute_terrain("SNDK", cap["chain"], cap["spot"], now=now).to_dict()
    assert served["flip_diag"]["unpriced"] == {"no_volatility": 5}, "the count stays in the diagnostics"
    assert served["flip_diag"]["state"] == FLIP_FOUND and served["gamma_flip_reason"] == ""
    # the same flip as the chain without those contracts: nothing is filled in for them
    kept = [c for c in cap["chain"] if not contract_inputs([c], now)[1]]
    alone = compute_terrain("SNDK", kept, cap["spot"], now=now).to_dict()
    assert alone["flip_diag"]["unpriced"] == {}
    assert served["gamma_flip"] == alone["gamma_flip"] is not None
    assert served["flip_diag"]["curve_gamma_at_spot"] == alone["flip_diag"]["curve_gamma_at_spot"]
