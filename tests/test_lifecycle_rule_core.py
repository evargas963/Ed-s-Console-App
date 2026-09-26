"""lifecycle_rule_core's risk-multiplier/time-decay/VIX-adjustment/same-bar
resolution must each apply the correct adjustment -- a wrong multiplier here
silently mis-sizes every open position's stop/target."""
from __future__ import annotations


from lifecycle_rule_core import (
    SameBarResolution,
    fire_exit,
    resolve_same_bar_conflict,
)




def _bar(*, high: float, low: float, open_: float | None = None, close: float | None = None) -> dict:
    out = {"candle_high": high, "candle_low": low}
    if open_ is not None:
        out["candle_open"] = open_
    if close is not None:
        out["candle_close"] = close
    return out


















def test_fire_exit_long_stop_target_and_time_expiry():
    """Audit rows 85/87: exit firing preserves stop_hit, target_hit, and time_expiry."""
    stop = fire_exit(signal="long", stop=99.0, target=103.0, forward_bars=[_bar(high=101, low=98)], max_hold_bars=1)
    target = fire_exit(signal="long", stop=99.0, target=103.0, forward_bars=[_bar(high=104, low=100)], max_hold_bars=1)
    expiry = fire_exit(signal="long", stop=99.0, target=103.0, forward_bars=[_bar(high=102, low=100)], max_hold_bars=1)

    assert stop.exit_reason == "stop_hit"
    assert target.exit_reason == "target_hit"
    assert expiry.exit_reason == "time_expiry"
    assert expiry.exit_bar_index == 0


def test_fire_exit_short_uses_inverted_thresholds():
    """Audit rows 85/89: short exit firing preserves inverted stop and target tests."""
    stop = fire_exit(signal="short", stop=101.0, target=97.0, forward_bars=[_bar(high=102, low=99)], max_hold_bars=1)
    target = fire_exit(signal="short", stop=101.0, target=97.0, forward_bars=[_bar(high=100, low=96)], max_hold_bars=1)

    assert stop.exit_reason == "stop_hit"
    assert target.exit_reason == "target_hit"


def test_same_bar_conflict_uses_candle_body_when_available():
    """Audit row 86: same-bar conflict uses candle-body direction when OHLC body exists."""
    bull = resolve_same_bar_conflict(
        bar_ohlc=_bar(high=104, low=98, open_=100, close=101),
        stop=99.0,
        target=103.0,
        signal="long",
    )
    bear = resolve_same_bar_conflict(
        bar_ohlc=_bar(high=102, low=96, open_=100, close=99),
        stop=101.0,
        target=97.0,
        signal="short",
    )

    assert bull.resolution == SameBarResolution.CANDLE_BODY_OPEN_CLOSE
    assert bull.exit_reason == "stop_hit"
    assert bull.same_bar_resolution_rule == "bull_bar_assume_extreme_low_before_high_stop_priority"
    assert bear.resolution == SameBarResolution.CANDLE_BODY_OPEN_CLOSE
    assert bear.exit_reason == "stop_hit"
    assert bear.same_bar_resolution_rule == "bear_bar_assume_high_before_low_short_stop_before_target"


def test_same_bar_conflict_conservative_stop_first_without_body():
    """Audit row 86: missing open/close preserves conservative stop-first behavior."""
    result = resolve_same_bar_conflict(
        bar_ohlc=_bar(high=104, low=98),
        stop=99.0,
        target=103.0,
        signal="long",
    )

    assert result.resolution == SameBarResolution.CONSERVATIVE_STOP_FIRST
    assert result.exit_reason == "stop_hit"
    assert result.same_bar_resolution_rule == "conservative_stop_first_missing_body"


def test_fire_exit_preserves_replay_style_explicit_skip_reasons():
    """Audit row 90: replay-side missing data emits explicit skip reasons, not fallbacks."""
    invalid_signal = fire_exit(signal="wait", stop=99.0, target=103.0, forward_bars=[_bar(high=101, low=100)], max_hold_bars=1)
    missing_threshold = fire_exit(signal="long", stop=None, target=103.0, forward_bars=[_bar(high=101, low=100)], max_hold_bars=1)
    missing_ohlc = fire_exit(signal="long", stop=99.0, target=103.0, forward_bars=[{"candle_high": None, "candle_low": 100}], max_hold_bars=1)

    assert invalid_signal.skip_reason == "invalid_call_signal_for_path"
    assert missing_threshold.skip_reason == "missing_stop_target_for_exit"
    assert missing_ohlc.skip_reason == "missing_ohlc_forward_path"
