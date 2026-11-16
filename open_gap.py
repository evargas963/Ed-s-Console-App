"""The open-gap record (EXPERIMENTAL): how the overnight gap's direction has matched the first
five minutes' direction, for one ticker (operator 2026-11-15: "build something experimental and
continue to monitor it on a daily basis as we gather more data"; the mock-up he approved:
"approved, build it"; ACTIVE_PROGRAM.md OPEN-5MIN).

From two of Schwab's 5-minute /pricehistory answers, as sent: the regular session's bars alone
(series 5m365r) and the bars with extended hours (5m365). Schwab's regular bars mark each day's
session (AGENTS.md rule 8: no session time is typed): a day's first regular bar is its open, its
last the day's close, and the extended bars of that date before the open are its pre-market. For
each day with a prior regular session, a pre-market bar and an open bar that moved:
  gap         the pre-market's last close / the prior regular session's last close - 1
  first five  the open bar's close / its open - 1
The record: every such open, and how many of the up gaps and of the down gaps the first five
minutes followed, each with its 95% Wilson interval (one open per ticker per day).

Today's open, by the same definition, from Schwab's 5-minute bars of today (the console's `5m`
series) and today's and the prior session's regular windows as Schwab's /markets answered them.

Registered in docs/derived_register.md. A calculator: no clock, no database.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from micro_structure import Candle
from time_et import ET, Session

#: the 95% interval's z
Z95 = 1.959964
#: the opens the track record shows, newest first
LAST_OPENS = 10

type SchwabCandle = Mapping[str, Any]


@dataclass(frozen=True)
class Open:
    """One open: its day, the overnight gap and the first five minutes, each a fraction."""

    day: date
    gap: float
    first_five: float

    @property
    def called(self) -> bool:
        """Whether the first five minutes went the way the gap pointed."""
        return (self.gap > 0) == (self.first_five > 0)


@dataclass(frozen=True)
class Followed:
    """How many opens of one gap direction the first five minutes followed."""

    opens: int
    matched: int
    low: float  # the 95% Wilson interval of matched / opens
    high: float


@dataclass(frozen=True)
class OpenGapRecord:
    """One ticker's opens, and how the up gaps and the down gaps were followed."""

    opens: tuple[Open, ...]  # oldest first
    up: Followed | None  # None: no up gap counted
    down: Followed | None


def wilson(matched: int, opens: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval of the share matched / opens (opens > 0)."""
    p = matched / opens
    d = 1 + z * z / opens
    centre = (p + z * z / (2 * opens)) / d
    half = z * math.sqrt(p * (1 - p) / opens + z * z / (4 * opens * opens)) / d
    return centre - half, centre + half


def _followed(opens: Sequence[Open]) -> Followed | None:
    if not opens:
        return None
    matched = sum(o.called for o in opens)
    low, high = wilson(matched, len(opens))
    return Followed(len(opens), matched, low, high)


def _by_day(candles: Iterable[SchwabCandle]) -> dict[date, list[SchwabCandle]]:
    days: dict[date, list[SchwabCandle]] = defaultdict(list)
    for c in sorted(candles, key=lambda c: c["datetime"]):
        days[datetime.fromtimestamp(c["datetime"] / 1000, ET).date()].append(c)
    return days


def open_gap_record(
    regular: Iterable[SchwabCandle], extended: Iterable[SchwabCandle]
) -> OpenGapRecord | None:
    """The record over Schwab's regular-session and extended-hours 5-minute candles.

    A candle's datetime is Schwab's epoch milliseconds; its open and close as sent. None when no
    open counts. An open whose gap is 0 or whose first five minutes did not move has no direction
    and is not counted.
    """
    sessions = _by_day(regular)
    hours = _by_day(extended)
    prior: float | None = None
    opens: list[Open] = []
    for day in sorted(sessions):
        opening = sessions[day][0]
        pre = [c for c in hours[day] if c["datetime"] < opening["datetime"]]  # a day none: []
        if prior is not None and pre:
            gap = pre[-1]["close"] / prior - 1
            move = opening["close"] / opening["open"] - 1
            if gap != 0 and move != 0:
                opens.append(Open(day, gap, move))
        prior = sessions[day][-1]["close"]
    if not opens:
        return None
    return OpenGapRecord(
        tuple(opens),
        _followed([o for o in opens if o.gap > 0]),
        _followed([o for o in opens if o.gap < 0]),
    )


#: the length of one of Schwab's 5-minute bars, in seconds: an open bar is whole once it has passed
BAR_SECONDS = 300.0


def today_open(
    candles: Sequence[Candle], today: Session, prior: Session, now: float
) -> Open | None:
    """Today's open from Schwab's 5-minute bars (`candles`, oldest first) once its bar is whole.

    `today` and `prior` are the day's and the prior session's regular windows as Schwab's /markets
    answered them; `now` the time it is read. As the record defines it: the pre-market is today's
    bars before the open. None until the open bar has closed, or without a pre-market bar or a
    bar of the prior session; an open that did not move, or no gap, has no direction (None).
    """
    opened_at = today.regular[0][0]
    opened = opened_at.timestamp()
    prior_start, prior_end = prior.regular[0][0].timestamp(), prior.regular[-1][1].timestamp()
    first = [c for c in candles if c.ts == opened]
    pre = [
        c
        for c in candles
        if c.ts < opened and datetime.fromtimestamp(c.ts, ET).date() == opened_at.date()
    ]
    before = [c for c in candles if prior_start <= c.ts < prior_end]
    if now < opened + BAR_SECONDS or not first or not pre or not before:
        return None
    gap = pre[-1].close / before[-1].close - 1
    move = first[0].close / first[0].open - 1
    if gap == 0 or move == 0:
        return None
    return Open(today.regular[0][0].date(), gap, move)
