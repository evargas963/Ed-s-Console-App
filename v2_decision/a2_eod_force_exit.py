"""A2 EOD force-exit and cadence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")

EOD_CADENCE_WINDOW_MINUTES = 30
FORCE_EXIT_CLOCK_HOUR = 15
FORCE_EXIT_CLOCK_MINUTE = 50
RTH_OPEN_MINUTE_TOTAL = 9 * 60 + 30
RTH_CLOSE_MINUTE_TOTAL = 16 * 60


def derive_et_clock_from_decision_time_ms(decision_time_ms) -> tuple[int, int, int] | None:
    """Returns (et_hour, et_minute, et_weekday) or None on invalid input."""
    try:
        ms = float(decision_time_ms)
        dt_utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        dt_et = dt_utc.astimezone(ET)
        return dt_et.hour, dt_et.minute, dt_et.weekday()
    except (TypeError, ValueError, OSError):
        return None


def is_in_rth_normal_session(et_hour, et_minute, et_weekday) -> bool:
    try:
        minute_total = int(et_hour) * 60 + int(et_minute)
        weekday = int(et_weekday)
    except (TypeError, ValueError):
        return False
    return 0 <= weekday <= 4 and RTH_OPEN_MINUTE_TOTAL <= minute_total <= RTH_CLOSE_MINUTE_TOTAL


def is_force_exit_clock_threshold_passed(et_hour, et_minute) -> bool:
    try:
        minute_total = int(et_hour) * 60 + int(et_minute)
    except (TypeError, ValueError):
        return False
    threshold = FORCE_EXIT_CLOCK_HOUR * 60 + FORCE_EXIT_CLOCK_MINUTE
    return minute_total >= threshold


def is_in_eod_cadence_window(et_hour, et_minute) -> bool:
    try:
        minute_total = int(et_hour) * 60 + int(et_minute)
    except (TypeError, ValueError):
        return False
    return minute_total >= RTH_CLOSE_MINUTE_TOTAL - EOD_CADENCE_WINDOW_MINUTES


def is_0dte(selected_exp, decision_time_ms) -> bool:
    try:
        if selected_exp is None:
            return False
        dt_utc = datetime.fromtimestamp(float(decision_time_ms) / 1000, tz=timezone.utc)
        today_et = dt_utc.astimezone(ET).date().isoformat()
        return str(selected_exp).strip() == today_et
    except (TypeError, ValueError, OSError):
        return False


def evaluate_a2_eod_force_exit(ms_dict: dict[str, Any]) -> tuple[str, str]:
    """Returns (lifecycle_action, cadence_observation_mode) per the EOD contract.

    Defaults: ("no_active_position", "event_triggered") on any missing input.
    Force-exit fires when all 4 predicates hold per contract §6.
    Cadence shifts to "every_tier_c_cycle" when in EOD window per contract §7.
    Never raises in production.
    """
    try:
        ms = ms_dict if isinstance(ms_dict, dict) else {}
        clock = derive_et_clock_from_decision_time_ms(ms.get("decision_time_ms"))
        if clock is None:
            return "no_active_position", "event_triggered"
        et_hour, et_minute, et_weekday = clock
        in_rth = is_in_rth_normal_session(et_hour, et_minute, et_weekday)
        cadence = "every_tier_c_cycle" if in_rth and is_in_eod_cadence_window(et_hour, et_minute) else "event_triggered"
        should_force_exit = (
            str(ms.get("entry_state") or "").strip().lower() == "filled"
            and in_rth
            and is_force_exit_clock_threshold_passed(et_hour, et_minute)
            and is_0dte(ms.get("selected_exp"), ms.get("decision_time_ms"))
        )
        return ("force_exit_recommended" if should_force_exit else "no_active_position"), cadence
    except Exception:
        return "no_active_position", "event_triggered"
