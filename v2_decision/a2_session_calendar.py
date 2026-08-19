"""A2 session calendar loader and classifier."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, NamedTuple
from time_et import ET, RTH_END_MINS, RTH_START_MINS, now_et

logger = logging.getLogger(__name__)
CALENDAR_RELATIVE_PATH = Path("trading_calendar") / "us_equities.json"
DEFAULT_DATA_ROOT = Path("data")

SessionType = Literal["normal_rth", "early_close", "full_closure", "out_of_session"]


class SessionInfo(NamedTuple):
    session_type: SessionType
    session_open_et: str | None
    session_close_et: str | None
    decision_date_et: str
    decision_minute_et: int


def load_a2_session_calendar(*, data_root: Path | None = None, now_et_date: date | None = None) -> dict | None:
    """Returns the A2 session calendar dict or None on missing, malformed, or stale."""
    try:
        root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
        path = root / CALENDAR_RELATIVE_PATH
        with path.open("r", encoding="utf-8") as handle:
            calendar = json.load(handle)
        if not _is_valid_calendar(calendar):
            logger.debug("A2 session calendar invalid: %s", path)
            return None
        valid_through = _parse_iso_date(calendar.get("valid_through_date"))
        current_date = now_et_date or now_et().date()
        if valid_through is None or current_date > valid_through:
            logger.debug("A2 session calendar stale: %s", path)
            return None
        return calendar
    except Exception as exc:
        logger.debug("A2 session calendar unavailable: %s", exc)
        return None


def get_session_info(*, decision_time_ms: int, calendar: dict) -> SessionInfo | None:
    """Classify the decision moment against the A2 session calendar."""
    try:
        if not _is_valid_calendar(calendar):
            return None

        dt_et = datetime.fromtimestamp(float(decision_time_ms) / 1000, tz=timezone.utc).astimezone(ET)
        decision_date_et = dt_et.date().isoformat()
        decision_minute_et = dt_et.hour * 60 + dt_et.minute

        regular_session = calendar.get("regular_session")
        # Display strings and the minute cut come from the one RTH clock
        # (time_et). The JSON still has to carry parseable regular_session
        # HH:MM for schema validity; it is not a second open/close producer.
        if _string_value(regular_session, "open_et") is None:
            return None
        if _string_value(regular_session, "close_et") is None:
            return None
        open_minute = int(RTH_START_MINS)
        close_minute = int(RTH_END_MINS)
        regular_open = f"{open_minute // 60:02d}:{open_minute % 60:02d}"
        regular_close = f"{close_minute // 60:02d}:{close_minute % 60:02d}"

        full_closures = _date_set(calendar.get("full_closures"))
        early_close_map = _early_close_map(calendar.get("early_closes"))

        if dt_et.weekday() >= 5 or decision_date_et in full_closures:
            return SessionInfo(
                session_type="full_closure",
                session_open_et=None,
                session_close_et=None,
                decision_date_et=decision_date_et,
                decision_minute_et=decision_minute_et,
            )

        if decision_date_et in early_close_map:
            early_close_et = early_close_map[decision_date_et]
            early_close_minute = _parse_hhmm_to_min(early_close_et)
            if early_close_minute is None:
                return None
            session_type: SessionType = (
                "early_close" if open_minute <= decision_minute_et <= early_close_minute else "out_of_session"
            )
            return SessionInfo(
                session_type=session_type,
                session_open_et=regular_open,
                session_close_et=early_close_et,
                decision_date_et=decision_date_et,
                decision_minute_et=decision_minute_et,
            )

        session_type = (
            "normal_rth"
            if open_minute <= decision_minute_et < close_minute
            else "out_of_session"
        )
        return SessionInfo(
            session_type=session_type,
            session_open_et=regular_open,
            session_close_et=regular_close,
            decision_date_et=decision_date_et,
            decision_minute_et=decision_minute_et,
        )
    except Exception as exc:
        logger.debug("A2 session calendar classification unavailable: %s", exc)
        return None


def _is_valid_calendar(calendar: Any) -> bool:
    if not isinstance(calendar, dict):
        return False
    if calendar.get("schema_version") != "1":
        return False
    if calendar.get("scope") != "us_equities":
        return False
    regular_session = calendar.get("regular_session")
    if not isinstance(regular_session, dict):
        return False
    if _parse_hhmm_to_min(regular_session.get("open_et")) is None:
        return False
    if _parse_hhmm_to_min(regular_session.get("close_et")) is None:
        return False
    if _parse_iso_date(calendar.get("valid_through_date")) is None:
        return False
    if not isinstance(calendar.get("full_closures"), list):
        return False
    if not isinstance(calendar.get("early_closes"), list):
        return False
    return True


def _parse_hhmm_to_min(value: str) -> int | None:
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


def _parse_iso_date(value: Any) -> date | None:
    try:
        if not isinstance(value, str):
            return None
        return date.fromisoformat(value)
    except ValueError:
        return None


def _string_value(obj: Any, key: str) -> str | None:
    if isinstance(obj, dict):
        value = obj.get(key)
        if isinstance(value, str):
            return value
    return None


def _date_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and _parse_iso_date(value) is not None}


def _early_close_map(values: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(values, list):
        return result
    for item in values:
        if not isinstance(item, dict):
            continue
        day = item.get("date")
        close_et = item.get("close_et")
        if isinstance(day, str) and _parse_iso_date(day) is not None and _parse_hhmm_to_min(close_et) is not None:
            result[day] = close_et
    return result
