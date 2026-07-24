"""F1 S1 seam tests: the unified session/calendar authority (RC-31 / F-8 / F-9).

Drives the REAL time_et functions. Locks the three dimensions (ET weekday,
holiday/early-close calendar, RTH minutes) into one call, the fail-closed
uncovered-year rule, DST boundary exactness at the 2026 spring transition,
and — regression-critical — the measured holiday classes (Memorial Day /
2026-07-03) that the legacy clock-only filter admitted.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from time_et import (
    EARLY_CLOSE_MINS,
    RTH_END_MINS,
    RTH_START_MINS,
    is_rth_ts_utc,
    is_tradable_session_ts_utc,
    session_close_mins_for_et_date,
)

ET = ZoneInfo("America/New_York")


def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET).timestamp()


def test_normal_weekday_rth_minute_is_tradable():
    assert is_tradable_session_ts_utc(_ts(2026, 7, 22, 10, 0)) is True
    assert is_tradable_session_ts_utc(_ts(2026, 7, 22, 9, 29)) is False
    assert is_tradable_session_ts_utc(_ts(2026, 7, 22, 16, 0)) is False


def test_full_holidays_are_closed_including_the_measured_classes():
    # Memorial Day 2026 — the store holds 3,795 labeled 'rth' rows here (RC-31 F-9).
    assert is_tradable_session_ts_utc(_ts(2026, 5, 25, 10, 0)) is False
    # Independence Day observed 2026-07-03 — 912 measured rows.
    assert is_tradable_session_ts_utc(_ts(2026, 7, 3, 10, 0)) is False
    assert session_close_mins_for_et_date("2026-05-25") is None
    assert session_close_mins_for_et_date("2026-07-03") is None


def test_legacy_clock_only_filter_admits_what_the_authority_rejects():
    """Documents WHY new consumers must not use is_rth_ts_utc alone."""
    memorial_10am = _ts(2026, 5, 25, 10, 0)
    assert is_rth_ts_utc(memorial_10am) is True  # clock-only: blind to calendar
    assert is_tradable_session_ts_utc(memorial_10am) is False
    saturday_10am = _ts(2026, 3, 7, 10, 0)
    assert is_rth_ts_utc(saturday_10am) is True  # clock-only: blind to weekday
    assert is_tradable_session_ts_utc(saturday_10am) is False


def test_early_close_half_day_ends_at_1300_et():
    # Friday after Thanksgiving 2026.
    assert session_close_mins_for_et_date("2026-11-27") == EARLY_CLOSE_MINS
    assert is_tradable_session_ts_utc(_ts(2026, 11, 27, 12, 59)) is True
    assert is_tradable_session_ts_utc(_ts(2026, 11, 27, 13, 0)) is False
    # 2025 coverage spot-check.
    assert session_close_mins_for_et_date("2025-11-28") == EARLY_CLOSE_MINS


def test_et_weekday_not_utc_weekday_decides():
    # Sunday 20:30 ET is already Monday in UTC (the F-8 divergence window).
    assert is_tradable_session_ts_utc(_ts(2026, 7, 19, 20, 30)) is False


def test_dst_transition_boundaries_exact_on_both_sides():
    # EST Friday before / EDT Monday after the 2026-03-08 spring-forward.
    assert is_tradable_session_ts_utc(_ts(2026, 3, 6, 9, 29)) is False
    assert is_tradable_session_ts_utc(_ts(2026, 3, 6, 9, 30)) is True
    assert is_tradable_session_ts_utc(_ts(2026, 3, 9, 9, 29)) is False
    assert is_tradable_session_ts_utc(_ts(2026, 3, 9, 9, 30)) is True
    assert is_tradable_session_ts_utc(_ts(2026, 3, 9, 15, 59)) is True
    assert is_tradable_session_ts_utc(_ts(2026, 3, 9, 16, 0)) is False


def test_uncovered_year_fails_closed():
    assert session_close_mins_for_et_date("2027-06-15") is None
    assert is_tradable_session_ts_utc(_ts(2027, 6, 15, 10, 0)) is False
    assert session_close_mins_for_et_date("garbage") is None


def test_normal_day_close_is_the_rth_constant():
    assert session_close_mins_for_et_date("2026-07-22") == RTH_END_MINS
    assert RTH_START_MINS == 570 and RTH_END_MINS == 960
