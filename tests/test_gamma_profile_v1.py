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
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_UNAVAILABLE,
    GSF_STATE_BELOW_SUPPORT,
    GSF_STATE_OK,
    GSF_STATE_UNAVAILABLE,
    bs_gamma,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    gamma_at_price,
    gamma_flip_from_profile,
    snap_level_to_shelf_strike,
)

import pytest
from datetime import datetime
import time_et


@pytest.fixture(autouse=True)
def _pin_now_to_fixture_session(monkeypatch):
    # The fixture is a REAL 0DTE SPY chain captured 2026-07-17. The canonical intraday
    # time-to-expiry (time_et.time_to_expiry_years) measures from now_et() to the session
    # close, so replaying it today reads it as long-expired and drops every contract. Pin the
    # clock to mid-session on the fixture's expiry day so it is a live 0DTE (~6h to close).
    monkeypatch.setattr(time_et, "now_et", lambda: datetime(2026, 7, 17, 10, 0, tzinfo=time_et.ET))


_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_bs_gamma_peaks_at_the_money() -> None:
    """Gamma must peak ATM and vanish far OTM — the shape the whole profile depends on."""
    atm = bs_gamma(100.0, 100.0, 0.02, 0.20)
    otm = bs_gamma(100.0, 130.0, 0.02, 0.20)
    assert atm is not None and otm is not None
    assert atm > otm
    assert bs_gamma(100.0, 100.0, 0.0, 0.20) is None      # expired -> refuse
    assert bs_gamma(100.0, 100.0, 0.02, 0.0) is None      # no vol -> refuse


def test_profile_on_real_chain_is_finite_and_spans_spot() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, span_pct=0.15, steps=120)
    assert len(prof) == 121
    assert all(math.isfinite(v) for _, v in prof)
    prices = [p for p, _ in prof]
    assert prices[0] < spot < prices[-1]
    assert prices == sorted(prices)


def test_profile_uses_dealer_sign_convention() -> None:
    """Calls add, puts subtract: an all-call book must be positive at every price."""
    chain, spot = _load_real_chain()
    calls = [c for c in chain if str(c.get("putCall", "")).upper().startswith("C")]
    assert calls, "fixture must contain calls"
    prof = compute_gamma_profile(calls, spot, span_pct=0.10, steps=40)
    assert prof and all(v >= 0 for _, v in prof)


def test_flip_is_interpolated_within_the_profile_span() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, span_pct=0.15, steps=240)
    flip = gamma_flip_from_profile(prof)
    if flip is not None:
        assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_returns_none_when_no_zero_crossing() -> None:
    assert gamma_flip_from_profile([(100.0, 5.0), (101.0, 7.0)]) is None
    assert gamma_flip_from_profile([]) is None


def test_narrow_chain_flip_is_reported_low_confidence() -> None:
    """The live 20-strike chain spans only ~+/-1.3%; its flip must never be served as
    trustworthy (measured error vs full-chain reference: 770.35 vs 745.61)."""
    chain, spot = _load_real_chain()
    flip, confidence, diag = compute_gamma_flip_v2(chain, spot)
    assert confidence == GAMMA_FLIP_NARROW
    assert diag["span_below_pct"] < 0.05 or diag["span_above_pct"] < 0.05
    assert diag["n_strikes"] > 0 and diag["strike_lo"] < diag["strike_hi"]


def test_flip_v2_fails_closed_without_inputs() -> None:
    for contracts, spot in (([], 100.0), (None, 100.0), ([{"strikePrice": 100}], 0.0)):
        flip, confidence, _diag = compute_gamma_flip_v2(contracts, spot)
        assert flip is None and confidence == GAMMA_FLIP_UNAVAILABLE

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
    assert gamma_flip_from_profile([(100.0, 5.0), (101.0, 7.0)]) is None
    assert gamma_at_price([(100.0, 5.0), (101.0, 7.0)], 100.5) == 6.0


def test_gamma_at_price_clamps_outside_the_profile() -> None:
    prof = [(100.0, -2.0), (110.0, 4.0)]
    assert gamma_at_price(prof, 50.0) == -2.0     # below the profile -> first value
    assert gamma_at_price(prof, 500.0) == 4.0     # above -> last value
    assert gamma_at_price([], 100.0) is None
    assert gamma_at_price(prof, None) is None


