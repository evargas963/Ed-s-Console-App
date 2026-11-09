"""Volatility-derived transforms: the average true range.

math_volatility.py
"""

from __future__ import annotations

from micro_structure import Candle

# ── ATR (Average True Range) ────────────────────────────────────────────────


def compute_atr(candles: list[Candle], *, period: int = 14) -> float | None:
    """Return Wilder's Average True Range of OHLC candles.

    Wilder (1978), New Concepts in Technical Trading Systems:
    TR =max(high - low, abs(high - prev_close), abs(low - prev_close)). The first ATR is the
    simple mean of the first `period` TRs; each later one is
    ATR_t = (ATR_(t-1) * (period - 1) + TR_t) / period.

    Args:
        candles:  Schwab's candles, oldest first
        period:   ATR lookback period (default 14)

    Returns ATR in price points, or None with fewer than `period` TRs.
    """
    trs = [
        max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        for p, c in zip(candles, candles[1:], strict=False)
    ]
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr
