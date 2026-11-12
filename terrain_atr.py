"""ATR for the terrain radar — distance measured in what price can actually travel.

Percent means different things on different instruments (0.5% is a normal hour on SPY and noise
on TSLA); ATR normalises distance into "can price get there".

Daily, weekly and monthly ATR(14) by Wilder's smoothing (math_volatility.compute_atr), each from
Schwab's own candles of that length (/pricehistory daily, weekly and monthly, as sent); today's
daily candle is the one Schwab pushes until its series holds the day (server._atr).
"""

from __future__ import annotations

from dataclasses import dataclass

from math_volatility import compute_atr
from micro_structure import Candle

#: ATR(14) needs 15 candles
ATR_PERIOD = 14


@dataclass(frozen=True)
class Atr:
    """Daily, weekly and monthly ATR in price points.

    Any may be None: Schwab did not send enough candles to compute it. Nothing stands in for the
    missing number.
    """

    daily: float | None
    weekly: float | None
    monthly: float | None


def compute_atrs(daily: list[Candle], weekly: list[Candle], monthly: list[Candle]) -> Atr:
    """Daily, weekly and monthly Wilder ATR(14) of one ticker, each from Schwab's candles.

    Each list is oldest first. A horizon with fewer than 14 true ranges is None.
    """
    return Atr(*(compute_atr(candles, period=ATR_PERIOD) for candles in (daily, weekly, monthly)))
