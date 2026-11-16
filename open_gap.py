"""The open-gap record (EXPERIMENTAL): how often the overnight gap's direction matched the first
five minutes' direction, for one ticker (operator 2026-11-15: "build something experimental and
continue to monitor it on a daily basis as we gather more data"; ACTIVE_PROGRAM.md OPEN-5MIN).

From two of Schwab's 5-minute /pricehistory answers, as sent: the regular session's bars alone
(series 5m365r) and the bars with extended hours (5m365). Schwab's regular bars mark each day's
session (AGENTS.md rule 8: no session time is typed): a day's first regular bar is its open, its
last the day's close, and the extended bars of that date before the open are its pre-market. For
each day with a prior regular session, a pre-market bar and an open bar that moved:
  gap         the pre-market's last close / the prior regular session's last close - 1
  first five  the open bar's close - its open
The record: the opens, how many the gap's sign matched the first five minutes' sign, and the 95%
Wilson interval of that share (one open per ticker per day). Registered in
docs/derived_register.md. A calculator: no clock, no database.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from time_et import ET

#: the 95% interval's z
Z95 = 1.959964

type Candle = Mapping[str, Any]


@dataclass(frozen=True)
class OpenGapRecord:
    """One ticker's record of the gap's direction against the first five minutes' direction."""

    opens: int  # the opens with a gap and a first five minutes that moved
    matched: int  # of them, the gap's sign matched the first five minutes'
    low: float  # the 95% Wilson interval of matched / opens
    high: float
    first_day: date
    last_day: date


def wilson(matched: int, opens: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval of the share matched / opens (opens > 0)."""
    p = matched / opens
    d = 1 + z * z / opens
    centre = (p + z * z / (2 * opens)) / d
    half = z * math.sqrt(p * (1 - p) / opens + z * z / (4 * opens * opens)) / d
    return centre - half, centre + half


def _by_day(candles: Iterable[Candle]) -> dict[date, list[Candle]]:
    days: dict[date, list[Candle]] = defaultdict(list)
    for c in sorted(candles, key=lambda c: c["datetime"]):
        days[datetime.fromtimestamp(c["datetime"] / 1000, ET).date()].append(c)
    return days


def open_gap_record(regular: Iterable[Candle], extended: Iterable[Candle]) -> OpenGapRecord | None:
    """The record over Schwab's regular-session and extended-hours 5-minute candles.

    A candle's datetime is Schwab's epoch milliseconds; its open and close as sent. None when no
    open counts. An open whose gap is 0 or whose first five minutes did not move has no direction
    and is not counted.
    """
    sessions = _by_day(regular)
    hours = _by_day(extended)
    prior: float | None = None
    days: list[date] = []
    matched = 0
    for day in sorted(sessions):
        opening = sessions[day][0]
        pre = [c for c in hours[day] if c["datetime"] < opening["datetime"]]  # a day none: []
        if prior is not None and pre:
            gap = pre[-1]["close"] / prior - 1
            move = opening["close"] - opening["open"]
            if gap != 0 and move != 0:
                days.append(day)
                matched += (gap > 0) == (move > 0)
        prior = sessions[day][-1]["close"]
    if not days:
        return None
    low, high = wilson(matched, len(days))
    return OpenGapRecord(len(days), matched, low, high, days[0], days[-1])
