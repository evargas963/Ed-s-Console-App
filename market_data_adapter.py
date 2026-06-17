"""
market_data_adapter.py — Normalized OHLCV data layer
=====================================================
Consumes data from any transport (WebSocket, SSE, polling) and emits
a unified bar format for the liquidity_value_engine.

Output: list of dicts with keys:
  timestamp, open, high, low, close, volume, source, missing_fields

The engine is transport-agnostic; it only sees normalized bars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# Canonical bar keys expected by liquidity_value_engine
BAR_KEYS = ("timestamp", "open", "high", "low", "close", "volume", "source", "missing_fields")

_OHLC_KEYS = ("open", "high", "low", "close")

# Schwab field dictionary mapping (pricehistory.candles.*)
SCHWAB_CANDLE_LEAF_MAP: dict[str, str] = {
    "open": "pricehistory.candles.*.open",
    "high": "pricehistory.candles.*.high",
    "low": "pricehistory.candles.*.low",
    "close": "pricehistory.candles.*.close",
    "volume": "pricehistory.candles.*.volume",
    "datetime": "pricehistory.candles.*.datetime",
}


@dataclass
class NormalizedBar:
    """Single OHLCV bar in canonical format."""
    timestamp: Any  # datetime or epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    source: str = ""
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "source": self.source,
            "missing_fields": list(self.missing_fields),
        }


def normalize_bar(raw: dict | Any, *, source: str = "") -> Optional[NormalizedBar]:
    """
    Convert a raw bar into NormalizedBar.

    Reads the canonical Schwab keys directly: ``open``, ``high``, ``low``,
    ``close``, ``volume`` (per Schwab field dictionary
    ``pricehistory.candles.*``) and the canonical timestamp key
    ``datetime`` (Schwab pricehistory) or ``timestamp`` (NormalizedBar).

    Rejects bars with any OHLC missing or ``close == 0``. Emits ``missing_fields``
    (empty when clean) and ``source`` when provided by the caller.
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
            return None
        try:
            out = float(v)
        except (TypeError, ValueError):
            return None
        return out if out >= 0 else None

    missing_fields: list[str] = []

    if isinstance(raw, dict):
        if source == "schwab_pricehistory":
            ts = raw.get("datetime")
            if ts is None:
                missing_fields.append("datetime")
        else:
            ts = raw.get("datetime") if raw.get("datetime") is not None else raw.get("timestamp")
    else:
        ts = getattr(raw, "datetime", None) if source == "schwab_pricehistory" else getattr(
            raw, "timestamp", None
        )
    open_ = _f("open")
    high = _f("high")
    low = _f("low")
    close = _f("close")
    for key, val in zip(_OHLC_KEYS, (open_, high, low, close), strict=True):
        if val is None:
            missing_fields.append(key)
    if missing_fields:
        log.debug("normalize_bar rejected: missing OHLC/datetime %s", missing_fields)
        return None
    if close == 0:
        log.debug("normalize_bar rejected: close == 0")
        return None

    vol = _volume()
    if isinstance(raw, dict) and raw.get("volume") is None:
        missing_fields.append("volume")

    return NormalizedBar(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=vol,
        source=source,
        missing_fields=missing_fields,
    )


def normalize_bars(raw_bars: list, *, source: str = "") -> list[dict]:
    """Convert a list of raw bars to engine-ready dicts."""
    out = []
    for b in raw_bars or []:
        nb = normalize_bar(b, source=source)
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
        raw = dict(c)
        nb = normalize_bar(raw, source="schwab_pricehistory")
        if nb is None:
            continue
        bar = nb.to_dict()
        ts = c.get("datetime")
        if ts is not None:
            try:
                ts_f = float(ts)
                bar["_ts"] = ts_f / 1000.0 if ts_f > 1e12 else ts_f
            except (TypeError, ValueError):
                pass
        out.append(bar)
    return out
