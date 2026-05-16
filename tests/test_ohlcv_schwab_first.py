"""Day 1 — OHLCV bar adapters (DFR-009, DFR-011, MT-006, MT-007, PQ-009, DFR-018 re-audit)."""

from __future__ import annotations

import re
from pathlib import Path

from market_data_adapter import normalize_bar, schwab_candles_to_bars
from snapshot_normalizer import resample_to_1m

ROOT = Path(__file__).resolve().parent.parent


def test_normalize_bar_rejects_missing_close():
    assert normalize_bar({"open": 1.0, "high": 2.0, "low": 0.5, "close": None}) is None


def test_normalize_bar_rejects_zero_close():
    assert (
        normalize_bar(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 0, "volume": 100},
            source="schwab_pricehistory",
        )
        is None
    )


def test_normalize_bar_emits_source_and_missing_fields():
    nb = normalize_bar(
        {
            "datetime": 1_710_000_000_000,
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
            "volume": 1200,
        },
        source="schwab_pricehistory",
    )
    assert nb is not None
    d = nb.to_dict()
    assert d["source"] == "schwab_pricehistory"
    assert d["missing_fields"] == []


def test_schwab_candles_to_bars_rejects_zero_close():
    candles = [
        {
            "datetime": 1_710_000_000_000,
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 0.0,
            "volume": 100,
        }
    ]
    assert schwab_candles_to_bars(candles) == []


def test_resample_synthetic_bars_are_tagged():
    rows = [
        {
            "ts_utc": 1_710_000_060.0,
            "ticker": "SPY",
            "candle_open": 500.0,
            "candle_high": 501.0,
            "candle_low": 499.0,
            "candle_close": 500.5,
            "candle_volume": 1000,
            "spot": 500.5,
        }
    ]
    out = resample_to_1m(rows, "SPY")
    assert len(out) == 1
    assert out[0]["synthetic"] is True
    assert out[0]["source"] == "snapshot_synthetic"


def test_resample_skips_bucket_with_no_open_or_spot():
    rows = [
        {
            "ts_utc": 1_710_000_060.0,
            "ticker": "SPY",
            "candle_high": 501.0,
            "candle_low": 499.0,
            "candle_close": 500.5,
        }
    ]
    assert resample_to_1m(rows, "SPY") == []


def test_market_data_adapter_no_zero_injection_pattern():
    text = (ROOT / "market_data_adapter.py").read_text(encoding="utf-8")
    assert not re.search(
        r"(?:float|int)\([^)]*\.get\([^)]*,\s*0\s*\)\s*(?:or\s*0)?",
        text,
    )


def test_snapshot_normalizer_no_open_zero_fallback():
    text = (ROOT / "snapshot_normalizer.py").read_text(encoding="utf-8")
    assert "o = 0.0" not in text


def test_liquidity_value_engine_no_ohlcv_zero_injection_pattern():
    text = (ROOT / "liquidity_value_engine.py").read_text(encoding="utf-8")
    assert not re.search(
        r'\.get\("(open|high|low|close)"\s*,\s*0\)',
        text,
    )
