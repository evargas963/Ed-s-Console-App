"""UI-04 P1D — previous-day levels must use the previous TRADING day.

Pre-fix defect: session_date-1 on Mondays/post-holiday sessions produced an
empty window, and the fallback swept EVERY prior bar in the buffer
(multi-day, extended-hours included) into PDH/PDL/PDC.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from liquidity_value_engine import PlaybookConfig, get_previous_day_levels

ET = ZoneInfo("America/New_York")


def _bar(d: date, hh: int, mm: int, o: float, h: float, l: float, c: float, v: int = 100):
    ts = datetime.combine(d, dtime(hh, mm), tzinfo=ET).timestamp()
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _cfg() -> PlaybookConfig:
    return PlaybookConfig()


def test_monday_uses_friday_not_weekend_calendar_walk():
    """Monday session: prior trading day is Friday; Thursday bars must not leak."""
    friday = date(2026, 7, 3)      # weekday before the 2026-07-06 Monday
    thursday = date(2026, 7, 2)
    monday = date(2026, 7, 6)
    bars = [
        _bar(thursday, 10, 0, 100, 120, 90, 110),   # decoy older day
        _bar(friday, 10, 0, 100, 105, 95, 101),
        _bar(friday, 14, 0, 101, 106, 96, 102),
    ]
    out = get_previous_day_levels(bars, monday, _cfg())
    assert out["pdh"] == 106
    assert out["pdl"] == 95
    assert out["pdc"] == 102


def test_extended_hours_bars_never_enter_prev_day_levels():
    prev = date(2026, 7, 9)
    today = date(2026, 7, 10)
    bars = [
        _bar(prev, 8, 0, 100, 999, 1, 100),     # premarket outlier — must be excluded
        _bar(prev, 10, 0, 100, 105, 95, 101),
        _bar(prev, 17, 0, 100, 998, 2, 100),    # after-hours outlier — must be excluded
    ]
    out = get_previous_day_levels(bars, today, _cfg())
    assert out["pdh"] == 105
    assert out["pdl"] == 95


def test_multi_day_buffer_selects_only_most_recent_trading_day():
    d1, d2, today = date(2026, 7, 7), date(2026, 7, 9), date(2026, 7, 10)
    bars = [
        _bar(d1, 11, 0, 100, 200, 50, 150),     # older day extremes — must not leak
        _bar(d2, 11, 0, 100, 110, 90, 105),
    ]
    out = get_previous_day_levels(bars, today, _cfg())
    assert out["pdh"] == 110
    assert out["pdl"] == 90
    assert out["pdc"] == 105


def test_no_prior_rth_bars_fails_closed_empty():
    """No prior-day RTH bar anywhere: levels stay absent — never fabricated
    from extended-hours or same-day bars (the pre-fix fallback defect)."""
    today = date(2026, 7, 10)
    bars = [
        _bar(date(2026, 7, 9), 7, 0, 100, 120, 80, 110),   # premarket only
        _bar(today, 10, 0, 100, 105, 95, 101),             # same-day RTH
    ]
    out = get_previous_day_levels(bars, today, _cfg())
    assert "pdh" not in out and "pdl" not in out and "pdc" not in out


def test_empty_bars_returns_empty():
    assert get_previous_day_levels([], date(2026, 7, 10), _cfg()) == {}
