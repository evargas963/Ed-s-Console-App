"""UI-04 P1D — previous-day levels must use the previous TRADING day.

Pre-fix defect: session_date-1 on Mondays/post-holiday sessions produced an
empty window, and the fallback swept EVERY prior bar in the buffer
(multi-day, extended-hours included) into PDH/PDL/PDC.
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
    ts = datetime.combine(d, dtime(hh, mm), tzinfo=ET).timestamp()
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _cfg() -> PlaybookConfig:
    return PlaybookConfig()


def test_monday_uses_friday_not_weekend_calendar_walk():
    """Monday session: prior trading day is Friday; Thursday bars must not leak."""
    friday = date(2026, 7, 10)     # the trading day before the 2026-07-13 Monday
    thursday = date(2026, 7, 9)    # (2026-07-03 was used here until ONE-10: a market holiday)
    monday = date(2026, 7, 13)
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


def _real_spy_bars():
    """Schwab's SPY 1-minute bars, 2026-09-24 and -25 (tests/fixtures)."""
    import json
    from pathlib import Path
    fx = Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json"
    return json.loads(fx.read_text(encoding="utf-8"))["bars"]


def _et(b):
    return datetime.fromtimestamp(b["timestamp"] / 1000.0, ET)


def test_the_prior_session_ends_at_the_calendars_close_on_an_early_close_day(monkeypatch):
    """ONE-10: the levels engine fixed the regular session at 09:30-16:00, so on an early close
    (13:00) its prior-day high, low and close took in three hours of after-hours trading. The
    close is the market calendar's (time_et). Real SPY bars; stand-in: 2026-09-24 declared a
    13:00 early close in the calendar (no early close is in the stored bars yet)."""
    import time_et
    bars = _real_spy_bars()
    prior, today = date(2026, 9, 24), date(2026, 9, 25)
    session = [b for b in bars if _et(b).date() == prior and dtime(9, 30) <= _et(b).time() < dtime(13, 0)]
    full = [b for b in bars if _et(b).date() == prior and dtime(9, 30) <= _et(b).time() < dtime(16, 0)]
    assert max(b["high"] for b in full) != max(b["high"] for b in session) or \
        full[-1]["close"] != session[-1]["close"], "the stand-in day must differ after 13:00"
    monkeypatch.setitem(time_et.US_EQUITY_EARLY_CLOSE_MINS_ET, prior.isoformat(), time_et.EARLY_CLOSE_MINS)
    out = get_previous_day_levels(bars, today, _cfg())
    assert out["pdh"] == max(b["high"] for b in session)
    assert out["pdl"] == min(b["low"] for b in session)
    assert out["pdc"] == session[-1]["close"]


def test_a_holiday_has_no_session_whatever_bars_it_carries(monkeypatch):
    """A day the calendar closes is never the prior session. Real SPY bars; stand-in: 2026-09-24
    declared a full holiday, so the prior session of 2026-09-25 is not in the buffer: absent."""
    import time_et
    monkeypatch.setattr(time_et, "US_EQUITY_FULL_HOLIDAYS_ET",
                        time_et.US_EQUITY_FULL_HOLIDAYS_ET | {"2026-09-24"})
    assert get_previous_day_levels(_real_spy_bars(), date(2026, 9, 25), _cfg()) == {}
