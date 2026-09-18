"""Canonical typed contract for a depth-of-book snapshot observation (RC-REHAB-1, Phase 1).

Grounded in a direct investigation of `app/options/order_flow/{engine.py,state.py,history.py}`
(not assumed): the two headline defects this rehab's plan originally named for this domain --
a BIDS/ASKS level-parser duplicated between `state.py` and `engine.py`, and a second
book-imbalance formula silently standing in when the canonical one said "unavailable" -- were
ALREADY fixed in a prior pass (`engine.py`'s own comments document this: "ONE CANONICAL BOOK
PATH", "Removed the former REST fallback ... which conflated the two under one name").

What the investigation found instead, still live:

1. `history.py`'s `book_heatmap_for_ticker` walks raw `BIDS`/`ASKS`/`TOTAL_VOLUME` on its own,
   independently of `engine.py`'s canonical `_extract_canonical_book` -> `_iter_bids_levels` /
   `_iter_asks_levels` / `_sorted_valid_levels` chain -- a genuine second parser of the same
   wire shape, just not the two files the original finding named.
2. `_extract_canonical_book` (`engine.py:527-568`) returns a bare `has_book: bool` -- present
   or absent, nothing else. A real staleness signal (`ages.book_stale`) exists, but only
   downstream, computed separately, in a different dict a consumer could forget to check.
   There is no single place that answers "genuinely live snapshot" vs. "we have one but it is
   too old to trust" vs. "we have never seen a book for this ticker" -- exactly the disclosure
   gap `market_observation.FreshnessState` exists to close for the quote plane.

This module gives the book-levels domain the same typed shape: `BookSnapshotObservation`
reuses `FreshnessState` from `market_observation.py` (no second tri-state type) and folds the
already-correct, already-single-sourced `_book_side_depth_total` / `_book_imbalance_from_totals`
formulas into methods on the observation itself, so a future second parser (like `history.py`'s
today) has a typed authority to call instead of a bare dict with no attached behavior.

Not yet wired into `engine.py`/`state.py`/`history.py`. That sweep -- consolidating
`history.py`'s independent parser onto this contract, and fixing the dead `get_top_of_book`
import in `server.py:3609` that a bare `except ImportError` currently swallows -- is Phase 2's
explicit job (close the order-flow vertical against Phase 1's typed contracts), not this
module's. A second adversarial review (before any wiring) confirmed the math here matches
`_book_side_depth_total`/`_book_imbalance_from_totals` exactly, but also found this type is
NOT a drop-in for `history.py`'s `book_heatmap_for_ticker` as-is -- worth recording now so
Phase 2 doesn't have to re-derive it:
  - that function buckets MANY historical rows (one snapshot each), not one point-in-time
    snapshot -- it would need one BookSnapshotObservation per DB row, not a single instance;
  - it rounds price to 2 decimals before using it as a dict key (`history.py:312`) specifically
    to avoid float-jitter duplicate buckets; `BookLevel.price` is deliberately the raw,
    unrounded value, so a heatmap consumer must still round at its own call site, not assume
    `BookLevel.price` is bucket-ready;
  - it silently drops a nested-list level entry (`history.py:306-308`) that `_iter_bids_levels`/
    `_iter_asks_levels` already handle (`engine.py:164-170`, `189-194`) -- a real, separate
    pre-existing bug in `history.py`'s own parser, not something this type introduces, but
    something Phase 2's consolidation will fix as a side effect;
  - `BookLevel`'s positivity/non-negativity invariants are stricter than `history.py`'s current
    tolerance (only checks for None) -- a malformed row `history.py` silently buckets today
    would raise if constructed as a `BookLevel` unchanged; Phase 2's wiring needs to decide
    whether that's the correct tightening or needs a filter-before-construct step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from market_observation import FreshnessState

Side = Literal["bid", "ask"]


@dataclass(frozen=True)
class BookLevel:
    """One price/volume level of a depth-of-book snapshot. No per-level provenance: production
    has none -- every level in a snapshot shares the snapshot's own state/source/book_time_ms
    (see BookSnapshotObservation). `price` and `volume` are always non-negative when this level
    exists at all; a level that failed to resolve is simply not appended by the producer
    (matching `_iter_bids_levels`/`_iter_asks_levels`'s own `p is not None and v is not None`
    filter), not represented as a BookLevel with a sentinel value.
    """

    price: float
    volume: float

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"BookLevel: price={self.price!r} is not positive")
        if self.volume < 0:
            raise ValueError(f"BookLevel: volume={self.volume!r} is negative")


@dataclass(frozen=True)
class BookSnapshotObservation:
    """A full bid+ask depth-of-book snapshot with ONE shared freshness/provenance.

    Production only ever resolves a snapshot from a single content item carrying BOTH BIDS and
    ASKS together (`_latest_book_snapshot`, `engine.py:207-212`) -- the two sides never have
    independently distinct staleness. Modeling them as two separately-stated observations would
    imply a degree of freedom production doesn't have; this type deliberately does not.

    `levels` on each side are expected pre-sorted best-first (bids descending, asks ascending)
    by the producer, matching `_sorted_valid_levels`'s own contract (`engine.py:517-524`) --
    this type does not re-sort, and `depth_total`/`imbalance` below trust that ordering exactly
    as the real `_book_side_depth_total` does today.

    `state`:
      - LIVE: a snapshot was resolved and is within the freshness boundary.
      - STALE: a snapshot was resolved but has aged past the freshness boundary -- carried
        forward and disclosed as such, never silently presented as current.
      - UNAVAILABLE: no snapshot has ever been resolved for this ticker (both level lists
        empty, `book_time_ms` None) -- distinct from a STALE snapshot that merely aged out.
        Today's `_extract_canonical_book` collapses both of the latter two into one bare
        `has_book=False`; this type is what makes that distinction representable at all.
    """

    bid_levels: tuple[BookLevel, ...]
    ask_levels: tuple[BookLevel, ...]
    state: FreshnessState
    source: str
    book_time_ms: Optional[float]
    received_ts: float

    def __post_init__(self) -> None:
        if self.state is FreshnessState.UNAVAILABLE and (self.bid_levels or self.ask_levels):
            raise ValueError(
                "BookSnapshotObservation: state=UNAVAILABLE but levels are present -- an "
                "unavailable book must carry no levels, never a stale/empty snapshot wearing "
                "the unavailable label"
            )
        if self.state is FreshnessState.UNAVAILABLE and self.book_time_ms is not None:
            raise ValueError(
                "BookSnapshotObservation: state=UNAVAILABLE but book_time_ms is set -- an "
                "unavailable book has no snapshot to carry a time from"
            )

    @classmethod
    def unavailable(cls, *, source: str, received_ts: float) -> "BookSnapshotObservation":
        """No snapshot has ever been resolved for this ticker -- distinct from STALE (see
        class docstring)."""
        return cls(
            bid_levels=(), ask_levels=(), state=FreshnessState.UNAVAILABLE,
            source=source, book_time_ms=None, received_ts=received_ts,
        )

    def depth_total(self, side: Side, depth: int) -> Optional[float]:
        """Sum of volume over the best `depth` levels of one side. THE single depth-aggregation
        for this type -- matches `_book_side_depth_total` (`engine.py:215-222`) exactly: None
        when the side has no levels (including when the whole snapshot is UNAVAILABLE).

        `side` must be exactly "bid" or "ask" -- rejected explicitly rather than silently
        falling through to one side on a typo. The real `_book_side_depth_total` never had this
        hazard: it takes a level list directly, never a side-name string; this method's string
        parameter is new surface area this type adds, so it must fail closed on a bad value
        instead of quietly reading the wrong side's depth.
        """
        if side == "bid":
            levels = self.bid_levels
        elif side == "ask":
            levels = self.ask_levels
        else:
            raise ValueError(f"BookSnapshotObservation.depth_total: side must be 'bid' or 'ask', got {side!r}")
        if not levels:
            return None
        return sum(level.volume for level in levels[:depth])

    def imbalance(self, depth: int) -> Optional[float]:
        """THE single book-imbalance formula, as a method of the observation itself rather than
        a free function a second parser could independently reimplement (the class this rehab
        keeps finding and fixing): (bid_total - ask_total) / (bid_total + ask_total) over the
        best `depth` levels of each side. Matches `_book_imbalance_from_totals`
        (`engine.py:225-234`) exactly. None if either side's depth total is unavailable or the
        combined depth is non-positive."""
        bid_total = self.depth_total("bid", depth)
        ask_total = self.depth_total("ask", depth)
        if bid_total is None or ask_total is None:
            return None
        total = bid_total + ask_total
        if total <= 0:
            return None
        return (bid_total - ask_total) / total
