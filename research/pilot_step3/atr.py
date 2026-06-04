"""
Wilder (RMA) ATR-14 on 1m bars for pilot label construction.

Do not use math_volatility.compute_atr (SMA of TR) for authoritative pilot labels.
"""

from __future__ import annotations

from typing import Sequence


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def wilder_atr_14(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    period: int = 14,
) -> list[float | None]:
    """
    Wilder / smoothed ATR: first ATR = mean(TR[1:period]); then
    ATR_i = (ATR_{i-1} * (period - 1) + TR_i) / period.

    Returns list aligned with closes index i; first `period` entries are None
    (insufficient history for a full ATR at i). Pilot labeling uses ATR at
    index i_sig - 1 for an event at signal bar i_sig (T-1 anchor).
    """
    n = len(closes)
    if n == 0 or len(highs) != n or len(lows) != n:
        raise ValueError("highs, lows, closes must have equal length")
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    trs: list[float] = []
    prev_c = float(closes[0])
    for i in range(1, n):
        tr = true_range(float(highs[i]), float(lows[i]), prev_c)
        trs.append(tr)
        prev_c = float(closes[i])

    # trs[j] corresponds to bar index j+1
    if len(trs) < period:
        return out

    # Initial ATR at index (period) using mean of first `period` TRs (bars 1..period)
    first_mean = sum(trs[:period]) / float(period)
    atr_idx = period  # first full ATR aligns with close index `period`
    out[atr_idx] = first_mean
    atr = first_mean
    for j in range(period, len(trs)):
        i = j + 1  # bar index
        atr = (atr * (period - 1) + trs[j]) / float(period)
        out[i] = atr
    return out
