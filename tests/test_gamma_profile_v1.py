"""FIND-GAMMA-FLIP-METHOD-V1 — canonical gamma profile (hypothetical-spot recompute).

Proven 2026-07-19 on a real SPY reference chain that the cumulative-sum method does NOT
reproduce the published profile (corr 0.086, never crosses zero, 2.19e9 divergence).
Only recomputing every contract's gamma at each candidate price reproduces the published
flip. These tests run on a REAL captured Schwab chain, never a hand-built one.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import time_et
from math_levels import (
    GAMMA_FLIP_UNAVAILABLE,
    GSF_STATE_BELOW_SUPPORT,
    GSF_STATE_OK,
    GSF_STATE_UNAVAILABLE,
    _interp_profile_at,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    contract_inputs,
    gamma_at_price,
    gamma_flip_from_profile,
)
from option_contract import OptionContract, read_chain, read_contract
from terrain_engine import compute_terrain

#: a REAL same-day-expiry SPY chain the capture daemon captured 2026-10-07 12:32 ET, valued at its
#: own capture time (a live 0DTE, ~3.5 h to Schwab's 16:00 EQO close)
_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_2026_10_07.json"
_DATA = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
NOW = datetime.fromtimestamp(_DATA["ts_utc"], time_et.ET)


def _load_real_chain() -> tuple[list[OptionContract], float]:
    return read_chain(_DATA["chain"]), float(_DATA["spot"])


def test_profile_on_real_chain_is_finite_and_spans_spot() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, now=NOW)
    assert len(prof) == 241
    assert all(math.isfinite(v) for _, v in prof)
    prices = [p for p, _ in prof]
    assert prices[0] < spot < prices[-1]
    assert prices == sorted(prices)


def test_profile_uses_dealer_sign_convention() -> None:
    """Calls add, puts subtract: an all-call book must be positive at every price."""
    chain, spot = _load_real_chain()
    calls = [c for c in chain if c.side == "CALL"]
    assert calls, "fixture must contain calls"
    prof = compute_gamma_profile(calls, spot, now=NOW)
    assert prof and all(v >= 0 for _, v in prof)


def test_flip_is_interpolated_within_the_profile_span() -> None:
    """RC-467: the real chain MUST yield a flip.

    The old `if flip is not None` guard let a flip-always-None regression pass silently while
    asserting nothing. MEASURED on this
    fixture at its capture time: 241 profile points, 1 sign crossing, flip = 779.03, inside
    the span. Existence is pinned; the exact value is not (it moves with vol/time inputs) -
    span containment is the invariant.
    """
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, now=NOW)
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None, (
        "the real fixture chain has a zero crossing (measured flip 779.03); a None flip "
        "here means the profile or crossing detection regressed"
    )
    assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_v2_fails_closed_without_inputs() -> None:
    for contracts, spot in (
        ([], 100.0),
        (None, 100.0),
        ([read_contract({"strikePrice": 100})], 0.0),
    ):
        flip, confidence, _diag = compute_gamma_flip_v2(contracts, spot, profile=[])
        assert flip is None and confidence == GAMMA_FLIP_UNAVAILABLE


def test_regime_is_defined_even_when_the_profile_never_crosses_zero() -> None:
    """RC-11: no zero-crossing means no FLIP LEVEL, never an unknown regime.

    A chain whose dealer gamma holds one sign at every price has an unambiguous regime --
    arguably more certain than one with a flip beside spot. Before this was corrected, 20
    of 51 live tickers reported UNAVAILABLE while their gamma was uniformly signed.
    """
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, now=NOW)
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
    assert gamma_at_price(prof, 50.0) == -2.0  # below the profile -> first value
    assert gamma_at_price(prof, 500.0) == 4.0  # above -> last value
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
    """Cursor audit 2026-07-20: a profile STARTING at exactly zero returned None.

    Both strict-sign conditions are false at v0==0, so the boundary vanished.
    """
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
        (round(lo_px + (hi_px - lo_px) * i / steps, 4), lo_v + (hi_v - lo_v) * i / steps)
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
    assert flip is not None and out["gsf"] > flip  # above the flip
    assert flip < out["gsf"] < 105.0  # between flip and spot
    assert abs(out["gsf"] - 100.0) < 0.5  # analytic crossing
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
    assert out["grc"] is not None and out["grc"] > 106.0  # beyond the peak/wall
    n_spot = out["n_at_spot"]
    # value at the ceiling is ~phi * N(spot)
    assert abs(_interp_profile_at(prof, out["grc"]) - 0.5 * n_spot) / n_spot < 0.05


def test_below_support_state_never_fabricates_a_price():
    # Negative-gamma regime at spot: honest STATE, both levels None.
    prof = _linear_profile(90.0, 110.0, -6e9, -1e9)
    out = compute_gamma_support_levels(prof, 100.0)
    assert out["state"] == GSF_STATE_BELOW_SUPPORT
    assert out["gsf"] is None and out["grc"] is None


def test_unavailable_on_empty_or_bad_inputs():
    assert compute_gamma_support_levels([], 100.0)["state"] == GSF_STATE_UNAVAILABLE
    assert (
        compute_gamma_support_levels(_linear_profile(90, 110, 1e9, 2e9), None)["state"]
        == GSF_STATE_UNAVAILABLE
    )
    assert (
        compute_gamma_support_levels(_linear_profile(90, 110, 1e9, 2e9), -5)["state"]
        == GSF_STATE_UNAVAILABLE
    )


def test_the_flip_counts_the_contracts_it_could_not_price():
    """M-10: the served flip counts the contracts it could not price, and says why.

    The profile cannot price a contract with open interest whose volatility Schwab sent as
    -999; one beyond a year runs to Schwab's own expirationDate. The served flip says how
    many were left out and why.
    Real captures of 2026-10-07: NFLX (10:32 ET; PM) -- on 2026-10-16, 100 contracts with open
    interest and a volatility; on 2027-12-17 and 2028-01-21, 585 with a volatility and 8 sent
    -999 -- and $SPX's AM-settled 2027-12-17 expiry (10:37 ET; 288 with open interest).
    """
    fx = Path(__file__).parent / "fixtures"
    nflx = json.loads(
        (fx / "real_nflx_chain_2026_10_07_three_expiries.json").read_text(encoding="utf-8")
    )
    spx = json.loads((fx / "real_spx_chain_2026_10_07_2027_12_17.json").read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(nflx["ts_utc"], time_et.ET)
    nflx_chain = read_chain(nflx["chain"])
    priced, unpriced = contract_inputs(nflx_chain, now)
    assert (len(priced), unpriced) == (685, {"no_volatility": 8})
    far = next(ct for ct in nflx["chain"] if ct["expirationDate"].startswith("2028-01-21"))
    assert (
        time_et.time_to_expiry_years(
            far["expirationDate"], now, settlement_type=far["settlementType"]
        )
        == (datetime.fromisoformat(far["expirationDate"]).timestamp() - now.timestamp())
        / time_et.YEAR_SECONDS
    )
    snap = compute_terrain("NFLX", nflx_chain, nflx["spot"], now=now)
    assert snap.to_dict()["flip_diag"]["unpriced"] == {"no_volatility": 8}
    at = datetime.fromtimestamp(spx["ts_utc"], time_et.ET)
    assert contract_inputs(read_chain(spx["chain"]), at)[1] == {}
