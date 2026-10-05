"""Session VWAP semantic fidelity — RTH availability."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from liquidity_value_engine import (
    _bars_to_list,
    compute_session_vwap_series,
    count_session_rth_positive_volume_bars,
)
from tests.feed_live_helper import console_bars
from time_et import ET, RTH_START_MINS, is_trading_day_et, session_label

FRIDAY = date(2026, 8, 28)
SATURDAY = date(2026, 8, 29)


def _rth_bar(session: date, minutes_after_open: int, close: float, volume: float = 1_000.0) -> dict:
    mins = int(RTH_START_MINS) + minutes_after_open
    dt = datetime(session.year, session.month, session.day, mins // 60, mins % 60, tzinfo=ET)
    return {
        "timestamp": int(dt.timestamp() * 1000),
        "open": close - 0.05,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
        "volume": volume,
        "bar_start_ts_utc": dt.timestamp() - 60.0,
        "bar_end_ts_utc": dt.timestamp(),
    }


def test_friday_is_trading_day_saturday_is_not() -> None:
    assert is_trading_day_et(FRIDAY.isoformat()) is True
    assert is_trading_day_et(SATURDAY.isoformat()) is False


def test_first_positive_volume_rth_bar_produces_session_vwap() -> None:
    """After the first valid +volume RTH bar, canonical session VWAP exists (the rule names no
    ticker)."""
    bars = _bars_to_list([_rth_bar(FRIDAY, 0, 100.0, volume=2_500.0)])
    assert compute_session_vwap_series(bars, FRIDAY), "VWAP absent after the first +volume RTH bar"
    assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 1


def test_zero_volume_rth_bar_does_not_create_session_vwap() -> None:
    bars = _bars_to_list([_rth_bar(FRIDAY, 0, 100.0, volume=0.0)])
    assert compute_session_vwap_series(bars, FRIDAY) == []
    assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 0




def test_a_partly_recorded_session_has_a_vwap_point_for_each_minute_schwab_sent_and_no_other():
    """Real SPY 2026-09-23 as the capture daemon recorded it: 208 of the session's 390 minutes
    (from 09:35), each with Schwab's volume. The VWAP path has one point per recorded minute; the
    minutes the daemon did not record have none, never a filled-in point."""
    bars = console_bars("real_daemon_bars_spy_2026_09_23.json", "SPY")
    day = date(2026, 9, 23)
    rth = [b for b in _bars_to_list(bars) if b["_dt"].date() == day and session_label(b["_dt"]) == "RTH"]
    assert len(rth) == 208 and all(b["volume"] > 0 for b in rth)
    series = compute_session_vwap_series(_bars_to_list(bars), day)
    assert [p[0] for p in series] == [b["_dt"].timestamp() for b in rth]


def test_next_rth_after_saturday_2026_08_29_is_monday_2026_08_31() -> None:
    d = SATURDAY + timedelta(days=1)
    while not is_trading_day_et(d.isoformat()):
        d += timedelta(days=1)
    assert d == date(2026, 8, 31)
    assert d.strftime("%A") == "Monday"
