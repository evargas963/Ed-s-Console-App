"""PDCA verdict + history mechanics for the daily terrain scorecard.

The decision rules ARE the product (operator 2026-07-20: "how do we turn this into
something real?") — so they are pure functions with boundary tests, not prose.
"""
from __future__ import annotations

from tools.terrain_backtest_report_v1 import (
    PDCA_ADJUST_PTS,
    PDCA_PROMOTE_PTS,
    PDCA_WINDOW_SESSIONS,
    pdca_verdict,
    rolling_gap,
)


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
