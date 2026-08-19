"""Single ET authority: DST-aware America/New_York."""

from __future__ import annotations

from datetime import datetime

from db import now_et as db_now_et
from time_et import ET, et_clock_from_ts_utc, now_et


def test_now_et_uses_america_new_york_zone():
    dt = now_et()
    assert dt.tzinfo is not None
    assert str(dt.tzinfo) in ("America/New_York", "America/New_York EST", "America/New_York EDT")
    assert dt.utcoffset() is not None


def test_db_now_et_matches_time_et_module():
    assert db_now_et().tzinfo == now_et().tzinfo


def test_et_clock_from_ts_utc_matches_now_et_zone():
    dt = now_et()
    h, m, wd = et_clock_from_ts_utc(dt.timestamp())
    assert h == dt.hour
    assert m == dt.minute
    assert wd == dt.weekday()


def test_dst_offset_differs_summer_vs_winter():
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=ET)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=ET)
    assert winter.utcoffset() != summer.utcoffset()
    assert winter.utcoffset().total_seconds() == -5 * 3600
    assert summer.utcoffset().total_seconds() == -4 * 3600


def test_hours_until_session_close_uses_early_close_not_1600():
    from time_et import hours_until_session_close_et

    # 2026-11-27 is a listed early-close day (13:00 ET).
    early_am = datetime(2026, 11, 27, 11, 0, tzinfo=ET)
    assert hours_until_session_close_et(early_am) == 2.0
    regular = datetime(2026, 5, 5, 10, 30, tzinfo=ET)
    assert hours_until_session_close_et(regular) == 5.5
    after_early = datetime(2026, 11, 27, 14, 0, tzinfo=ET)
    assert hours_until_session_close_et(after_early) is None
    # Negative: a regular session at 14:00 still has 2h to 16:00.
    regular_pm = datetime(2026, 5, 5, 14, 0, tzinfo=ET)
    assert hours_until_session_close_et(regular_pm) == 2.0
