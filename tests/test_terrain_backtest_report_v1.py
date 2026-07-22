"""PDCA verdict + history mechanics for the daily terrain scorecard.

The decision rules ARE the product (operator 2026-07-20: "how do we turn this into
something real?") — so they are pure functions with boundary tests, not prose.
"""
from __future__ import annotations

from tools.terrain_backtest_report_v1 import (
    _regime_for_scoring,
    _sign_ab,
    PDCA_ADJUST_PTS,
    PDCA_PROMOTE_PTS,
    PDCA_WINDOW_SESSIONS,
    pdca_verdict,
    rolling_gap,
    wall_hold_stats,
)


def test_demoted_display_regime_still_scores_from_raw_sign():
    """SIGN-DEMOTION must not starve its own restoration gate: SIGN_UNPROVEN rows
    keep scoring from the raw naive sign (this tool IS the restoration test)."""
    assert _regime_for_scoring("SIGN_UNPROVEN", -3.9e9) == "SHORT_GAMMA_TREND"
    assert _regime_for_scoring("SIGN_UNPROVEN", 2.5e8) == "LONG_GAMMA_CHOP"
    assert _regime_for_scoring("LONG_GAMMA_CHOP", None) == "LONG_GAMMA_CHOP"
    assert _regime_for_scoring("SHORT_GAMMA_TREND", 1.0) == "SHORT_GAMMA_TREND"
    assert _regime_for_scoring("SIGN_UNPROVEN", None) is None   # no sign -> no row
    assert _regime_for_scoring("SIGN_UNPROVEN", 0.0) is None
    assert _regime_for_scoring("UNAVAILABLE", -1.0) is None     # untrusted stays out


def test_verdict_accumulates_until_window_fills():
    colour, action = pdca_verdict(10.0, PDCA_WINDOW_SESSIONS - 1)
    assert colour == "YELLOW" and "ACCUMULATE" in action, (
        "a huge gap on a thin window must NOT trigger ACT — Deming's tampering rule")


def test_verdict_boundaries_fire_the_right_rule():
    assert pdca_verdict(PDCA_PROMOTE_PTS, PDCA_WINDOW_SESSIONS)[0] == "GREEN"
    assert "PROMOTE" in pdca_verdict(PDCA_PROMOTE_PTS, PDCA_WINDOW_SESSIONS)[1]
    assert pdca_verdict(PDCA_ADJUST_PTS, PDCA_WINDOW_SESSIONS)[0] == "RED"
    assert "ADJUST" in pdca_verdict(PDCA_ADJUST_PTS, PDCA_WINDOW_SESSIONS)[1]
    mid = pdca_verdict(0.0, PDCA_WINDOW_SESSIONS)
    assert mid[0] == "YELLOW" and "REFINE" in mid[1]
    broken = pdca_verdict(None, PDCA_WINDOW_SESSIONS)
    assert broken[0] == "RED" and "CHECK BROKEN" in broken[1]


def test_rolling_gap_is_hit_weighted_not_pct_averaged():
    """A 1-row day must not swing the window like a 500-row day."""
    hist = [
        {"day": "d1", "trusted_n": 500, "trusted_hit_pct": 60.0,
         "placebo_n": 500, "placebo_hit_pct": 50.0},
        {"day": "d2", "trusted_n": 1, "trusted_hit_pct": 0.0,
         "placebo_n": 1, "placebo_hit_pct": 100.0},
    ]
    gap, sessions = rolling_gap(hist, window=20)
    assert sessions == 2
    # hit-weighted: trusted 300/501 vs placebo 251/501 -> ~ +9.8pts (NOT (10-100)/2)
    assert 9.0 < gap < 10.5, gap


def test_rolling_gap_none_when_empty():
    assert rolling_gap([], window=20) == (None, 0)


def _wall_row(**kw):
    base = {"spot": 100.0, "call_wall": 105.0, "put_wall": 95.0,
            "high": 104.0, "low": 96.0, "close": 101.0}
    base.update(kw)
    return base


def test_wall_hold_counts_hold_and_breach_both_ways():
    held = _wall_row()                                    # inside both walls all day
    call_breach = _wall_row(high=106.0, close=106.5)      # through CW, closed above it
    put_breach = _wall_row(low=94.0, close=94.5)          # through PW, closed below it
    w = wall_hold_stats([held, call_breach, put_breach])
    assert w["call_n"] == 3 and w["put_n"] == 3
    assert w["call_held_pct"] == round(100 * 2 / 3, 1)
    assert w["call_close_below_pct"] == round(100 * 2 / 3, 1)
    assert w["put_held_pct"] == round(100 * 2 / 3, 1)
    assert w["put_close_above_pct"] == round(100 * 2 / 3, 1)


def test_wall_hold_excludes_wrong_side_and_missing_walls():
    # Call wall already below spot at 10:00 -> 'held' is meaningless, excluded.
    wrong_side = _wall_row(call_wall=99.0)
    no_walls = _wall_row(call_wall=None, put_wall=None)
    w = wall_hold_stats([wrong_side, no_walls])
    assert w["call_n"] == 0 and w["call_held_pct"] is None
    assert w["put_n"] == 1  # wrong_side's put wall is still valid


def test_wall_hold_touch_exactly_at_wall_counts_as_held():
    # SpotGamma wording: high did not EXCEED the wall — touching it is a hold.
    touch = _wall_row(high=105.0, low=95.0)
    w = wall_hold_stats([touch])
    assert w["call_held_pct"] == 100.0 and w["put_held_pct"] == 100.0


def _ab_row(tk, regime, prior, high):
    return {"ticker": tk, "regime": regime, "regime_prior": prior,
            "range_class_high": high,
            "hit": (regime == "SHORT_GAMMA_TREND") == high,
            "hit_prior": (prior == "SHORT_GAMMA_TREND") == high if prior else None}


def test_sign_ab_scores_shared_rows_and_reports_constant_share():
    rows = [
        _ab_row("NVDA", "SHORT_GAMMA_TREND", "LONG_GAMMA_CHOP", True),   # naive hit, prior miss
        _ab_row("NVDA", "LONG_GAMMA_CHOP", "LONG_GAMMA_CHOP", False),    # both hit
        _ab_row("AMD", "LONG_GAMMA_CHOP", "LONG_GAMMA_CHOP", True),      # both miss
        _ab_row("SPY", "SHORT_GAMMA_TREND", None, True),                 # sentinel: excluded
        _ab_row("TSLA", "LONG_GAMMA_CHOP", None, True),                  # no prior row: excluded
    ]
    ab = _sign_ab(rows)
    assert ab["n"] == 3
    assert ab["naive_hit_pct"] == round(100 * 2 / 3, 1)
    assert ab["prior_hit_pct"] == round(100 * 1 / 3, 1)
    assert ab["prior_always_long_pct"] == 100.0


def test_sign_ab_empty_is_explicit_not_zero():
    ab = _sign_ab([_ab_row("SPY", "LONG_GAMMA_CHOP", None, True)])
    assert ab == {"n": 0, "naive_hit_pct": None, "prior_hit_pct": None,
                  "prior_always_long_pct": None}
