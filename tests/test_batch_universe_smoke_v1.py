"""RC-7 rule: research/tools code cited in decisions ships with smoke tests."""
from __future__ import annotations

import inspect

from tools.run_batch_universe_study import (
    MIN_REAL_BAR_SHARE,
    MIN_TOTAL_BARS,
    MIN_TRADABLE_SESSIONS,
    discover_universe,
    run_ticker_battery,
    screen_ticker,
)


def test_gate_floors_match_the_f2_template():
    assert MIN_TRADABLE_SESSIONS == 60          # F2 session floor verbatim
    assert MIN_TOTAL_BARS == 20_000
    assert 0.0 < MIN_REAL_BAR_SHARE <= 1.0


def test_screen_and_battery_signatures_are_ticker_parametric():
    assert list(inspect.signature(screen_ticker).parameters) == ["db_path", "ticker"]
    assert list(inspect.signature(run_ticker_battery).parameters) == ["db_path", "ticker"]
    assert list(inspect.signature(discover_universe).parameters) == ["db_path"]


def test_f2_sessions_events_accepts_ticker():
    from research.pilot_step3.f2_tb_grid_runner import _sessions_events

    params = inspect.signature(_sessions_events).parameters
    assert "ticker" in params
    assert params["ticker"].default == "SPY"
