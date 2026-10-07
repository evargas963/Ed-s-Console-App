"""ATR for the terrain radar — distance measured in what price can actually travel.

WHY ATR AND NOT PERCENT (operator 2026-07-19): percent means different things on
different instruments. 0.5% is a normal hour on SPY and noise on TSLA. ATR normalises
distance into "can price get there", which is the only question the radar answers.

TWO horizons, each answering a different question:
  * DAILY ATR  -> "reachable today"        — sets the radar ring (the triage decision)
  * 15-MIN ATR -> "reachable in the next few bars" — shown only on the focused contact,
                  so the scope stays readable

Both are computed from Schwab's own candles of that period (its /pricehistory daily and
15-minute candles, which the capture daemon asks for in every chain rotation).
"""

from __future__ import annotations

from dataclasses import dataclass

from math_volatility import compute_atr


#: ATR(14) needs 15 candles
ATR_PERIOD = 14


@dataclass(frozen=True)
class AtrPair:
    """Daily and 15-minute ATR in price points. Either may be None, with its reason."""

    daily: float | None
    m15: float | None
    daily_reason: str | None = None
    m15_reason: str | None = None


def _leg(candles: list, unit: str, series: str) -> tuple[float | None, str | None]:
    """ATR(ATR_PERIOD) of Schwab's `candles`, or None with why: fewer than ATR_PERIOD + 1 of them
    (none yet: 0)."""
    atr = compute_atr(candles, period=ATR_PERIOD)
    if atr is not None:
        return atr, None
    if len(candles) < ATR_PERIOD + 1:
        return None, (f"{len(candles)} {unit} of Schwab's {series} candles; "
                      f"ATR({ATR_PERIOD}) needs {ATR_PERIOD + 1}")
    return None, f"Schwab's {series} candles do not give a true range"


def compute_atr_pair(daily: list, m15: list) -> AtrPair:
    """Daily and 15-minute ATR of one ticker from Schwab's daily and 15-minute candles (oldest
    first; none from Schwab yet: empty), each None with its reason when it cannot be computed.
    The same rule for every ticker."""
    d, d_reason = _leg(daily, "trading days", "daily")
    m, m_reason = _leg(m15, "15-minute periods", "15-minute")
    return AtrPair(d, m, d_reason, m_reason)
