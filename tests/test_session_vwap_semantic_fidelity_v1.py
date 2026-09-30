"""Session VWAP semantic fidelity — RTH availability."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from liquidity_value_engine import (
    _bars_to_list,
    compute_session_vwap_series,
    count_session_rth_positive_volume_bars,
)
from time_et import ET, RTH_START_MINS, is_trading_day_et

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




def test_next_rth_after_saturday_2026_08_29_is_monday_2026_08_31() -> None:
    d = SATURDAY + timedelta(days=1)
    while not is_trading_day_et(d.isoformat()):
        d += timedelta(days=1)
    assert d == date(2026, 8, 31)
    assert d.strftime("%A") == "Monday"
