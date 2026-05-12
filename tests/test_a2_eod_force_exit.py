from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from v2_decision import a2_eod_force_exit
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


def _calendar(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "scope": "us_equities",
        "exchange": "NYSE/NASDAQ unified",
        "valid_through_date": "2026-12-31",
        "last_updated_epoch_seconds": 1778113676,
        "regular_session": {
            "open_et": "09:30",
            "close_et": "16:00",
        },
        "full_closures": [
            "2026-01-01",
        ],
        "early_closes": [
            {
                "date": "2026-11-27",
                "close_et": "13:00",
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _isolate_calendar(monkeypatch):
    """Default to calendar=None so tests are independent of the real fixture file."""
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: None, raising=False)


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
    # Legacy fallback path: chain_row absent, selected_exp drives the check.
    assert is_0dte("2026-05-06", _epoch_ms_et(2026, 5, 5, 15, 50)) is False
    assert evaluate_a2_eod_force_exit(_ms(selected_exp="2026-05-06")) == (
        "no_active_position",
        "every_tier_c_cycle",
    )


def test_is_0dte_schwab_chain_row_daysToExpiration_is_primary_source():
    """Schwab `chain_row.daysToExpiration` is the primary 0DTE check;
    it overrides any disagreement with the legacy `selected_exp` proxy."""
    decision_ms = _epoch_ms_et(2026, 5, 5, 15, 50)
    # Primary == 0 wins even when selected_exp would say not-0DTE.
    assert is_0dte("2026-05-06", decision_ms, {"daysToExpiration": 0}) is True
    # Primary != 0 wins even when selected_exp would say 0DTE.
    assert is_0dte("2026-05-05", decision_ms, {"daysToExpiration": 1}) is False
    # Empty/missing chain_row falls back to selected_exp comparison.
    assert is_0dte("2026-05-05", decision_ms, {}) is True
    assert is_0dte("2026-05-05", decision_ms, None) is True


def test_force_exit_uses_chain_row_daysToExpiration_when_proof_present():
    """Schwab `chain_row.daysToExpiration == 0` from the selection proof is
    the primary 0DTE source for `evaluate_a2_eod_force_exit`."""
    proof = {
        "winner": {"chain_row": {"daysToExpiration": 0, "putCall": "CALL"}},
    }
    # selected_exp disagrees (says next day), but Schwab chain_row says 0DTE.
    ms = _ms(
        selected_exp="2026-05-06",
        option_chain_selection_proof=proof,
    )
    assert evaluate_a2_eod_force_exit(ms) == (
        "force_exit_recommended",
        "every_tier_c_cycle",
    )

    # And when chain_row says not-0DTE, force-exit does not fire even if
    # selected_exp says today.
    proof_not_0dte = {
        "winner": {"chain_row": {"daysToExpiration": 1, "putCall": "CALL"}},
    }
    ms2 = _ms(
        selected_exp="2026-05-05",
        option_chain_selection_proof=proof_not_0dte,
    )
    assert evaluate_a2_eod_force_exit(ms2) == (
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


def test_calendar_aware_force_exit_fires_at_early_close_minus_10(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 11, 27, 12, 50),
            selected_exp="2026-11-27",
        )
    ) == ("force_exit_recommended", "every_tier_c_cycle")


def test_calendar_aware_cadence_shifts_at_early_close_minus_30(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 11, 27, 12, 30),
            selected_exp="2026-11-27",
        )
    ) == ("no_active_position", "every_tier_c_cycle")


def test_calendar_aware_full_closure_blocks_force_exit(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 1, 1, 15, 55),
            selected_exp="2026-01-01",
        )
    ) == ("no_active_position", "event_triggered")


def test_calendar_aware_weekend_blocks_force_exit_even_with_calendar_present(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 6, 6, 15, 55),
            selected_exp="2026-06-06",
        )
    ) == ("no_active_position", "event_triggered")


def test_calendar_aware_post_early_close_yields_out_of_session(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 11, 27, 14, 0),
            selected_exp="2026-11-27",
        )
    ) == ("no_active_position", "event_triggered")


def test_calendar_missing_falls_back_to_rth_only_v1_logic(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: None, raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 55),
            selected_exp="2026-05-05",
        )
    ) == ("force_exit_recommended", "every_tier_c_cycle")


def test_calendar_aware_normal_rth_15_50_matches_fallback_15_50(monkeypatch):
    monkeypatch.setattr(a2_eod_force_exit, "load_a2_session_calendar", lambda **kw: _calendar(), raising=False)

    assert evaluate_a2_eod_force_exit(
        _ms(
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50),
            selected_exp="2026-05-05",
        )
    ) == ("force_exit_recommended", "every_tier_c_cycle")
