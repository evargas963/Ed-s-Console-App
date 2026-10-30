"""liquidity_value_engine chunk-1: lock I-01 fail-closed contracts (slice-only walk)."""

from __future__ import annotations

from datetime import date, datetime

from micro_structure import Candle
from time_et import ET
from liquidity_value_engine import bars_from_candles, compute_session_vwap_series


def test_session_vwap_absent_when_volume_missing():
    session = date(2026, 3, 13)
    dt = datetime(2026, 3, 13, 10, 0, tzinfo=ET)
    bars = [Candle(ts=dt.timestamp(), open=500.0, high=501.0, low=499.0, close=500.5, volume=None)]
    assert compute_session_vwap_series(bars_from_candles(bars), session) == []
