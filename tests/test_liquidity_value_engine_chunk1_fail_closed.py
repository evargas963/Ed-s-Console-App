"""liquidity_value_engine chunk-1: lock I-01 fail-closed contracts (slice-only walk).

Real data: SPY's first regular-session CHART_EQUITY bar of 2026-10-01 as the capture daemon recorded
it (real_daemon_bars_spy_tsla_2026_10_01_02.json). Induced (named): its volume taken out, as
Schwab leaves a field out.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from liquidity_value_engine import bars_from_candles, compute_session_vwap_series
from micro_structure import Candle
from tests.feed_live_helper import daemon_bars
from time_et import ET


def test_session_vwap_absent_when_volume_missing():
    session = date(2026, 10, 1)
    opening = datetime(2026, 10, 1, 9, 30, tzinfo=ET).timestamp() * 1000
    bar = next(
        b
        for b in daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY")
        if b["bar_start_ms"] == opening
    )
    sent = Candle(
        ts=bar["bar_start_ms"] / 1000,
        open=bar["open"],
        high=bar["high"],
        low=bar["low"],
        close=bar["close"],
        volume=bar["volume"],
    )
    assert compute_session_vwap_series(bars_from_candles([sent]), session) != []
    bars = [replace(sent, volume=None)]
    assert compute_session_vwap_series(bars_from_candles(bars), session) == []
