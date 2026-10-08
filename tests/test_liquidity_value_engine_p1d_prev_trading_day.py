"""UI-04 P1D — previous-day levels must use the previous TRADING day.

Pre-fix defect: session_date-1 on Mondays/post-holiday sessions produced an
empty window, and the fallback swept EVERY prior bar in the buffer
(multi-day, extended-hours included) into PDH/PDL/PDC.

The sessions are Schwab's /markets answers captured 2026-10-07 (tests/conftest.py): a Friday and
the Monday after it (2026-10-02, -05), Thanksgiving (2026-11-26, closed) and the early close after
it (2026-11-27, regular session 09:30-13:00 ET). The bars are hand-built on those dates: each case
needs a bar placed exactly inside or outside a session boundary.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from liquidity_value_engine import PlaybookConfig, _bars_to_list
from liquidity_value_engine import get_previous_day_levels as _levels


def get_previous_day_levels(bars, session_date, cfg):
    """The engine's prior-day levels of bars normalized as its producer normalizes them."""
    return _levels(_bars_to_list(bars), session_date, cfg)

ET = ZoneInfo("America/New_York")


def _bar(d: date, hh: int, mm: int, o: float, h: float, l: float, c: float, v: int = 100):
    # institutional-synthetic-ok: each case places a bar exactly inside or outside a session
    # boundary Schwab's /markets sent
    ts = datetime.combine(d, dtime(hh, mm), tzinfo=ET).timestamp()
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _cfg() -> PlaybookConfig:
    return PlaybookConfig()


def test_monday_uses_friday_not_weekend_calendar_walk():
    """Monday session: prior trading day is Friday; Thursday bars must not leak."""
    thursday, friday, monday = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)
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
    prev, today = date(2026, 10, 6), date(2026, 10, 7)
    bars = [
        _bar(prev, 8, 0, 100, 999, 1, 100),     # premarket outlier — must be excluded
        _bar(prev, 10, 0, 100, 105, 95, 101),
        _bar(prev, 17, 0, 100, 998, 2, 100),    # after-hours outlier — must be excluded
    ]
    out = get_previous_day_levels(bars, today, _cfg())
    assert out["pdh"] == 105
    assert out["pdl"] == 95


def test_multi_day_buffer_selects_only_most_recent_trading_day():
    d1, d2, today = date(2026, 10, 1), date(2026, 10, 6), date(2026, 10, 7)
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
    today = date(2026, 10, 7)
    bars = [
        _bar(date(2026, 10, 6), 7, 0, 100, 120, 80, 110),   # premarket only
        _bar(today, 10, 0, 100, 105, 95, 101),              # same-day RTH
    ]
    out = get_previous_day_levels(bars, today, _cfg())
    assert "pdh" not in out and "pdl" not in out and "pdc" not in out


def test_empty_bars_returns_empty():
    assert get_previous_day_levels([], date(2026, 10, 7), _cfg()) == {}


def test_the_prior_session_ends_at_schwabs_close_on_an_early_close_day():
    """ONE-10: the levels engine fixed the regular session at 09:30-16:00, so on an early close
    (13:00) its prior-day high, low and close took in three hours of after-hours trading. The
    close is the one Schwab's /markets sent: 2026-11-27's regular session ends 13:00 ET, so the
    14:00 bar is after hours and never a prior-day level of Monday 2026-11-30."""
    friday, monday = date(2026, 11, 27), date(2026, 11, 30)
    bars = [
        _bar(friday, 10, 0, 100, 105, 95, 101),
        _bar(friday, 12, 59, 101, 106, 96, 102),
        _bar(friday, 14, 0, 102, 150, 50, 140),   # after the early close — must be excluded
    ]
    out = get_previous_day_levels(bars, monday, _cfg())
    assert (out["pdh"], out["pdl"], out["pdc"]) == (106, 95, 102)


def test_a_holiday_has_no_session_whatever_bars_it_carries():
    """A day Schwab's /markets says is closed is never the prior session: Thanksgiving 2026-11-26
    carries bars, and the prior session of 2026-11-27 is 2026-11-25."""
    bars = [
        _bar(date(2026, 11, 25), 11, 0, 100, 105, 95, 101),
        _bar(date(2026, 11, 26), 11, 0, 100, 200, 50, 150),   # the holiday's bar — never a level
    ]
    out = get_previous_day_levels(bars, date(2026, 11, 27), _cfg())
    assert (out["prior_date"], out["pdh"], out["pdl"]) == (date(2026, 11, 25), 105, 95)
