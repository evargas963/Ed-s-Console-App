from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from v2_decision.a2_eod_force_exit import (
    derive_et_clock_from_decision_time_ms,
    evaluate_a2_eod_force_exit,
    is_0dte,
    is_force_exit_clock_threshold_passed,
    is_in_eod_cadence_window,
    is_in_rth_normal_session,
)


ET = ZoneInfo("America/New_York")


def _epoch_ms_et(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _ms(**overrides) -> dict:
    base = {
        "entry_state": "filled",
        "decision_time_ms": _epoch_ms_et(2026, 5, 5, 15, 50),
        "selected_exp": "2026-05-05",
    }
    base.update(overrides)
    return base


def test_derive_et_clock_returns_correct_hour_minute_weekday_for_normal_input():
    assert derive_et_clock_from_decision_time_ms(_epoch_ms_et(2026, 5, 5, 15, 50)) == (15, 50, 1)


def test_derive_et_clock_returns_none_on_invalid_input():
    assert derive_et_clock_from_decision_time_ms(None) is None
    assert derive_et_clock_from_decision_time_ms("not-a-timestamp") is None


def test_derive_et_clock_handles_dst_transitions():
    assert derive_et_clock_from_decision_time_ms(_epoch_ms_et(2026, 3, 9, 15, 50)) == (15, 50, 0)
    assert derive_et_clock_from_decision_time_ms(_epoch_ms_et(2026, 11, 2, 15, 50)) == (15, 50, 0)


def test_force_exit_fires_when_all_4_predicates_hold():
    assert evaluate_a2_eod_force_exit(_ms()) == ("force_exit_recommended", "every_tier_c_cycle")


def test_force_exit_does_not_fire_when_entry_state_is_not_filled():
    assert evaluate_a2_eod_force_exit(_ms(entry_state="armed")) == ("no_active_position", "every_tier_c_cycle")


def test_force_exit_does_not_fire_when_clock_before_15_50():
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 49))) == (
        "no_active_position",
        "every_tier_c_cycle",
    )


def test_force_exit_does_not_fire_outside_rth_normal_session():
    assert is_in_rth_normal_session(9, 29, 1) is False
    assert is_in_rth_normal_session(16, 1, 1) is False
    assert is_in_rth_normal_session(15, 50, 5) is False
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 9, 15, 50))) == (
        "no_active_position",
        "event_triggered",
    )


def test_force_exit_does_not_fire_for_non_0dte():
    assert is_0dte("2026-05-06", _epoch_ms_et(2026, 5, 5, 15, 50)) is False
    assert evaluate_a2_eod_force_exit(_ms(selected_exp="2026-05-06")) == (
        "no_active_position",
        "every_tier_c_cycle",
    )


def test_cadence_mode_event_triggered_outside_eod_window():
    assert is_in_eod_cadence_window(15, 29) is False
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 29))) == (
        "no_active_position",
        "event_triggered",
    )


def test_cadence_mode_every_tier_c_cycle_inside_eod_window():
    assert is_in_eod_cadence_window(15, 31) is True
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 31))) == (
        "no_active_position",
        "every_tier_c_cycle",
    )


def test_cadence_mode_at_15_30_boundary():
    assert is_in_eod_cadence_window(15, 30) is True
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 30))) == (
        "no_active_position",
        "every_tier_c_cycle",
    )


def test_force_exit_at_15_50_boundary():
    assert is_force_exit_clock_threshold_passed(15, 49) is False
    assert is_force_exit_clock_threshold_passed(15, 50) is True
    assert evaluate_a2_eod_force_exit(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50))) == (
        "force_exit_recommended",
        "every_tier_c_cycle",
    )


def test_orchestrator_does_not_raise_on_unexpected_input():
    assert evaluate_a2_eod_force_exit(None) == ("no_active_position", "event_triggered")
    assert evaluate_a2_eod_force_exit({"entry_state": "filled", "decision_time_ms": object()}) == (
        "no_active_position",
        "event_triggered",
    )


def test_orchestrator_does_not_mutate_ms_dict():
    ms = _ms()
    before = deepcopy(ms)

    evaluate_a2_eod_force_exit(ms)

    assert ms == before
