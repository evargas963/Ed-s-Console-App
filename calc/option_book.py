"""Options Level II: each contract's resting book and volume, their summary and the options lean.

Schwab sends each contract's book (OPTIONS_BOOK, every level's TOTAL_VOLUME) and its volume today
(LEVELONE_OPTIONS TOTAL_VOLUME), not their totals, shares or a lean. Each is computed here, once
(docs/derived_register.md, the Options Level II rows). A Calculator: it takes its inputs and reads
no clock, State, database or network (AGENTS.md rule 11).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from calc.order_flow import Book
from calc.terrain_engine import side_total

#: the five zones of the lean, from -1 to +1 in equal fifths
ZONES = ("Defensive", "Leaning defensive", "Neutral", "Leaning constructive", "Constructive")
#: the edges between the zones; a lean on an edge is in the zone above it
ZONE_EDGES = (-0.6, -0.2, 0.2, 0.6)
#: the needle's swing: a lean of +1 points this many degrees right of upright, -1 as far left
NEEDLE_SWING_DEG = 90.0
#: the two sides of a listing, as Schwab names them (putCall)
CALL, PUT = "CALL", "PUT"


@dataclass(frozen=True)
class Leg:
    """One contract's cells: its resting bid and ask sizes and its volume today.

    A resting size is the sum of TOTAL_VOLUME over every level of that side of the contract's
    newest OPTIONS_BOOK (a side the book has no level on is 0); both are None while no book is
    held. The volume is the contract's as the chain screens show it; None when not known.
    """

    symbol: str
    bid: float | None
    ask: float | None
    volume: float | None


def leg(symbol: str, book: Book | None, volume: float | None) -> Leg:
    """Return a contract's cells from its newest book (None: none held) and its volume today."""
    if book is None:
        return Leg(symbol, None, None, volume)
    return Leg(
        symbol,
        math.fsum(level[1] for level in book.bids),
        math.fsum(level[1] for level in book.asks),
        volume,
    )


@dataclass(frozen=True)
class BookRow:
    """One row of the Book: a strike, the call and the put listed at it (None: none listed).

    `summed`: both have a book, so the row is in the summary.
    """

    strike: float
    call: Leg | None
    put: Leg | None
    summed: bool


def book_rows(listed: Sequence[tuple[float, str, Leg]]) -> list[BookRow]:
    """Return the Book's rows of `listed` contracts, each (strike, CALL or PUT, its cells).

    Strikes high to low, as the chain ladder lists them; a second contract listed at one strike
    and side gets its own row, paired with the second of the other side.
    """
    by_strike: dict[float, dict[str, list[Leg]]] = {}
    for strike, side, cells in listed:
        by_strike.setdefault(strike, {CALL: [], PUT: []})[side].append(cells)
    rows: list[BookRow] = []
    for strike in sorted(by_strike, reverse=True):
        calls, puts = by_strike[strike][CALL], by_strike[strike][PUT]
        for i in range(max(len(calls), len(puts))):
            call = calls[i] if i < len(calls) else None
            put = puts[i] if i < len(puts) else None
            booked = (
                call is not None
                and put is not None
                and call.bid is not None
                and put.bid is not None
            )
            rows.append(BookRow(strike, call, put, booked))
    return rows


@dataclass(frozen=True)
class Scales:
    """The largest resting size and the largest volume of the rows: each bar's full length.

    None when the rows hold no such value.
    """

    resting: float | None
    volume: float | None


def scales(rows: Sequence[BookRow]) -> Scales:
    """Return the rows' scales: resting sizes on one, volumes on their own."""
    legs = [x for r in rows for x in (r.call, r.put) if x is not None]
    resting = [v for x in legs for v in (x.bid, x.ask) if v is not None]
    volume = [x.volume for x in legs if x.volume is not None]
    return Scales(max(resting, default=None), max(volume, default=None))


@dataclass(frozen=True)
class Split:
    """One summary bar: two totals and each one's share of their sum.

    A total is None when not known; the shares are None unless both are known and their sum is
    above 0.
    """

    left: float | None
    right: float | None
    left_share: float | None
    right_share: float | None


def split(left: float | None, right: float | None) -> Split:
    """Return the split of two totals."""
    if left is None or right is None or left + right <= 0:
        return Split(left, right, None, None)
    total = left + right
    return Split(left, right, left / total, right / total)


def _tilt(s: Split) -> float | None:
    """Return (left - right) / (left + right), -1 to +1; None unless the shares are known."""
    if s.left is None or s.right is None or s.left_share is None:
        return None
    return (s.left - s.right) / (s.left + s.right)


@dataclass(frozen=True)
class Lean:
    """The options lean: the plain average of three readings, each from -1 to +1.

    `calls`: the calls' resting (bid - ask) / (bid + ask); `puts`: the puts' resting
    (ask - bid) / (bid + ask), put buyers waiting read as protection, defensive; `volume`:
    (calls - puts) / (calls + puts) of volume today. `value` is None unless all three are known;
    `zone` its place among ZONES (`zone_index`), and `needle_deg` the gauge needle's angle from
    upright, positive to the right.
    """

    calls: float | None
    puts: float | None
    volume: float | None
    value: float | None
    zone_index: int | None
    zone: str | None
    needle_deg: float | None


def lean(calls: Split, puts: Split, volume: Split) -> Lean:
    """Return the options lean of the summary's three splits."""
    c, v = _tilt(calls), _tilt(volume)
    p = _tilt(Split(puts.right, puts.left, puts.right_share, puts.left_share))
    if c is None or p is None or v is None:
        return Lean(c, p, v, None, None, None, None)
    value = (c + p + v) / 3.0
    zone = bisect_right(ZONE_EDGES, value)
    return Lean(c, p, v, value, zone, ZONES[zone], value * NEEDLE_SWING_DEG)


@dataclass(frozen=True)
class BookSummary:
    """The summary of the rows: over the rows whose call and put both have a book.

    `strikes`: those rows' strikes, ascending; `left_out`: the rows shown and not summed. The
    calls' and the puts' resting bid against ask, volume today calls against puts, and the lean.
    """

    strikes: tuple[float, ...]
    left_out: int
    calls: Split
    puts: Split
    volume: Split
    lean: Lean


def summary(rows: Sequence[BookRow]) -> BookSummary:
    """Return the summary of the Book's rows."""
    summed = [r for r in rows if r.summed]
    calls = [r.call for r in summed if r.call is not None]
    puts = [r.put for r in summed if r.put is not None]
    c = split(side_total([x.bid for x in calls]), side_total([x.ask for x in calls]))
    p = split(side_total([x.bid for x in puts]), side_total([x.ask for x in puts]))
    v = split(side_total([x.volume for x in calls]), side_total([x.volume for x in puts]))
    return BookSummary(
        tuple(sorted({r.strike for r in summed})),
        len(rows) - len(summed),
        c,
        p,
        v,
        lean(c, p, v),
    )
