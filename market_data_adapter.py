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
    volume: float = 0.0

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

    def _f(key: str, default: float = 0.0) -> float:
        v = raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    ts = None
    if isinstance(raw, dict):
        ts = raw.get("timestamp") or raw.get("datetime") or raw.get("t") or raw.get("time")
    else:
        ts = getattr(raw, "timestamp", None) or getattr(raw, "datetime", None)

    return NormalizedBar(
        timestamp=ts,
        open=_f("open", _f("o")),
        high=_f("high", _f("h")),
        low=_f("low", _f("l")),
        close=_f("close", _f("c")),
        volume=_f("volume", _f("vol", 0.0)),
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
        bar = {
            "datetime": ts,
            "timestamp": ts,
            "open": float(c.get("open", 0) or 0),
            "high": float(c.get("high", 0) or 0),
            "low": float(c.get("low", 0) or 0),
            "close": float(c.get("close", 0) or 0),
            "volume": float(c.get("volume", 0) or 0),
        }
        if ts is not None:
            bar["_ts"] = float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
        out.append(bar)
    return out
