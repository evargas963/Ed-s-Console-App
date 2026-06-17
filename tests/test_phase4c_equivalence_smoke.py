"""Smoke: BAR_ANCHOR recompute is deterministic (Phase 4C helper contract)."""
from __future__ import annotations

import bisect


from horizon_outcomes import OUTCOME_BAR_SPECS, bar_complete_by_utc, forward_bar_start_utc
from math_exposure import classify_direction


def _compute(ts: float, bar_ends: list[float], bar_end_closes: list[float], close_by_start: dict, tz: float):
    ai = bisect.bisect_right(bar_ends, ts) - 1
    assert ai >= 0
    ac = bar_end_closes[ai]
    for _odir, _opt, n_min in OUTCOME_BAR_SPECS:
        b0 = forward_bar_start_utc(ts, n_min)
        assert bar_complete_by_utc(b0, tz)
        fc = close_by_start[float(b0)]
        classify_direction(float(fc) - ac, ac)
    return ac


def test_phase4c_determinism_synthetic_grid():
    t0 = 0.0
    nbar = 400
    bar_ends = [t0 + 60.0 * (i + 1) for i in range(nbar)]
    bar_end_closes = [100.0 + 0.01 * i for i in range(nbar)]
    close_by_start = {be - 60.0: c for be, c in zip(bar_ends, bar_end_closes)}
    ts = 150.0
    tz = 500_000.0
    a1 = _compute(ts, bar_ends, bar_end_closes, close_by_start, tz)
    a2 = _compute(ts, bar_ends, bar_end_closes, close_by_start, tz)
    assert a1 == a2