# ── STRIKE WIDTH IS DERIVED, NOT TABULATED (root fix for RC-12) ─────────────
# RC-12 found the cause -- "a fixed strike count cannot satisfy a percentage-based span
# requirement across instruments with different strike spacing" -- then answered it with a
# hardcoded table for three tickers, leaving every other ticker on a fixed 40. MEASURED
# across 52 stored chains 2026-07-20: that table was wrong in BOTH directions. $SPX needed
# 150 and got 40; IWM needed 30 and got 80; ~48 equities needed under 20 and got 40.

from math_levels import (
    GAMMA_FLIP_MIN_SPAN_PCT,
    infer_strike_increment,
    required_strike_count,
)


def test_required_count_actually_spans_the_trust_bar():
    """The whole point: the derived count must COVER +/-5%, measured, not asserted."""
    for spot, incr in ((742.49, 1.0), (701.69, 1.0), (294.32, 1.0),
                       (7457.69, 5.0), (205.20, 2.5), (17.84, 0.5)):
        n = required_strike_count(spot, incr)
        half_span_points = (n - 1) / 2.0 * incr      # strikes centred on spot
        assert half_span_points >= GAMMA_FLIP_MIN_SPAN_PCT * spot, (
            f"spot={spot} incr={incr}: {n} strikes reaches only "
            f"{half_span_points / spot:.3%}, under the {GAMMA_FLIP_MIN_SPAN_PCT:.0%} bar")


def test_same_price_different_spacing_needs_different_counts():
    """This is the RC-12 root cause in one assertion: spacing drives the count."""
    tight = required_strike_count(700.0, 1.0)
    wide = required_strike_count(700.0, 5.0)
    assert tight > wide, (tight, wide)
    assert required_strike_count(700.0, 1.0) > required_strike_count(70.0, 1.0)


def test_measured_real_instruments_against_the_replaced_table():
    """Values MEASURED from stored chains 2026-07-20, not invented for the test."""
    assert required_strike_count(7457.69, 5.0) > 100      # $SPX: table gave 40
    assert required_strike_count(294.32, 1.0) < 80        # IWM: table gave 80
    assert required_strike_count(205.20, 2.5) < 40        # NVDA: table gave 40
    assert required_strike_count(742.49, 1.0) > 40        # SPY: a flat 40 is too narrow


def test_unknown_geometry_returns_none_never_a_guess():
    """A fabricated width would be silently wrong; absence must read as absence."""
    assert required_strike_count(None, 1.0) is None
    assert required_strike_count(742.0, None) is None
    for bad in (0, -1.0):
        assert required_strike_count(bad, 1.0) is None
        assert required_strike_count(742.0, bad) is None


def test_increment_inferred_by_median_resists_gaps():
    """Illiquid far strikes leave wide gaps; a mean would understate the count needed."""
    even = [{"strikePrice": p} for p in (100, 102.5, 105, 107.5, 110)]
    assert infer_strike_increment(even) == 2.5
    gapped = [{"strikePrice": p} for p in (100, 102.5, 105, 107.5, 110, 160)]
    assert infer_strike_increment(gapped) == 2.5          # the 50-point gap is ignored
    assert infer_strike_increment([{"strikePrice": 100}, {"strikePrice": 105}]) is None
    assert infer_strike_increment([]) is None


# ── FLIP DETECTION IS DIRECTION-BLIND (Bugbot 2026-07-20, HIGH — confirmed) ──
# `v0 < 0 <= v1` found only rising neg->pos crossings. A profile that is long-gamma below
# and short-gamma above (pos->neg) has a real regime boundary that returned None — the
# flip vanished and the verdict claimed "no crossing" on a chain that crosses.
# (gamma_flip_from_profile is imported at the top of this file.)


def test_flip_detects_positive_to_negative_crossing():
    prof = [(90.0, 5.0), (95.0, 2.0), (100.0, -1.0), (105.0, -4.0)]
    flip = gamma_flip_from_profile(prof)
    assert flip is not None, "pos->neg crossing missed — the direction-blind defect"
    assert 95.0 < flip < 100.0, flip


def test_flip_still_detects_negative_to_positive():
    prof = [(90.0, -4.0), (95.0, -1.0), (100.0, 2.0), (105.0, 5.0)]
    flip = gamma_flip_from_profile(prof)
    assert flip is not None and 95.0 < flip < 100.0, flip


