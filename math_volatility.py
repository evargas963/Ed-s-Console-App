"""Volatility-derived transforms: the average true range.

math_volatility.py
"""

from __future__ import annotations

from micro_structure import Candle

# ── ATR (Average True Range) ────────────────────────────────────────────────


def compute_atr(candles: list[Candle], *, period: int = 14) -> float | None:
    """
    Average True Range from OHLC candles.

    Formula:
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ATR = SMA(TR, period)

    Args:
        candles:  Schwab's candles, oldest first
        period:   ATR lookback period (default 14)

    Returns ATR in price points, or None if insufficient data.
    """
    if not candles or len(candles) < period + 1:
        return None

    trs = []
    prev_close = None
    for candle in candles:
        h, lo = candle.high, candle.low
        if prev_close is not None:
            tr = max(h - lo, abs(h - prev_close), abs(lo - prev_close))
            trs.append(tr)

        prev_close = candle.close

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period
