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
    """RC-467: the real chain MUST yield a flip - the old `if flip is not None` guard let
    a flip-always-None regression pass silently while asserting nothing. MEASURED on this
    fixture under the pinned session clock: 241 profile points, 2 sign crossings,
    flip = 761.0, inside the span. Existence is pinned; the exact value is not (it moves
    with vol/time inputs) - span containment is the invariant."""
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, span_pct=0.15, steps=240)
    flip = gamma_flip_from_profile(prof)
    assert flip is not None, (
        "the real fixture chain has a zero crossing (measured flip 761.0); a None flip "
        "here means the profile or crossing detection regressed"
    )
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


def test_rc354_gsf_grc_wired_producer_to_consumer():
    """RC-354 end-to-end wiring: terrain carries the fields fail-closed, the /api/state
    stamp writes them from the SSOT terrain book, and both UI surfaces consume them."""
    from terrain_engine import compute_terrain

    # dataclass carries the fields, defaulting fail-closed
    snap = compute_terrain("SPY", [], 780.0)          # no chain -> _unavailable path
    assert hasattr(snap, "gsf") and hasattr(snap, "grc")
    assert snap.gsf is None and snap.grc is None
    assert snap.gsf_state == "UNAVAILABLE"

    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    for key in ('md["kl_gsf"]', 'md["kl_grc"]', 'md["kl_gsf_state"]', 'md["kl_gsf_state_disp"]'):
        assert key in srv, f"server must stamp {key} from the terrain book"

    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "key: 'kl_gsf'" in html and "key: 'kl_grc'" in html
    assert "Gamma Support Floor" in html and "Gamma Resistance Ceiling" in html
    chart = Path(__file__).resolve().parent.parent.joinpath("static", "chart.html").read_text(encoding="utf-8")
    assert "'gsf', 'GSF'" in chart and "'grc', 'GRC'" in chart


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


def test_rc357_zero_dte_share_wired_end_to_end():
    """RC-357 wiring: terrain field fail-closed, /api/state stamp, Console row."""
    from terrain_engine import compute_terrain

    snap = compute_terrain("SPY", [], 780.0)
    assert hasattr(snap, "zero_dte_gamma_share_pct")
    assert snap.zero_dte_gamma_share_pct is None
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    assert 'md["kl_zero_dte_share"]' in srv
    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "0DTE Gamma Share" in html and "kl_zero_dte_share" in html


def test_rc358_25d_risk_reversal_front_expiry_and_fail_closed():
    """RC-358: RR = IV(25Δ call) − IV(25Δ put) on the FRONT expiry, tolerance-gated;
    an unusable wing yields None — never a fabricated skew."""
    from math_volatility import compute_25d_risk_reversal

    def ct(side, delta, iv, dte):
        return {"putCall": side, "delta": delta, "volatility": iv, "daysToExpiration": dte}

    chain = [
        # front expiry (1d): usable 25Δ wings — RR = 17.0 − 21.5 = −4.5
        ct("CALL", 0.27, 17.0, 1), ct("PUT", -0.24, 21.5, 1),
        # noise wings far from 25Δ on the front
        ct("CALL", 0.55, 15.0, 1), ct("PUT", -0.60, 25.0, 1),
        # next expiry (7d) must be IGNORED even with perfect deltas
        ct("CALL", 0.25, 30.0, 7), ct("PUT", -0.25, 10.0, 7),
    ]
    out = compute_25d_risk_reversal(chain)
    assert out is not None and out["dte"] == 1
    assert out["rr_pts"] == -4.5
    assert out["call_iv_25d"] == 17.0 and out["put_iv_25d"] == 21.5

    # tolerance gate: nearest call delta 0.45 is > 0.10 from target -> fail closed
    bad = [ct("CALL", 0.45, 17.0, 1), ct("PUT", -0.25, 21.5, 1)]
    assert compute_25d_risk_reversal(bad) is None
    # one-sided chain, empty chain, missing greeks -> fail closed
    assert compute_25d_risk_reversal([ct("CALL", 0.25, 17.0, 1)]) is None
    assert compute_25d_risk_reversal([]) is None
    assert compute_25d_risk_reversal([{"putCall": "CALL", "daysToExpiration": 1}]) is None


