"""Action 12.6: micro_structure + liquidity_value_engine fail-closed (full read fixes)."""

from __future__ import annotations

from pathlib import Path

from micro_structure import Candle, detect_candle_patterns, detect_flag, collapse_sweep_alerts
from liquidity_value_engine import _cluster_reference_price
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def test_detect_candle_patterns_requires_spot():
    c = Candle(ts=0, open=100, high=101, low=99, close=100.5, volume=1000)
    assert detect_candle_patterns([c, c], spot=None) == []


def test_detect_flag_requires_spot():
    candles = [
        Candle(ts=i, open=100 + i * 0.1, high=101 + i * 0.1, low=99 + i * 0.1, close=100.5 + i * 0.1, volume=1000)
        for i in range(20)
    ]
    assert detect_flag(candles, spot=None) is None


def test_collapse_sweep_alerts_skips_events_without_level():
    sw = SimpleNamespace(type="sweep_low", held=False, level=None)
    assert collapse_sweep_alerts([sw]) == []


def test_cluster_reference_price_no_fabricated_500():
    assert _cluster_reference_price(None, None, None) is None
    assert _cluster_reference_price(450.25) == 450.25


def test_liquidity_engine_no_hardcoded_500_reference():
    text = (ROOT / "liquidity_value_engine.py").read_text(encoding="utf-8")
    assert " or 500.0" not in text


def test_micro_structure_no_spot_500_default():
    text = (ROOT / "micro_structure.py").read_text(encoding="utf-8")
    assert "spot: float = 500.0" not in text
