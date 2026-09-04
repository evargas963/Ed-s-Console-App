"""A2 EOD force-exit and cadence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from app.domain.time_et import ET, RTH_END_MINS, RTH_START_MINS

from v2_decision.a2_session_calendar import get_session_info, load_a2_session_calendar

EOD_CADENCE_WINDOW_MINUTES = 30
RTH_OPEN_MINUTE_TOTAL = RTH_START_MINS
RTH_CLOSE_MINUTE_TOTAL = RTH_END_MINS
A2_FORCE_EXIT_OFFSET_FROM_SESSION_CLOSE_MINUTES = 10
A2_CADENCE_SHIFT_OFFSET_FROM_SESSION_CLOSE_MINUTES = 30
FORCE_EXIT_CLOCK_MINUTE_TOTAL = (
    RTH_CLOSE_MINUTE_TOTAL - A2_FORCE_EXIT_OFFSET_FROM_SESSION_CLOSE_MINUTES
)
FORCE_EXIT_CLOCK_HOUR = FORCE_EXIT_CLOCK_MINUTE_TOTAL // 60
FORCE_EXIT_CLOCK_MINUTE = FORCE_EXIT_CLOCK_MINUTE_TOTAL % 60


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
    return 0 <= weekday <= 4 and RTH_OPEN_MINUTE_TOTAL <= minute_total < RTH_CLOSE_MINUTE_TOTAL


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


def is_0dte(selected_exp, decision_time_ms, chain_row=None) -> bool:
    """Schwab-first 0DTE check.

    Primary: ``chain_row["daysToExpiration"] == 0`` when chain_row is provided
    and carries the field. Schwab is the authoritative source for the selected
    contract's days-to-expiration.

    Fallback: when chain_row is absent (or missing daysToExpiration), compare
    ``selected_exp`` against today's ET date as a legacy app-side proxy.
    """
    try:
        if isinstance(chain_row, dict):
            dte = chain_row.get("daysToExpiration")
            if dte is not None:
                try:
                    return int(dte) == 0
                except (TypeError, ValueError):
                    pass
        if selected_exp is None:
            return False
        dt_utc = datetime.fromtimestamp(float(decision_time_ms) / 1000, tz=timezone.utc)
        today_et = dt_utc.astimezone(ET).date().isoformat()
        return str(selected_exp).strip() == today_et
    except (TypeError, ValueError, OSError):
        return False


def _selected_chain_row(ms: dict[str, Any]) -> dict[str, Any] | None:
    proof = ms.get("option_chain_selection_proof")
    if not isinstance(proof, dict):
        return None
    winner = proof.get("winner")
    if not isinstance(winner, dict):
        return None
    chain_row = winner.get("chain_row")
    if not isinstance(chain_row, dict) or not chain_row:
        return None
    return chain_row


def _parse_hhmm_to_min(value) -> int | None:
    try:
        if not isinstance(value, str):
            return None
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute
    except (TypeError, ValueError):
        return None


def _evaluate_a2_eod_force_exit_fallback(ms: dict[str, Any]) -> tuple[str, str]:
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
        and is_0dte(ms.get("selected_exp"), ms.get("decision_time_ms"), _selected_chain_row(ms))
    )
    return ("force_exit_recommended" if should_force_exit else "no_active_position"), cadence


def evaluate_a2_eod_force_exit(ms_dict: dict[str, Any]) -> tuple[str, str]:
    """Returns (lifecycle_action, cadence_observation_mode) per the EOD contract.

    Defaults: ("no_active_position", "event_triggered") on any missing input.
    Force-exit fires when all 4 predicates hold per contract §6.
    Cadence shifts to "every_tier_c_cycle" when in EOD window per contract §7.
    Never raises in production.
    """
    try:
        ms = ms_dict if isinstance(ms_dict, dict) else {}
        calendar = load_a2_session_calendar()
        if calendar is None:
            return _evaluate_a2_eod_force_exit_fallback(ms)

        session_info = get_session_info(decision_time_ms=ms.get("decision_time_ms"), calendar=calendar)
        if session_info is None:
            return _evaluate_a2_eod_force_exit_fallback(ms)
        if session_info.session_type not in ("normal_rth", "early_close"):
            return "no_active_position", "event_triggered"

        session_close_minute = _parse_hhmm_to_min(session_info.session_close_et)
        if session_close_minute is None:
            return _evaluate_a2_eod_force_exit_fallback(ms)

        cadence_threshold = session_close_minute - A2_CADENCE_SHIFT_OFFSET_FROM_SESSION_CLOSE_MINUTES
        force_exit_threshold = session_close_minute - A2_FORCE_EXIT_OFFSET_FROM_SESSION_CLOSE_MINUTES
        cadence = "every_tier_c_cycle" if session_info.decision_minute_et >= cadence_threshold else "event_triggered"
        should_force_exit = (
            str(ms.get("entry_state") or "").strip().lower() == "filled"
            and session_info.decision_minute_et >= force_exit_threshold
            and is_0dte(ms.get("selected_exp"), ms.get("decision_time_ms"), _selected_chain_row(ms))
        )
        return ("force_exit_recommended" if should_force_exit else "no_active_position"), cadence
    except Exception:
        return "no_active_position", "event_triggered"