def test_rc358_rr25_wired_end_to_end():
    from terrain_engine import compute_terrain

    snap = compute_terrain("SPY", [], 780.0)
    assert hasattr(snap, "rr_25d") and snap.rr_25d is None
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    assert 'md["kl_rr25_pts"]' in srv and 'md["kl_rr25_dte"]' in srv
    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "25Δ Risk Reversal" in html and "kl_rr25_pts" in html


def test_rc362_net_vanna_math_and_fail_closed():
    """RC-362: net vanna = (Σcall_vanna − Σput_vanna)/100 shares per vol-pt, ×spot in $;
    None on empty/valueless book or missing spot."""
    from math_exposure_core import compute_net_vanna

    book = {700.0: {"call_vanna": 5000.0, "put_vanna": -3000.0},
            705.0: {"call_vanna": 1000.0, "put_vanna": -1000.0}}
    out = compute_net_vanna(book, 800.0)
    # net shares/volpt = (6000 − (−4000))/100 = 100; dollars = 100×800 = 80,000
    assert out == {"net_vanna_dollars_per_volpt": 80000.0,
                   "net_vanna_shares_per_volpt": 100.0}
    assert compute_net_vanna({}, 800.0) is None
    assert compute_net_vanna(book, None) is None
    assert compute_net_vanna({700.0: {"other": 1}}, 800.0) is None


def test_rc362_vanna_wired_end_to_end():
    from terrain_engine import compute_terrain

    snap = compute_terrain("SPY", [], 780.0)
    assert hasattr(snap, "vanna_agg") and snap.vanna_agg is None
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    assert 'md["kl_vanna_net_dollars"]' in srv
    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "Net Vanna" in html and "kl_vanna_net_dollars" in html
    assert "/day" in html    # charm rate dollarized


def test_rc361_net_dex_dollars_sign_model_and_fail_closed():
    """RC-361: net DEX = Σ call_dex − Σ put_dex (dealer +call/−put; negative put deltas
    flip to the dealer side correctly); None on an empty/valueless book."""
    from math_exposure_core import compute_net_dex_dollars

    book = {700.0: {"call_dex_dollars": 5e8, "put_dex_dollars": -3e8},
            705.0: {"call_dex_dollars": 2e8, "put_dex_dollars": -1e8}}
    out = compute_net_dex_dollars(book)
    assert out == {"net_dex": 1.1e9, "call_dex": 7e8, "put_dex": -4e8}
    assert compute_net_dex_dollars({}) is None
    assert compute_net_dex_dollars({700.0: {"other": 1}}) is None


def test_rc361_dex_wired_end_to_end():
    from terrain_engine import compute_terrain

    snap = compute_terrain("SPY", [], 780.0)
    assert hasattr(snap, "dex_dollars") and snap.dex_dollars is None
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    assert 'md["kl_dex_net"]' in srv
    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "Net DEX" in html and "kl_dex_net" in html


def test_rc359_delta_oi_walls_build_unwind_and_fail_closed():
    """RC-359: ΔOI walls — biggest call/put OI builds + biggest unwind; None until a
    prior session exists; a strike absent yesterday diffs against 0 (genuinely new)."""
    from math_exposure_core import compute_delta_oi_walls

    prev = {700.0: (1000.0, 500.0), 705.0: (2000.0, 800.0)}
    today = {700.0: (1500.0, 450.0),          # call +500, put −50
             705.0: (1800.0, 3000.0),         # call −200, put +2200
             710.0: (900.0, 100.0)}           # new strike: +900 / +100 vs 0
    out = compute_delta_oi_walls(today, prev)
    assert out is not None
    assert out["call_build_strike"] == 710.0 and out["call_build_doi"] == 900
    assert out["put_build_strike"] == 705.0 and out["put_build_doi"] == 2200
    assert out["unwind_strike"] is None       # no strike shrank NET (705: -200+2200>0)

    shrink = compute_delta_oi_walls({700.0: (100.0, 100.0)}, {700.0: (1000.0, 500.0)})
    assert shrink["unwind_strike"] == 700.0 and shrink["unwind_doi"] == -1300
    assert shrink["call_build_strike"] is None

    assert compute_delta_oi_walls(today, {}) is None   # no prior session -> fail closed
    assert compute_delta_oi_walls({}, prev) is None


