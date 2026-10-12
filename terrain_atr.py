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
    """Daily, weekly and monthly ATR in price points. Any may be None, with its reason."""

    daily: float | None
    weekly: float | None
    monthly: float | None
    daily_reason: str | None = None
    weekly_reason: str | None = None
    monthly_reason: str | None = None


def roll_up(candles: "list[Candle]", key) -> "list[Candle]":
    """`candles` (oldest first) rolled into one candle per `key` of each candle's ET date: the
    first open, the highest high, the lowest low, the last close."""
    out: "list[Candle]" = []
    last = None
    for c in candles:
        k = key(datetime.fromtimestamp(c.ts, ET).date())
        if k != last:
            out.append(Candle(ts=c.ts, open=c.open, high=c.high, low=c.low, close=c.close))
            last = k
        else:
            p = out[-1]
            out[-1] = Candle(ts=p.ts, open=p.open, high=max(p.high, c.high), low=min(p.low, c.low), close=c.close)
    return out


def _leg(candles: list, unit: str) -> tuple[float | None, str | None]:
    """ATR(ATR_PERIOD) of `candles`, or None with why: fewer than ATR_PERIOD + 1 of them."""
    atr = compute_atr(candles, period=ATR_PERIOD)
    if atr is not None:
        return atr, None
    if len(candles) < ATR_PERIOD + 1:
        return None, f"{len(candles)} {unit} of Schwab's daily candles; ATR({ATR_PERIOD}) needs {ATR_PERIOD + 1}"
    return None, f"Schwab's daily candles do not give a {unit[:-1]} true range"


def compute_atrs(daily: "list[Candle]") -> Atr:
    """Daily, weekly and monthly ATR of one ticker from its daily candles (oldest first, today's
    the live one), each None with its reason when it cannot be computed."""
    d = _leg(daily, "days")
    w = _leg(roll_up(daily, lambda day: day.isocalendar()[:2]), "weeks")
    m = _leg(roll_up(daily, lambda day: (day.year, day.month)), "months")
    return Atr(d[0], w[0], m[0], d[1], w[1], m[1])
