"""liquidity_value_engine chunk-1: lock I-01 fail-closed contracts (slice-only walk)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from time_et import ET
from liquidity_value_engine import (
    compute_session_vwap,
    generate_liquidity_value_snapshot,
)


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


def test_generate_liquidity_value_snapshot_raises_on_unknown_type():
    with pytest.raises(ValueError, match=r"not a valid SnapshotType|Unknown snapshot_type"):
        generate_liquidity_value_snapshot("SPY", [], "2026-03-13", "not_a_checkpoint")
