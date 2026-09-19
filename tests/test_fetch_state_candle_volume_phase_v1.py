"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, fifteenth extracted phase.

_candle_volume_for_state (server.py) is the Candle Volume Resolution phase,
extracted verbatim from _fetch_state's body.

A pre-existing quirk preserved, not fixed: the original inline banner
comment says "priority: 1) Price history primary, 2) accumulator
secondary", but the actual code order tries the accumulator FIRST, price
history SECOND (only when the accumulator had no usable volume), then
re-checks the accumulator a THIRD time with the IDENTICAL condition as the
first check -- unreachable dead code whenever the first check already
failed, since the accumulator bars don't change in between. Preserved
verbatim for behavior fidelity, not fixed as part of this decomposition.
"""
from __future__ import annotations

from unittest import mock

import server as srv


class _FakeBar:
    def __init__(self, volume, ts=1000.0):
        self.volume = volume
        self.ts = ts


class _FakePriceHistoryResp:
    def __init__(self, candles):
        self.status_code = 200
        self._candles = candles

    def json(self):
        return {"candles": self._candles}


def _with_bars(bars):
    orig = srv._candles_1m.get_bars
    srv._candles_1m.get_bars = lambda ticker: bars
    return orig


def _restore_bars(orig):
    srv._candles_1m.get_bars = orig


def test_accumulator_primary_used_directly_without_price_history_call():
    orig = _with_bars([_FakeBar(500.0)])
    try:
        with mock.patch.object(srv, "safe_get_price_history") as mock_ph:
            result = srv._candle_volume_for_state("ZZZ_CVOL_ACC", object())
        assert result == 500.0
        assert mock_ph.call_count == 0
    finally:
        _restore_bars(orig)


def test_falls_back_to_price_history_when_accumulator_has_no_bars():
    orig = _with_bars([])
    try:
        resp = _FakePriceHistoryResp([{"datetime": 1000000, "volume": 777.0}])
        with mock.patch.object(srv, "safe_get_price_history", return_value=resp) as mock_ph:
            result = srv._candle_volume_for_state("ZZZ_CVOL_PH", object())
        assert result == 777.0
        assert mock_ph.call_count == 1
    finally:
        _restore_bars(orig)


def test_both_sources_unavailable_yields_none_without_raising():
    orig = _with_bars([])
    try:
        with mock.patch.object(srv, "safe_get_price_history", return_value=None):
            result = srv._candle_volume_for_state("ZZZ_CVOL_NONE", object())
        assert result is None
    finally:
        _restore_bars(orig)


def test_zero_or_negative_accumulator_volume_is_rejected_falls_through():
    """A zero or negative volume must not be accepted -- v > 0 is the original inline
    guard, preserved verbatim."""
    orig = _with_bars([_FakeBar(0.0)])
    try:
        with mock.patch.object(srv, "safe_get_price_history", return_value=None):
            result = srv._candle_volume_for_state("ZZZ_CVOL_ZERO", object())
        assert result is None
    finally:
        _restore_bars(orig)


def test_price_history_exception_is_swallowed_falls_through_to_none():
    orig = _with_bars([])
    try:
        with mock.patch.object(srv, "safe_get_price_history", side_effect=RuntimeError("boom")):
            result = srv._candle_volume_for_state("ZZZ_CVOL_BOOM", object())
        assert result is None
    finally:
        _restore_bars(orig)


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _candle_volume_for_state exactly once."""
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
    assert calls_in_fetch_state.count("_candle_volume_for_state") == 1