def test_flip_picks_the_crossing_nearest_spot():
    """Multi-cross profile: the boundary that governs the trade is the one beside spot."""
    prof = [(80.0, -2.0), (90.0, 3.0), (100.0, 1.0), (110.0, -2.0), (120.0, -5.0)]
    near_low = gamma_flip_from_profile(prof, spot=85.0)
    near_high = gamma_flip_from_profile(prof, spot=108.0)
    assert near_low is not None and 80.0 < near_low < 90.0, near_low
    assert near_high is not None and 100.0 < near_high < 110.0, near_high
    assert near_low != near_high


def test_flip_none_when_one_signed():
    assert gamma_flip_from_profile([(90.0, -1.0), (100.0, -2.0)]) is None
    assert gamma_flip_from_profile([(90.0, 1.0), (100.0, 2.0)]) is None
    assert gamma_flip_from_profile([]) is None


def test_flip_zero_touching_profile_start_is_the_boundary():
    """Cursor audit 2026-07-20: a profile STARTING at exactly zero returned None —
    both strict-sign conditions are false at v0==0, so the boundary vanished."""
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, 1.0), (120.0, 2.0)]) == 100.0
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, -1.0)]) == 100.0
    # flat zero segments are not crossings
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, 0.0)]) is None
    # segment ENDING at zero still interpolates to the zero point
    assert gamma_flip_from_profile([(100.0, -1.0), (110.0, 0.0), (120.0, 1.0)]) == 110.0


# ── TU-04: sign-model A/B (parallel profile, never a silent swap) ────────────

def test_sign_model_default_is_naive_and_unknown_raises():
    import pytest
    from math_levels import SIGN_MODEL_NAIVE, compute_gamma_profile
    chain, spot = _load_real_chain()
    assert compute_gamma_profile(chain, spot) == compute_gamma_profile(
        chain, spot, sign_model=SIGN_MODEL_NAIVE)
    with pytest.raises(ValueError):
        compute_gamma_profile(chain, spot, sign_model="vibes")


def test_empirical_prior_flips_puts_to_dealer_long_on_real_chain():
    from math_levels import SIGN_MODEL_EMPIRICAL_PRIOR, compute_gamma_profile
    chain, spot = _load_real_chain()
    calls = [c for c in chain if str(c.get("putCall")).upper() == "CALL"]
    naive = compute_gamma_profile(chain, spot)
    prior = compute_gamma_profile(chain, spot, sign_model=SIGN_MODEL_EMPIRICAL_PRIOR)
    calls_only = compute_gamma_profile(calls, spot)
    assert naive and len(naive) == len(prior) == len(calls_only)
    for (_px, v_n), (_, v_p), (_, v_c) in zip(naive, prior, calls_only, strict=True):
        put_leg = v_c - v_n              # the put gamma naive SUBTRACTED at this price
        assert v_p >= v_n                # flipping puts positive can only raise the curve
        import math as _m
        assert _m.isclose(v_p, v_c + put_leg, rel_tol=1e-9, abs_tol=1e-3), (
            "empirical_prior must ADD exactly the put gamma naive subtracted")
    # calls-only chain: the models agree exactly (the flip only touches puts)
    co_prior = compute_gamma_profile(calls, spot, sign_model=SIGN_MODEL_EMPIRICAL_PRIOR)
    assert co_prior == calls_only


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
    flip = gamma_flip_from_profile(prof, 105.0)
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
    from math_levels import _interp_profile_at
    assert abs(_interp_profile_at(prof, out["grc"]) - 0.5 * n_spot) / n_spot < 0.05


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


def test_snap_to_shelf_only_within_tolerance_and_side():
    # significant shelf strike at 99.90 within 0.25% of a 100.05 level -> snaps below spot
    snapped = snap_level_to_shelf_strike(
        100.05, {99.90: 5e9, 101.0: 6e9}, side="below", spot=105.0, theta=1e9)
    assert snapped == 99.90
    # insignificant strike (below theta) never snaps
    assert snap_level_to_shelf_strike(
        100.05, {99.90: 1e8}, side="below", spot=105.0, theta=1e9) == 100.05
    # wrong side (above spot for a floor) never snaps
    assert snap_level_to_shelf_strike(
        104.9, {105.2: 5e9}, side="below", spot=105.0, theta=1e9) == 104.9
    # None passes through fail-closed
    assert snap_level_to_shelf_strike(None, {100.0: 5e9}, side="below", spot=105.0, theta=1e9) is None
