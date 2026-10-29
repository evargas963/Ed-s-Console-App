"""Session VWAP semantic fidelity — RTH availability, inside the regular session Schwab's
/markets sent (tests/conftest.py holds the answers captured 2026-10-07)."""

from __future__ import annotations

from datetime import date, timedelta

from liquidity_value_engine import (
    bars_from_candles,
    compute_session_vwap_series,
    count_session_rth_positive_volume_bars,
)
from micro_structure import Candle
from time_et import session

FRIDAY = date(2026, 10, 2)


def _rth_bar(day: date, minutes_after_open: int, close: float, volume: float = 1_000.0) -> Candle:
    dt = session(day.isoformat()).regular[0][0] + timedelta(minutes=minutes_after_open)
    return Candle(ts=dt.timestamp(), open=close - 0.05, high=close + 0.10, low=close - 0.10, close=close,
                  volume=volume)


def test_first_positive_volume_rth_bar_produces_session_vwap() -> None:
    """After the first valid +volume RTH bar, canonical session VWAP exists (the rule names no
    ticker)."""
    bars = bars_from_candles([_rth_bar(FRIDAY, 0, 100.0, volume=2_500.0)])
    assert compute_session_vwap_series(bars, FRIDAY), "VWAP absent after the first +volume RTH bar"
    assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 1


def test_zero_volume_rth_bar_does_not_create_session_vwap() -> None:
    bars = bars_from_candles([_rth_bar(FRIDAY, 0, 100.0, volume=0.0)])
    assert compute_session_vwap_series(bars, FRIDAY) == []
    assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 0
