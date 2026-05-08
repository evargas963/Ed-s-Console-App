"""
market_data_adapter.py — Normalized OHLCV data layer
=====================================================
Consumes data from any transport (WebSocket, SSE, polling) and emits
a unified bar format for the liquidity_value_engine.

Output: list of dicts with keys:
  timestamp, open, high, low, close, volume

The engine is transport-agnostic; it only sees normalized bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

# Canonical bar keys expected by liquidity_value_engine
BAR_KEYS = ("timestamp", "open", "high", "low", "close", "volume")


@dataclass
class NormalizedBar:
    """Single OHLCV bar in canonical format."""
    timestamp: Any  # datetime or epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


def normalize_bar(raw: dict | Any) -> Optional[NormalizedBar]:
    """
    Convert a raw bar from any provider into NormalizedBar.
    Handles: Schwab candles, Polygon, Alpaca, generic OHLCV.
    """
    if raw is None:
        return None

    def _f(key: str) -> Optional[float]:
        v = raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _volume() -> Optional[float]:
        v = raw.get("volume") if isinstance(raw, dict) else getattr(raw, "volume", None)
        if v is None:
            v = raw.get("vol") if isinstance(raw, dict) else getattr(raw, "vol", None)
        if v is None:
            return None
        try:
            out = float(v)
        except (TypeError, ValueError):
            return None
        return out if out >= 0 else None

    ts = None
    if isinstance(raw, dict):
        ts = raw.get("timestamp") or raw.get("datetime") or raw.get("t") or raw.get("time")
    else:
        ts = getattr(raw, "timestamp", None) or getattr(raw, "datetime", None)

    open_ = _f("open")
    if open_ is None:
        open_ = _f("o")
    high = _f("high")
    if high is None:
        high = _f("h")
    low = _f("low")
    if low is None:
        low = _f("l")
    close = _f("close")
    if close is None:
        close = _f("c")
    if open_ is None or high is None or low is None or close is None:
        return None

    return NormalizedBar(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=_volume(),
    )


def normalize_bars(raw_bars: list) -> list[dict]:
    """Convert a list of raw bars to engine-ready dicts."""
    out = []
    for b in raw_bars or []:
        nb = normalize_bar(b)
        if nb:
            out.append(nb.to_dict())
    return out


# ── Schwab-specific: candles from get_price_history ───────────────────────────
# Used when integrating with existing Schwab client. Engine stays agnostic;
# this adapter bridges Schwab response → normalized bars.


def schwab_candles_to_bars(candles: list) -> list[dict]:
    """
    Convert Schwab price history candles to normalized bars.
    Schwab format: { datetime: ms, open, high, low, close, volume }
    Sets _ts (epoch seconds) for engine time filtering.
    """
    out = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        ts = c.get("datetime")
        try:
            open_ = float(c["open"])
            high = float(c["high"])
            low = float(c["low"])
            close = float(c["close"])
        except (KeyError, TypeError, ValueError):
            continue
        bar = {
            "datetime": ts,
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": float(c["volume"]) if c.get("volume") is not None else None,
        }
        if ts is not None:
            bar["_ts"] = float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
        out.append(bar)
    return out