def test_rc359_oi_banking_and_prev_session_reader(tmp_path):
    import sqlite3

    from db import EdDB

    d = EdDB(tmp_path / "oi.db", allow_noncanonical=True)
    d.bank_daily_strike_oi("SPY", "2026-08-14", [(700.0, 1000.0, 500.0)], 1.0)
    d.bank_daily_strike_oi("SPY", "2026-08-14", [(700.0, 1100.0, 500.0)], 2.0)  # upsert wins
    d.bank_daily_strike_oi("SPY", "2026-08-15", [(700.0, 1500.0, 450.0)], 3.0)
    prev = d.prev_session_strike_oi("SPY", "2026-08-15")
    assert prev == {700.0: (1100.0, 500.0)}            # most recent BEFORE the 15th, upserted
    assert d.prev_session_strike_oi("SPY", "2026-08-14") == {}   # nothing before day 1
    d.bank_daily_strike_oi("SPY", "2026-08-15", [], 4.0)          # empty writes nothing
    with sqlite3.connect(tmp_path / "oi.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM oi_daily").fetchone()[0] == 2


def test_rc359_doi_wired_end_to_end():
    from terrain_engine import compute_terrain

    snap = compute_terrain("SPY", [], 780.0)
    assert hasattr(snap, "oi_by_strike")
    assert "oi_by_strike" not in snap.to_dict()        # heavy field stays out of the poll
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    for k in ('bank_daily_strike_oi(', 'prev_session_strike_oi(', 'md["kl_doi_call_strike"]',
              'md["kl_doi_put_strike"]', 'md["kl_doi_unwind_strike"]'):
        assert k in srv, f"server must wire {k}"
    html = Path(__file__).resolve().parent.parent.joinpath("static", "index.html").read_text(encoding="utf-8")
    assert "ΔOI Call Build" in html and "ΔOI Put Build" in html and "kl_doi_call_strike" in html


def test_rc354_iv_banking_upsert_last_write_wins(tmp_path):
    """RC-354b: iv_daily banks one row per (ticker, ET date); the LAST write of the
    session wins so the banked value converges to the closing ATM IV (IVR convention)."""
    import sqlite3

    from db import EdDB

    d = EdDB(tmp_path / "iv.db", allow_noncanonical=True)
    d.bank_daily_atm_iv("SPY", "2026-08-15", 18.5, 1, "IV_SIGMA_1D", 1.0)
    d.bank_daily_atm_iv("SPY", "2026-08-15", 21.0, 1, "IV_SIGMA_1D", 2.0)  # later wins
    d.bank_daily_atm_iv("SPY", "2026-08-16", 19.0, 1, "IV_SIGMA_1D", 3.0)
    d.bank_daily_atm_iv("QQQ", "2026-08-15", 22.5, 1, "IV_SIGMA_1D", 4.0)
    with sqlite3.connect(tmp_path / "iv.db") as conn:
        rows = conn.execute(
            "SELECT ticker, date_et, atm_iv_pct FROM iv_daily ORDER BY ticker, date_et"
        ).fetchall()
    assert rows == [("QQQ", "2026-08-15", 22.5),
                    ("SPY", "2026-08-15", 21.0),   # upsert: closing value, not first
                    ("SPY", "2026-08-16", 19.0)]
    # the terrain-refresh hook is wired (source assertion on the one write site)
    srv = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    assert "bank_daily_atm_iv(" in srv and "iv_pct_atm" in srv


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
