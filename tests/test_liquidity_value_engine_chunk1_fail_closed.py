"""liquidity_value_engine chunk-1: lock I-01 fail-closed contracts (slice-only walk)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from zoneinfo import ZoneInfo

from time_et import ET
from liquidity_value_engine import (
    _cluster_reference_price,
    _schwab_pricehistory_bar_missing_datetime,
    compute_atr_from_bars,
    compute_session_vwap,
    generate_liquidity_value_snapshot,
)


def test_cluster_reference_price_none_when_all_candidates_invalid():
    assert _cluster_reference_price(None, 0, -1.0, "") is None


def test_schwab_pricehistory_bar_missing_datetime_when_datetime_absent():
    bar = {"source": "schwab_pricehistory", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}
    assert _schwab_pricehistory_bar_missing_datetime(bar) is True


def test_compute_session_vwap_none_when_volume_missing():
    session = date(2026, 3, 13)
    dt = datetime(2026, 3, 13, 10, 0, tzinfo=ET)
    bars = [
        {
            "timestamp": int(dt.timestamp() * 1000),
            "_ts": dt.timestamp(),
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
        }
    ]
    assert compute_session_vwap(bars, session) is None


def test_compute_atr_from_bars_none_when_insufficient_rth_bars():
    session = date(2026, 3, 13)
    dt = datetime(2026, 3, 13, 10, 0, tzinfo=ET)
    bars = [
        {
            "timestamp": int(dt.timestamp() * 1000),
            "_ts": dt.timestamp(),
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
            "volume": 1000.0,
        }
    ]
    assert compute_atr_from_bars(bars, session, period=14) is None


def test_generate_liquidity_value_snapshot_raises_on_unknown_type():
    with pytest.raises(ValueError, match=r"not a valid SnapshotType|Unknown snapshot_type"):
        generate_liquidity_value_snapshot("SPY", [], "2026-03-13", "not_a_checkpoint")
