"""ATR for the terrain radar — distance measured in what price can actually travel.

Percent means different things on different instruments (0.5% is a normal hour on SPY and noise
on TSLA); ATR normalises distance into "can price get there".

Daily, weekly and monthly ATR(14), all from Schwab's daily candles (/pricehistory, asked once a
day): the weekly and monthly candles are the daily candles of each week and month rolled up, and
today's candle is the live one the console rolls up from today's 1-minute bars (server._atr).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from math_volatility import compute_atr
from micro_structure import Candle
from time_et import ET

#: ATR(14) needs 15 candles
ATR_PERIOD = 14


@dataclass(frozen=True)
class Atr:
    """Daily, weekly and monthly ATR in price points. Any may be None: Schwab did not send enough
    candles to compute it. Nothing stands in for the missing number."""

    daily: float | None
    weekly: float | None
    monthly: float | None


def roll_up(candles: list[Candle], key) -> list[Candle]:
    """`candles` (oldest first) rolled into one candle per `key` of each candle's ET date: the
    first open, the highest high, the lowest low, the last close."""
    out: list[Candle] = []
    last = None
    for c in candles:
        k = key(datetime.fromtimestamp(c.ts, ET).date())
        if k != last:
            out.append(Candle(ts=c.ts, open=c.open, high=c.high, low=c.low, close=c.close))
            last = k
        else:
            p = out[-1]
            out[-1] = Candle(
                ts=p.ts, open=p.open, high=max(p.high, c.high), low=min(p.low, c.low), close=c.close
            )
    return out


def _leg(candles: list) -> float | None:
    """ATR(ATR_PERIOD) of `candles`, or None when fewer than ATR_PERIOD + 1 of them give a true
    range."""
    return compute_atr(candles, period=ATR_PERIOD)


def compute_atrs(daily: list[Candle]) -> Atr:
    """Daily, weekly and monthly ATR of one ticker from its daily candles (oldest first, today's
    the live one). A horizon that cannot be computed is None."""
    return Atr(
        _leg(daily),
        _leg(roll_up(daily, lambda day: day.isocalendar()[:2])),
        _leg(roll_up(daily, lambda day: (day.year, day.month))),
    )
