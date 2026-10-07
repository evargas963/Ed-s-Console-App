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
    GAMMA_FLIP_UNAVAILABLE,
    GSF_STATE_BELOW_SUPPORT,
    GSF_STATE_OK,
    GSF_STATE_UNAVAILABLE,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    gamma_at_price,
    gamma_flip_from_profile,
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
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None, (
        "the real fixture chain has a zero crossing (measured flip 761.0); a None flip "
        "here means the profile or crossing detection regressed"
    )
    assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_v2_fails_closed_without_inputs() -> None:
    for contracts, spot in (([], 100.0), (None, 100.0), ([{"strikePrice": 100}], 0.0)):
        flip, confidence, _diag = compute_gamma_flip_v2(contracts, spot, profile=[])
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
    assert gamma_flip_from_profile([(100.0, 5.0), (101.0, 7.0)], 100.5) is None
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


# ── FLIP DETECTION IS DIRECTION-BLIND (Bugbot 2026-07-20, HIGH — confirmed) ──
# `v0 < 0 <= v1` found only rising neg->pos crossings. A profile that is long-gamma below
# and short-gamma above (pos->neg) has a real regime boundary that returned None — the
# flip vanished and the verdict claimed "no crossing" on a chain that crosses.
# (gamma_flip_from_profile is imported at the top of this file.)


def test_flip_detects_positive_to_negative_crossing():
    prof = [(90.0, 5.0), (95.0, 2.0), (100.0, -1.0), (105.0, -4.0)]
    flip = gamma_flip_from_profile(prof, 97.0)
    assert flip is not None, "pos->neg crossing missed — the direction-blind defect"
    assert 95.0 < flip < 100.0, flip


def test_flip_still_detects_negative_to_positive():
    prof = [(90.0, -4.0), (95.0, -1.0), (100.0, 2.0), (105.0, 5.0)]
    flip = gamma_flip_from_profile(prof, 97.0)
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
    assert gamma_flip_from_profile([(90.0, -1.0), (100.0, -2.0)], 95.0) is None
    assert gamma_flip_from_profile([(90.0, 1.0), (100.0, 2.0)], 95.0) is None
    assert gamma_flip_from_profile([], 95.0) is None


def test_flip_zero_touching_profile_start_is_the_boundary():
    """Cursor audit 2026-07-20: a profile STARTING at exactly zero returned None —
    both strict-sign conditions are false at v0==0, so the boundary vanished."""
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, 1.0), (120.0, 2.0)], 105.0) == 100.0
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, -1.0)], 105.0) == 100.0
    # flat zero segments are not crossings
    assert gamma_flip_from_profile([(100.0, 0.0), (110.0, 0.0)], 105.0) is None
    # segment ENDING at zero still interpolates to the zero point
    assert gamma_flip_from_profile([(100.0, -1.0), (110.0, 0.0), (120.0, 1.0)], 110.0) == 110.0


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


def test_rc357_zero_dte_gamma_share_ratio_and_fail_closed():
    """RC-357: share = sum|0DTE net_gex_1pct| / sum|all net_gex_1pct|; None when the
    full book is empty or has no measurable gamma — never a fabricated 0%."""
    from math_exposure_core import compute_zero_dte_gamma_share

    all_book = {700.0: {"net_gex_1pct": 6e9}, 705.0: {"net_gex_1pct": -2e9},
                710.0: {"net_gex_1pct": 2e9}}
    zero_book = {700.0: {"net_gex_1pct": 4e9}, 705.0: {"net_gex_1pct": -1e9}}
    assert compute_zero_dte_gamma_share(all_book, zero_book) == 50.0   # 5e9/10e9
    assert compute_zero_dte_gamma_share(all_book, {}) == 0.0           # genuine zero 0DTE
    assert compute_zero_dte_gamma_share({}, zero_book) is None         # empty full book
    assert compute_zero_dte_gamma_share({700.0: {"net_gex_1pct": 0.0}}, {}) is None


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


def test_the_flip_counts_the_contracts_it_could_not_price():
    """M-10: Schwab sent volatility 0 on 5 SNDK contracts with open interest (real 09-25
    capture). The profile cannot price them; the served flip says how many and why."""
    from datetime import timezone
    from math_levels import contract_inputs
    from terrain_engine import compute_terrain
    cap = json.loads((Path(__file__).parent / "fixtures" / "real_sndk_chain_no_volatility.json")
                     .read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(cap["ts_utc"], timezone.utc).astimezone(time_et.ET)
    priced, unpriced = contract_inputs(cap["chain"], now)
    assert (len(priced), unpriced) == (476, {"no_volatility": 5})
    snap = compute_terrain("SNDK", cap["chain"], cap["spot"], now=now)
    assert snap.to_dict()["flip_diag"]["unpriced"] == {"no_volatility": 5}
