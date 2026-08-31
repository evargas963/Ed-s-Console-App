"""realized_contract_eval's rewired wiring through lifecycle_rule_core must still
evaluate the correct realized-bar outcome (high/low/open/close) after the rewire --
proves the seam survived, not just that the old code path still exists."""
from __future__ import annotations

import lifecycle_rule_core
import realized_contract_eval as rce


def _bar(*, high: float, low: float, open_: float | None = None, close: float | None = None) -> dict:
    out = {
        "candle_high": high,
        "candle_low": low,
        "option_chain_json": "[]",
    }
    if open_ is not None:
        out["candle_open"] = open_
    if close is not None:
        out["candle_close"] = close
    return out


def _assert_legacy_shape(result: dict) -> None:
    assert set(result) == {
        "exit_reason",
        "exit_row",
        "hold_bars",
        "skip_reason",
        "path_model_used",
        "same_bar_stop_target_conflict",
        "same_bar_resolution_rule",
    }


def test_simulate_exit_delegates_to_lifecycle_fire_exit(monkeypatch):
    calls: list[dict] = []
    real_fire_exit = rce.fire_exit

    def tracking_fire_exit(**kwargs):
        calls.append(kwargs)
        return real_fire_exit(**kwargs)

    monkeypatch.setattr(rce, "fire_exit", tracking_fire_exit)

    bars = [_bar(high=104, low=100)]
    result = rce._simulate_exit(call_signal="long", stop=99.0, target=103.0, bars=bars)

    assert calls == [
        {
            "signal": "long",
            "stop": 99.0,
            "target": 103.0,
            "forward_bars": bars,
            "max_hold_bars": len(bars),
        }
    ]
    assert result["exit_reason"] == "target_hit"


def test_simulate_exit_delegates_same_bar_resolution_to_rule_core(monkeypatch):
    calls: list[dict] = []
    real_resolve = rce.resolve_same_bar_conflict

    def tracking_resolve(**kwargs):
        calls.append(kwargs)
        return real_resolve(**kwargs)

    monkeypatch.setattr(rce, "resolve_same_bar_conflict", tracking_resolve)

    bar = _bar(high=104, low=98, open_=100, close=101)
    result = rce._simulate_exit(call_signal="long", stop=99.0, target=103.0, bars=[bar])

    assert calls == [{"bar_ohlc": bar, "stop": 99.0, "target": 103.0, "signal": "long"}]
    assert result["same_bar_stop_target_conflict"] is True
    assert result["same_bar_resolution_rule"] == "bull_bar_assume_extreme_low_before_high_stop_priority"


def test_simulate_exit_preserves_long_same_bar_body_direction_legacy_shape():
    bar = _bar(high=104, low=98, open_=100, close=101)

    result = rce._simulate_exit(call_signal="long", stop=99.0, target=103.0, bars=[bar])

    _assert_legacy_shape(result)
    assert result["exit_reason"] == "stop_hit"
    assert result["exit_row"] is bar
    assert result["hold_bars"] == 1
    assert result["path_model_used"] == "ohlc_body_direction_intrabar_order"
    assert result["same_bar_stop_target_conflict"] is True
    assert result["same_bar_resolution_rule"] == "bull_bar_assume_extreme_low_before_high_stop_priority"


def test_simulate_exit_preserves_short_same_bar_body_direction_legacy_shape():
    bar = _bar(high=102, low=96, open_=100, close=99)

    result = rce._simulate_exit(call_signal="short", stop=101.0, target=97.0, bars=[bar])

    _assert_legacy_shape(result)
    assert result["exit_reason"] == "stop_hit"
    assert result["exit_row"] is bar
    assert result["hold_bars"] == 1
    assert result["path_model_used"] == "ohlc_body_direction_intrabar_order"
    assert result["same_bar_stop_target_conflict"] is True
    assert result["same_bar_resolution_rule"] == "bear_bar_assume_high_before_low_short_stop_before_target"


def test_simulate_exit_preserves_conservative_stop_first_legacy_shape():
    bar = _bar(high=104, low=98)

    result = rce._simulate_exit(call_signal="long", stop=99.0, target=103.0, bars=[bar])

    _assert_legacy_shape(result)
    assert result["exit_reason"] == "stop_hit"
    assert result["exit_row"] is bar
    assert result["hold_bars"] == 1
    assert result["path_model_used"] == "ohlc_stop_priority_no_open_close"
    assert result["same_bar_stop_target_conflict"] is True
    assert result["same_bar_resolution_rule"] == "conservative_stop_first_missing_body"


def test_simulate_exit_preserves_time_expiry_shape():
    bars = [_bar(high=102, low=100), _bar(high=102.5, low=100.5)]

    result = rce._simulate_exit(call_signal="long", stop=99.0, target=103.0, bars=bars)

    _assert_legacy_shape(result)
    assert result["exit_reason"] == "time_expiry"
    assert result["exit_row"] is bars[-1]
    assert result["hold_bars"] == 2
    assert result["path_model_used"] == "ohlc_time_expiry_max_hold"
    assert result["same_bar_stop_target_conflict"] is False


def test_simulate_exit_preserves_missing_stop_target_skip_shape():
    result = rce._simulate_exit(call_signal="long", stop=None, target=103.0, bars=[_bar(high=102, low=100)])

    _assert_legacy_shape(result)
    assert result["skip_reason"] == "missing_stop_target_for_exit"
    assert result["exit_reason"] is None
    assert result["exit_row"] is None
    assert result["hold_bars"] is None


def test_simulate_exit_preserves_missing_ohlc_skip_shape():
    result = rce._simulate_exit(
        call_signal="long",
        stop=99.0,
        target=103.0,
        bars=[{"candle_high": None, "candle_low": 100, "option_chain_json": "[]"}],
    )

    _assert_legacy_shape(result)
    assert result["skip_reason"] == "missing_ohlc_forward_path"
    assert result["exit_reason"] is None
    assert result["exit_row"] is None
    assert result["hold_bars"] is None


def test_rewire_test_imports_rule_core_for_contract_visibility():
    assert lifecycle_rule_core.ExitOutcome.__name__ == "ExitOutcome"
