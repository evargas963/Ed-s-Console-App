from __future__ import annotations

import pytest

from lifecycle_rule_core import (
    SameBarResolution,
    apply_risk_multiplier,
    apply_time_decay,
    apply_vix_adjustment,
    derive_stop_distance_pct,
    derive_target_levels,
    fire_exit,
    resolve_same_bar_conflict,
    snap_target_to_structural,
)
from math_exposure import (
    STOP_BASE_PCT,
    STOP_CEILING_PCT,
    STOP_FLOOR_PCT,
    STOP_TIME_DECAY_PCT,
    STOP_VIX_HIGH_PCT,
    STOP_VIX_MED_PCT,
)


def _bar(*, high: float, low: float, open_: float | None = None, close: float | None = None) -> dict:
    out = {"candle_high": high, "candle_low": low}
    if open_ is not None:
        out["candle_open"] = open_
    if close is not None:
        out["candle_close"] = close
    return out


def test_vix_adjustment_preserves_call_engine_threshold_edges():
    """Audit rows 79/82: VIX adjustment keeps call_engine >20 / >30 semantics."""
    base = STOP_BASE_PCT

    assert apply_vix_adjustment(base, None) == pytest.approx(base)
    assert apply_vix_adjustment(base, 20.0) == pytest.approx(base)
    assert apply_vix_adjustment(base, 20.01) == pytest.approx(base + STOP_VIX_MED_PCT)
    assert apply_vix_adjustment(base, 30.0) == pytest.approx(base + STOP_VIX_MED_PCT)
    assert apply_vix_adjustment(base, 30.01) == pytest.approx(base + STOP_VIX_HIGH_PCT)


def test_time_decay_preserves_open_midday_near_close_math():
    """Audit rows 79/81: time decay subtracts STOP_TIME_DECAY_PCT per elapsed hour."""
    assert apply_time_decay(STOP_BASE_PCT, 0) == pytest.approx(STOP_BASE_PCT)
    assert apply_time_decay(STOP_BASE_PCT, 120) == pytest.approx(STOP_BASE_PCT - 2 * STOP_TIME_DECAY_PCT)
    assert apply_time_decay(STOP_BASE_PCT, 390) == pytest.approx(STOP_BASE_PCT - 6.5 * STOP_TIME_DECAY_PCT)


def test_risk_multiplier_preserves_clamp_and_default_semantics():
    """Audit rows 79/84: risk multiplier clamps to call_engine's 0.8x to 1.5x range."""
    assert apply_risk_multiplier(0.002, None) == pytest.approx(0.002)
    assert apply_risk_multiplier(0.002, 0.0) == pytest.approx(0.002)
    assert apply_risk_multiplier(0.002, 0.5) == pytest.approx(0.0016)
    assert apply_risk_multiplier(0.002, 2.0) == pytest.approx(0.003)


def test_derive_stop_distance_pct_preserves_adjustment_order_and_clamp():
    """Audit rows 79/81/82/84: stop distance applies time, VIX, multiplier, then clamp."""
    result = derive_stop_distance_pct(
        spot=500.0,
        vix_level=31.0,
        mins_elapsed_since_open=60.0,
        risk_multiplier=1.35,
    )
    expected = (STOP_BASE_PCT - STOP_TIME_DECAY_PCT + STOP_VIX_HIGH_PCT) * 1.35
    expected = max(STOP_FLOOR_PCT, min(STOP_CEILING_PCT, expected))

    assert result.final_pct == pytest.approx(expected)
    assert result.adjustments_applied == ("time_decay", "vix_high", "risk_multiplier")


def test_snap_target_to_structural_reuses_single_snap_semantics():
    """Audit row 83: structural snap picks nearest eligible level within 1.5R."""
    assert snap_target_to_structural(
        target_price=505.0,
        structural_levels=[500.0, 504.8, 507.0],
        direction="long",
        risk=1.0,
    ) == pytest.approx(504.8)
    assert snap_target_to_structural(
        target_price=495.0,
        structural_levels=[500.0, 495.2, 492.0],
        direction="short",
        risk=1.0,
    ) == pytest.approx(495.2)
    assert snap_target_to_structural(
        target_price=505.0,
        structural_levels=[510.0],
        direction="long",
        risk=1.0,
    ) == pytest.approx(505.0)


def test_derive_target_levels_long_preserves_5c_15c_caps_and_snap():
    """Audit rows 80/83: target levels preserve 5c/15c sources, caps, and snap reuse."""
    levels = derive_target_levels(
        entry=100.0,
        direction="long",
        risk=2.0,
        avg5=6.0,
        avg15=10.0,
        avg60=None,
        structural_levels=[105.8, 109.8],
    )

    assert levels.target == pytest.approx(105.8)
    assert levels.target2 == pytest.approx(109.8)
    assert levels.target_source == "5c_avg_move"
    assert levels.target2_source == "15c_avg_move"
    assert levels.target_snapped is True
    assert levels.target2_snapped is True


def test_derive_target_levels_fallbacks_and_short_direction():
    """Audit rows 80/83: missing avg moves preserve 2R and T1 plus 1R fallbacks."""
    levels = derive_target_levels(
        entry=100.0,
        direction="short",
        risk=2.0,
        avg5=None,
        avg15=None,
        avg60=None,
        structural_levels=[],
    )

    assert levels.target == pytest.approx(96.0)
    assert levels.target2 == pytest.approx(94.0)
    assert levels.target_source == "2r_fallback"
    assert levels.target2_source == "1r_offset_from_t1"
    assert levels.target_snapped is False
    assert levels.target2_snapped is False


def test_derive_target_levels_uses_60c_when_15c_missing_and_caps_rr():
    """Audit row 80: target2 can use 60c and remains capped at 8R."""
    levels = derive_target_levels(
        entry=100.0,
        direction="long",
        risk=2.0,
        avg5=100.0,
        avg15=None,
        avg60=100.0,
        structural_levels=[],
    )

    assert levels.target == pytest.approx(110.0)
    assert levels.target2 == pytest.approx(116.0)
    assert levels.target_source == "5c_avg_move"
    assert levels.target2_source == "60c_avg_move"


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
