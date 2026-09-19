"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, fifth extracted phase.

_candle_direction_for_state (server.py) is the Candle Direction + Body phase, moved out
of _fetch_state's body into a standalone function returning a _CandleDirectionForState
NamedTuple. Reads the last COMPLETED 1m bar (not a live tick delta) to classify bar
direction/body and expose OHLC/range.

Note: server.py reassigns c_open/c_high/c_low/c_close/c_range again LATER in _fetch_state's
own body, from the forming/live bar under a different branch -- this extraction only covers
the FIRST assignment (from the last completed bar), matching the original inline block
exactly; that later reassignment was untouched and is out of scope here.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import server as srv


def _with_bars(*bars):
    return mock.patch.object(srv, "_candles_1m", SimpleNamespace(get_bars=lambda t: list(bars)))


def test_bullish_bar_classifies_up_with_correct_ohlc_and_range():
    bar = SimpleNamespace(open=100.0, high=102.5, low=99.5, close=101.5)
    with _with_bars(bar):
        result = srv._candle_direction_for_state("SPY")

    expected_move = round(101.5 - 100.0, 4)
    expected_dir = srv._classify_direction(expected_move, 100.0)
    assert result.candle_dir == expected_dir
    assert result.candle_body == abs(expected_move)
    assert result.c_open == 100.0
    assert result.c_high == 102.5
    assert result.c_low == 99.5
    assert result.c_close == 101.5
    assert result.c_range == round(102.5 - 99.5, 4)


def test_no_completed_bars_returns_all_none():
    with mock.patch.object(srv, "_candles_1m", SimpleNamespace(get_bars=lambda t: [])):
        result = srv._candle_direction_for_state("COLD")
    assert result == (None, None, None, None, None, None, None)


def test_zero_open_guards_direction_and_body_but_ohlc_still_populates():
    """Matches the original inline guard `if _lb_open and _lb_close and
    float(_lb_open) > 0` -- a zero (or falsy) open must suppress direction/body
    classification (division-by-open-adjacent math would be meaningless) while the raw
    OHLC/range fields still populate independently."""
    bar = SimpleNamespace(open=0.0, high=1.0, low=0.0, close=0.5)
    with _with_bars(bar):
        result = srv._candle_direction_for_state("ZEROOPEN")
    assert result.candle_dir is None
    assert result.candle_body is None
    assert result.c_open == 0.0
    assert result.c_close == 0.5
    assert result.c_range == 1.0


def test_missing_high_low_leaves_range_none_without_raising():
    bar = SimpleNamespace(open=100.0, high=None, low=None, close=101.0)
    with _with_bars(bar):
        result = srv._candle_direction_for_state("PARTIAL")
    assert result.c_high is None
    assert result.c_low is None
    assert result.c_range is None
    # Direction/body still compute independently of high/low.
    assert result.candle_dir is not None
    assert result.candle_body == 1.0


def test_only_the_last_bar_is_read_never_averaged_across_history():
    """Matches the original inline `_completed_bars_now[-1]` -- an earlier bar in the
    list must never influence the result."""
    stale_bar = SimpleNamespace(open=200.0, high=210.0, low=190.0, close=195.0)
    latest_bar = SimpleNamespace(open=100.0, high=101.0, low=99.0, close=100.5)
    with _with_bars(stale_bar, latest_bar):
        result = srv._candle_direction_for_state("SPY")
    assert result.c_open == 100.0
    assert result.c_close == 100.5


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _candle_direction_for_state exactly once."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_candle_direction_for_state") == 1
    assert "_classify_direction" not in calls_in_fetch_state, (
        "_fetch_state still calls _classify_direction directly -- the candle-direction "
        "phase was not fully extracted, a second inline computation site survived"
    )
