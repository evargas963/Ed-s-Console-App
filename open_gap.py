"""The open-gap record (EXPERIMENTAL): how often the overnight gap's direction matched the first
five minutes' direction, for one ticker (operator 2026-11-15: "build something experimental and
continue to monitor it on a daily basis as we gather more data"; ACTIVE_PROGRAM.md OPEN-5MIN).

From Schwab's 5-minute /pricehistory bars with extended hours, as sent. For each ET day that has
a prior regular session, a pre-market bar (04:00-09:30 ET) and a 09:30 bar that moved:
  gap         the pre-market's last close / the prior regular session's last close - 1
  first five  the 09:30 bar's close - its open
The record: the opens, how many the gap's sign matched the first five minutes' sign, and the 95%
Wilson interval of that share (one open per ticker per day). Registered in
docs/derived_register.md. A calculator: no clock, no database.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from time_et import ET

PRE_MARKET = (time(4, 0), time(9, 30))
OPEN_BAR = time(9, 30)
REGULAR = (time(9, 30), time(16, 0))
#: the 95% interval's z
Z95 = 1.959964


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


def open_gap_record(candles: Iterable[Mapping[str, Any]]) -> OpenGapRecord | None:
    """The record over Schwab's 5-minute candles with extended hours; None when no open counts.

    A candle's datetime is Schwab's epoch milliseconds; its open and close as sent. An open whose
    gap is 0 or whose first five minutes did not move has no direction and is not counted.
    """
    by_day: dict[date, list[tuple[time, Mapping[str, Any]]]] = defaultdict(list)
    for c in candles:
        t = datetime.fromtimestamp(c["datetime"] / 1000, ET)
        by_day[t.date()].append((t.time(), c))
    prior: float | None = None
    days: list[date] = []
    matched = 0
    for day in sorted(by_day):
        bars = sorted(by_day[day], key=lambda x: x[0])
        pre = [c for t, c in bars if PRE_MARKET[0] <= t < PRE_MARKET[1]]
        first = [c for t, c in bars if t == OPEN_BAR]
        regular = [c for t, c in bars if REGULAR[0] <= t < REGULAR[1]]
        if prior is not None and pre and first:
            gap = pre[-1]["close"] / prior - 1
            move = first[0]["close"] - first[0]["open"]
            if gap != 0 and move != 0:
                days.append(day)
                matched += (gap > 0) == (move > 0)
        if regular:
            prior = regular[-1]["close"]
    if not days:
        return None
    low, high = wilson(matched, len(days))
    return OpenGapRecord(len(days), matched, low, high, days[0], days[-1])
