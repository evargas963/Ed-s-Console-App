"""Order Flow Engine.

The book microstructure and the tape flow of one symbol, from Schwab streaming fields.

Input: a FlowInput, the newest book of its Schwab service, the top of book as Schwab last sent
it, the tape in receive order and whether the feed delivers the book now.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple, TypedDict

import numpy as np

from calc.l1_trade_observation import (
    KeptPrint,
    compute_cum_delta_proxy,
    compute_tape_pressure,
    cum_delta_window,
    iter_signed_cum_points,
    unsigned_share,
)
from numeric_contract import (
    count_text,
    fixed_text,
    percent_text,
    price_text,
    schwab_count,
)
from option_contract import NO_TOP, StreamedTop
from time_et import ct_label

OF_TAPE_WINDOW_30S_SEC: float = 30.0
OF_TAPE_WINDOW_2M_SEC: float = 120.0
OF_TAPE_WINDOW_5M_SEC: float = 300.0
# Book-depth ladder: top of book, shallow, deep.
OF_BOOK_DEPTH_TOP: int = 1
OF_BOOK_DEPTH_SHALLOW: int = 3
OF_BOOK_DEPTH_DEEP: int = 5


# ─────────────────────────────────────────────────────────────────────────────
# DATA EXTRACTION — safe access to nested structures
# ─────────────────────────────────────────────────────────────────────────────


Exchanges = tuple[tuple[str, float, float | None], ...]

#: a value inside a Schwab book item, as its JSON was read
type Json = dict[str, Json] | list[Json] | str | float | None


#: one level of a book: (price, TOTAL_VOLUME, the level's per-exchange rows), as Schwab sent them
Level = tuple[float, float, Exchanges | None]
#: one side of a book as the engine reads it: each level's (price, TOTAL_VOLUME), best first
Levels = list[tuple[float, float]]


@dataclass(frozen=True)
class Book:
    """One Schwab book message (NYSE_BOOK, NASDAQ_BOOK or OPTIONS_BOOK).

    Read once where it arrives (stream_spine.read_book). Holds its service, BOOK_TIME,
    and each side's levels in the order Schwab sent them.
    """

    service: str
    book_time_ms: float | None
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

    def levels(self, side: str) -> tuple[Level, ...]:
        """Return the levels of `side`, "BIDS" or "ASKS"."""
        return self.bids if side == "BIDS" else self.asks

    def pairs(self, side: str) -> list[tuple[float, float]]:
        """Return the (price, TOTAL_VOLUME) of each level of `side`, "BIDS" or "ASKS", as sent."""
        return [(p, v) for p, v, _ in self.levels(side)]


@dataclass(frozen=True)
class FlowInput:
    """What the engine reads of one symbol.

    The newest book of its Schwab service (None: none held), its top of book as Schwab last sent
    each field, its tape in receive order, whether the feed delivers the book now (None: no
    book), and the exchange's quote clock (QUOTE_TIME_MILLIS, in seconds; None: not sent).
    """

    book: Book | None
    top: StreamedTop = NO_TOP
    prints: list[KeptPrint] = field(default_factory=list[KeptPrint])
    book_live: bool | None = None
    exchange_quote_ts: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
# BOOK METRICS
# ─────────────────────────────────────────────────────────────────────────────


def _book_side_depth_total(levels: list[tuple[float, float]], depth: int) -> float | None:
    """Return Σ TOTAL_VOLUME over the best `depth` levels (best-first).

    None when the side has no levels. The microstructure depth ladder's one depth aggregation.
    """
    if not levels:
        return None
    return sum(v for _, v in levels[:depth])


def _book_imbalance_from_totals(bid_total: float | None, ask_total: float | None) -> float | None:
    """Return the book imbalance (bid - ask) / (bid + ask): THE single book-imbalance formula.

    None if a side total is absent or the combined depth is non-positive.
    """
    if bid_total is None or ask_total is None:
        return None
    total = bid_total + ask_total
    if total <= 0:
        return None
    return (bid_total - ask_total) / total


# ─────────────────────────────────────────────────────────────────────────────
# TOP OF BOOK
# ─────────────────────────────────────────────────────────────────────────────


def _compute_top_book_pressure(data: FlowInput) -> float | None:
    """Top-of-book pressure: (bid_size - ask_size) / (bid_size + ask_size), streamed sizes."""
    return _book_imbalance_from_totals(data.top.bid_size, data.top.ask_size)


def _resolve_bid_ask_prices(data: FlowInput) -> tuple[float | None, float | None]:
    """Level-one BID_PRICE / ASK_PRICE as Schwab sent them."""
    return data.top.bid, data.top.ask


def _resolve_quote_mark(data: FlowInput) -> float | None:
    """Level-one MARK as Schwab sent it, a ticker's or a contract's; a reported 0 is 0."""
    return data.top.mark


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL BOOK MICROSTRUCTURE  (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1)
# ─────────────────────────────────────────────────────────────────────────────
# ONE canonical book path. `_extract_canonical_book` walks + validates + SORTS the live
# book EXACTLY ONCE into a normalized state; every metric is derived from that single
# result. Nothing re-walks or re-sums the raw book. `compute_book_microstructure` is its one
# producer: the book panel (`push.book.book`) and a contract's Flow panel both call it.
# Every field is classified NATIVE (a Schwab wire field), DERIVED (a deterministic function of
# NATIVE fields), or PROXY (temporal inference). STATIC book state only — no aggressor/CVD/
# absorption/iceberg (see `deferred`). No opaque composite score.

#: Depth ladder for the canonical depth totals/imbalance — the existing 1/3/5 ladder.
OF_MICRO_DEPTH_LADDER: tuple[int, ...] = (
    OF_BOOK_DEPTH_TOP,
    OF_BOOK_DEPTH_SHALLOW,
    OF_BOOK_DEPTH_DEEP,
)


def _sorted_valid_levels(
    levels: Sequence[tuple[float | None, float | None]], *, descending: bool
) -> list[tuple[float, float]]:
    """Normalize a raw book side ONCE.

    Drop a level Schwab sent no price or size for (the raw readers drop -999, text, NaN and a
    negative size), then SORT so `[:N]` is the true Top-N regardless of the vendor's array
    order: bids DESCENDING, asks ASCENDING.
    """
    valid = [(p, v) for (p, v) in levels if p is not None and v is not None]
    valid.sort(key=lambda pv: pv[0], reverse=descending)
    return valid


class CanonicalBook(NamedTuple):
    """The live book of one symbol, read and normalized once (_extract_canonical_book).

    Whether a book is held and its Schwab service, the top of book as Schwab last sent it, each
    side's valid levels best first, and Schwab's BOOK_TIME and MARK.
    """

    has_book: bool
    venue: str | None
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    bid_levels: Levels
    ask_levels: Levels
    book_time_ms: float | None
    mark: float | None


def _extract_canonical_book(data: FlowInput) -> CanonicalBook:
    """Extract and normalize the live book: THE single extraction/normalization.

    Reads the book (``data.book``, the newest of its Schwab service; a one-sided one included:
    the side Schwab sent no levels for is empty) ONCE, validates and sorts both sides, and
    carries the live top of book (``data.top``). Every downstream metric reads this result;
    nothing else re-walks the raw book.
    """
    snapshot = data.book
    bid, ask = _resolve_bid_ask_prices(data)
    bid_size = schwab_count(data.top.bid_size)
    ask_size = schwab_count(data.top.ask_size)

    bid_levels = _sorted_valid_levels(snapshot.pairs("BIDS"), descending=True) if snapshot else []
    ask_levels = _sorted_valid_levels(snapshot.pairs("ASKS"), descending=False) if snapshot else []
    mark = _resolve_quote_mark(data)
    return CanonicalBook(
        has_book=snapshot is not None,
        venue=snapshot.service if snapshot else None,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        book_time_ms=snapshot.book_time_ms if snapshot else None,
        mark=mark,
    )


def _microprice(
    bid: float | None, ask: float | None, bid_size: float | None, ask_size: float | None
) -> float | None:
    """Return the size-weighted top-of-book fair price.

        microprice = (bid·ask_size + ask·bid_size) / (bid_size + ask_size)
    Each price is weighted by the OPPOSITE side's size, so heavier bid size pulls the fair
    price toward the ask (imminent buy pressure). DERIVED from Schwab's quotes as sent. None on
    a missing leg (Schwab sent none) or zero total size (nothing to weight).
    """
    if bid is None or ask is None or bid_size is None or ask_size is None:
        return None
    denom = bid_size + ask_size
    if denom <= 0:
        return None
    return (bid * ask_size + ask * bid_size) / denom


class PressureLevel(TypedDict):
    """One level of the depth-pressure curve: its price and size, each with its text.

    `cum` is the size shown from the best level to this one.
    """

    price: float
    price_text: str | None
    volume: float
    volume_text: str | None
    cum: float


def _book_pressure_curve(levels: Levels, max_levels: int) -> list[PressureLevel]:
    """Cumulative displayed depth per level (best-first): the depth-pressure curve.

    Each level's size with its text as the screen shows it (count_text).
    """
    out: list[PressureLevel] = []
    cum = 0.0
    for price, vol in levels[:max_levels]:
        cum += vol
        out.append(
            {
                "price": price,
                "price_text": price_text(price),
                "volume": vol,
                "volume_text": count_text(vol),
                "cum": cum,
            }
        )
    return out


#: each served book field's kind: NATIVE (Schwab's as sent) or DERIVED (computed here)
_BOOK_CLASSIFICATION = {
    "top_of_book.bid": "NATIVE",
    "top_of_book.ask": "NATIVE",
    "top_of_book.bid_size": "NATIVE",
    "top_of_book.ask_size": "NATIVE",
    "mark": "NATIVE",
    "microprice": "DERIVED",
    "crossed": "DERIVED",
    "spread_pts": "DERIVED",
    "depth.*.bid_total": "DERIVED",
    "depth.*.ask_total": "DERIVED",
    "depth.*.imbalance": "DERIVED",
    "depth_pressure": "DERIVED",
    "ages.book_age_sec": "DERIVED",
    "ages.quote_age_sec": "DERIVED",
    "ages.book_stale": "DERIVED",
    "provenance.book_time_ms": "NATIVE",
    "provenance.exchange_quote_ts": "NATIVE",
    "provenance.server_received_ts": "DERIVED",
}
#: the book measures not served, each with why
_BOOK_DEFERRED = (
    "aggressor_side (PROXY: needs trade-vs-quote classification history)",
    "cumulative volume delta (estimated: exists in the engine, from the trades)",
    "absorption / replenishment (PROXY: exists in the engine, 2-snapshot compare)",
    "iceberg / add-pull / institutional_flow (PROXY: no evidence base in this slice)",
)


class TopOfBook(TypedDict):
    """The top of book as Schwab last sent it, each price and size with its text."""

    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    bid_size_text: str | None
    ask_size_text: str | None
    bid_text: str | None
    ask_text: str | None


class DepthTotals(TypedDict):
    """One step of the depth ladder: each side's total over its best levels and their imbalance."""

    bid_total: float | None
    ask_total: float | None
    bid_total_text: str | None
    ask_total_text: str | None
    imbalance: float | None
    imbalance_text: str | None


class DepthPressure(TypedDict):
    """The depth-pressure curve of each side, and the ladder's scale.

    `max_volume` is the largest size of the levels it draws; None with none.
    """

    bid: list[PressureLevel]
    ask: list[PressureLevel]
    max_volume: float | None


class BookProvenance(TypedDict):
    """Where a book's numbers come from: Schwab's clocks, the levels held and the book's service."""

    book_time_ms: float | None
    n_bid_levels: int
    n_ask_levels: int
    book_source: str | None
    exchange_quote_ts: float | None
    server_received_ts: float


class BookAges(TypedDict):
    """The book's and the quote's age at the time served, and whether the book is not live."""

    book_age_sec: float | None
    quote_age_sec: float | None
    book_stale: bool | None


class BookMicrostructure(TypedDict):
    """The canonical L2 book microstructure of one symbol (compute_book_microstructure)."""

    status: str
    top_of_book: TopOfBook
    crossed: bool | None
    mark: float | None
    microprice: float | None
    spread_pts: float | None
    mark_text: str | None
    microprice_text: str | None
    spread_pts_text: str | None
    depth: dict[str, DepthTotals]
    depth_pressure: DepthPressure
    classification: dict[str, str]
    deferred: list[str]
    provenance: BookProvenance
    ages: BookAges


def _depth_ladder(bid_levels: Levels, ask_levels: Levels) -> dict[str, DepthTotals]:
    """Return the depth ladder, each step with its texts.

    The readout's flat views (`_views`, the one producer of a book's top-N totals and
    imbalance), carried.
    """
    ladder = _views(bid_levels, ask_levels)
    depth: dict[str, DepthTotals] = {}
    for n in OF_MICRO_DEPTH_LADDER:
        lv = ladder[str(n)]
        depth[str(n)] = {
            "bid_total": lv.bid_total,
            "ask_total": lv.ask_total,
            "bid_total_text": count_text(lv.bid_total),
            "ask_total_text": count_text(lv.ask_total),
            "imbalance": lv.imbalance,
            "imbalance_text": fixed_text(lv.imbalance, 3),
        }
    return depth


def book_age_sec(book_time_ms: float | None, now: float) -> float | None:
    """Seconds from Schwab's BOOK_TIME to `now`; None with no book time."""
    return None if book_time_ms is None else now - book_time_ms / 1000.0


def compute_book_microstructure(data: FlowInput, *, now_ts: float) -> BookMicrostructure:
    """Compute the canonical L2 book microstructure for one symbol at `now_ts` (epoch seconds).

    The ONE producer the book panel (`push.book.book`) and a contract's Flow panel
    (`app.options.order_flow.live_payload.options_live_payload`) both call.
    `data.book` is the newest book of its Schwab service (app.options.order_flow.state
    .newest_book) and `data.top` the top of book; `data.exchange_quote_ts` (optional) is
    the plane's exchange quote clock; `data.book_live` is the live rule's answer for the book's
    service (absent: not live). Pure: computed from the book given on every call (about 30 us on
    a real book). Only the ages and the provenance's `server_received_ts` depend on `now`.
    Fail-closed: no book snapshot -> status 'no_book' with null metrics (no fabricated values).
    """
    now = now_ts
    cb = _extract_canonical_book(data)
    bid, ask = cb.bid, cb.ask
    bid_size, ask_size = cb.bid_size, cb.ask_size
    bid_levels, ask_levels = cb.bid_levels, cb.ask_levels
    # unknown without both quotes
    crossed = None if bid is None or ask is None else bid > ask

    microprice = _microprice(bid, ask, bid_size, ask_size)
    spread_pts = None if bid is None or ask is None else ask - bid
    mark = cb.mark
    exch_ts = data.exchange_quote_ts
    age = book_age_sec(cb.book_time_ms, now)
    return {
        "status": "ok" if cb.has_book else "no_book",
        "top_of_book": {
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "bid_size_text": count_text(bid_size),
            "ask_size_text": count_text(ask_size),
            "bid_text": price_text(bid),
            "ask_text": price_text(ask),
        },
        "crossed": crossed,
        "mark": mark,
        "microprice": microprice,
        "spread_pts": spread_pts,
        "mark_text": price_text(mark),
        "microprice_text": price_text(microprice),
        "spread_pts_text": price_text(spread_pts),
        "depth": _depth_ladder(bid_levels, ask_levels),
        "depth_pressure": {
            "bid": _book_pressure_curve(bid_levels, OF_BOOK_DEPTH_DEEP),
            "ask": _book_pressure_curve(ask_levels, OF_BOOK_DEPTH_DEEP),
            # the ladder's scale: the largest size of the levels it draws; None with none
            "max_volume": max(
                (v for _p, v in bid_levels[:OF_BOOK_DEPTH_DEEP] + ask_levels[:OF_BOOK_DEPTH_DEEP]),
                default=None,
            ),
        },
        "classification": dict(_BOOK_CLASSIFICATION),
        "deferred": list(_BOOK_DEFERRED),
        "provenance": {
            "book_time_ms": cb.book_time_ms,
            "n_bid_levels": len(bid_levels),
            "n_ask_levels": len(ask_levels),
            "book_source": cb.venue if cb.has_book else "unavailable",
            "exchange_quote_ts": exch_ts,  # NATIVE (plane quote clock)
            "server_received_ts": now,  # DERIVED (server wall clock at serialization)
        },
        "ages": {
            "book_age_sec": age,
            "quote_age_sec": None if exch_ts is None else now - exch_ts,
            # the live rule (live_market_plane.feed_live_for on the book's service), which the
            # caller passes as data.book_live; None with no book
            "book_stale": None if age is None else data.book_live is not True,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORDER IMBALANCE READOUT — the Desk Liquidity card
# ─────────────────────────────────────────────────────────────────────────────

#: the two Schwab equity books, and their deduped union
BOOK_VENUES: tuple[str, ...] = ("NYSE_BOOK", "NASDAQ_BOOK")
COMPOSITE = "COMPOSITE"
#: the card's views: the shares summed over the best 1, 3 and 5 price levels per side, each
#: (bid - ask) / (bid + ask) (docs/SOURCES.md gould-bonart-2015, cao-hansch-wang-2009,
#: bookmap-imbalance); "5" is the headline the screen opens on
READOUT_VIEWS: tuple[str, ...] = ("1", "3", "5")
#: the headline percentage reads NEUTRAL under this, else buy-heavy or sell-heavy (the three words
#: docs/SOURCES.md cartea-2018's; Bookmap's Imbalance indicator shows the ratio in the buyer's or
#: seller's colour from 10%: bookmap-imbalance)
OF_TILT_PCT: float = 10.0
#: the lean sparklines: (name, window in seconds, one point every this many seconds)
OF_LEAN_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("2m", int(OF_TAPE_WINDOW_2M_SEC), 1),
    ("5m", int(OF_TAPE_WINDOW_5M_SEC), 5),
)
#: the one-second values kept: the longest window
OF_LEAN_KEPT_SEC: int = int(OF_TAPE_WINDOW_5M_SEC)
#: a tilt as the card's headline says it (`side_word`); the same words in lower case are how
#: running text says it (`tilt_text`), each served so the page changes no case
TILT_WORDS = {"BID_HEAVY": "BUY-HEAVY", "BALANCED": "NEUTRAL", "OFFER_HEAVY": "SELL-HEAVY"}
#: a book's state as the card's headline says it when that state is why it has no tilt; served in
#: the tilt's place, so the Desk's strip says what the card says
STATE_WORDS = {"one_sided": "ONE-SIDED", "no_book": "NO BOOK", "empty": "NO LEVELS"}


def _lean_words(tilt: str | None, status: str) -> tuple[str | None, str | None]:
    """Return a view's lean as the card's headline says it and as running text says it.

    The tilt's words when it has one; else the book's state when that is why it has none
    (STATE_WORDS); else none: no value, drawn "-".
    """
    if tilt:
        word = TILT_WORDS[tilt]
    elif status in STATE_WORDS:
        word = STATE_WORDS[status]
    else:
        return None, None
    return word, word.lower()


#: a tilt's side, for flips: BALANCED is none
_SIDE = {"BID_HEAVY": "BID", "OFFER_HEAVY": "OFFER"}
#: the detail panel's words
READOUT_DETAIL = {
    "tilt": "Order book imbalance: the bid shares less the ask shares over the two together, each"
    f" second, as it is. NEUTRAL under {fixed_text(OF_TILT_PCT, 0)}%; BUY-HEAVY or SELL-HEAVY"
    f" from {fixed_text(OF_TILT_PCT, 0)}% (the line Bookmap's Imbalance indicator changes colour"
    " at): direction"
    " only, not strength. A flip is a change of side, buy to sell or back.",
    "construction": "Aggregate: every exchange's and market maker's quote from the books Schwab"
    " sends for this symbol, one per contributor by side; where a contributor quotes in both"
    " books (Nasdaq's NSDQ, for SPY and IWM), the copy with the newer quote time Schwab sent;"
    " then the shares summed at each distinct price and the best five prices per side. With one"
    " book, the aggregate is that book. Never the two books' level totals summed.",
    "spans": "Top 5 covers different price ranges on the two venues — the percentages are over"
    " different prices, so compare directions, not magnitudes. The top of book is the only"
    " like-for-like comparison across venues.",
    "books": "NYSE_BOOK is each exchange's best quote grouped by price, not order depth."
    " NASDAQ_BOOK carries Nasdaq's own quote and market makers' quotes.",
}
_CROSSED_SENTENCE = "Book crossed — the best bid is above the best offer."
_TOUCH_FLAG = {"CROSSED": "BOOK CROSSED", "LOCKED": "BOOK LOCKED"}


def _composite_side(books: dict[str, Book], side: str) -> tuple[Levels, bool]:
    """Return one side of the composite of the books held.

    Every quote, one per contributor (its code,
    matched without regard to case), from the book whose copy has the newer quote time (on an equal
    time, or neither sent, the first in BOOK_VENUES order), the shares summed at each distinct
    price, best first. A level that carries no per-exchange rows counts its TOTAL_VOLUME whole; it,
    or a contributor in two books with a copy sent without its quote time, makes the dedup partial
    (the second value).
    """
    rows_held = [
        (code.upper(), venue, quoted)
        for venue, book in books.items()
        for _price, _total, rows in book.levels(side)
        if rows is not None
        for code, _size, quoted in rows
    ]
    newest: dict[str, tuple[float | None, str]] = {}
    for key, venue, quoted in rows_held:
        held = newest.get(key)
        # a time sent is newer than one not sent
        if held is None or (quoted is not None and (held[0] is None or quoted > held[0])):
            newest[key] = (quoted, venue)
    partial = any(
        quoted is None and len({v for k, v, _q in rows_held if k == key}) > 1
        for key, _venue, quoted in rows_held
    )
    sizes: dict[float, float] = {}
    for venue, book in books.items():
        for price, total, rows in book.levels(side):
            if rows is None:
                partial = True
                sizes[price] = sizes.get(price, 0.0) + total
                continue
            for code, size, _quoted in rows:
                if newest[code.upper()][1] == venue:
                    sizes[price] = sizes.get(price, 0.0) + size
    return sorted(sizes.items(), reverse=side == "BIDS"), partial


def _span(levels: Levels, depth: int) -> float | None:
    """Return the span from the touch price to the `depth`-th level's.

    The last level's when the side has fewer; None for an empty side.
    """
    if not levels:
        return None
    return abs(levels[min(depth, len(levels)) - 1][0] - levels[0][0])


def _pct(imbalance: float | None) -> float | None:
    return None if imbalance is None else imbalance * 100.0


#: a one-sided book's words, by the side Schwab sent levels for
_ONE_SIDED = {
    "BIDS": "Only the bid side has levels in this book: no percentage.",
    "ASKS": "Only the offer side has levels in this book: no percentage.",
}


class ReadoutView(NamedTuple):
    """One view of a book: its best levels' totals, their imbalance and how far they reach.

    Each None where the book has no number for it: a side with no levels has no total, and a
    book without both sides has no imbalance, difference or depth.
    """

    imbalance: float | None
    pct: float | None
    bid_total: float | None
    ask_total: float | None
    difference: float | None
    total_depth: float | None
    span_bid: float | None
    span_ask: float | None


#: the views of no book: no number in any
_NO_VIEWS: Mapping[str, ReadoutView] = dict.fromkeys(
    READOUT_VIEWS, ReadoutView(None, None, None, None, None, None, None, None)
)


class Readout(NamedTuple):
    """The imbalance readout of one Schwab book, or of the composite (book_readout).

    `status`: "ok", "one_sided" (one side has no levels), "empty" (neither has) or "no_book"
    (none held: no number in any view, and no touch, count of levels or one-sided words).
    `levels`: the count of its bid and of its ask levels. `books` and `dedup_partial` are the
    composite's alone: the books it is built from, and whether a level or a quote could not be
    told apart between them.
    """

    status: str
    book_time_ms: float | None
    views: Mapping[str, ReadoutView]
    touch_state: str | None = None
    one_sided_text: str | None = None
    levels: tuple[int, int] | None = None
    books: list[str] | None = None
    dedup_partial: bool | None = None


#: the readouts kept: (receive time, each venue's readout), oldest first
Points = Sequence[tuple[float, Mapping[str, Readout]]]


def _views(bids: Levels, asks: Levels) -> dict[str, ReadoutView]:
    """Return one book's views.

    The totals of its best 1, 3 and 5 levels, their imbalance and its percentage (the one
    producer of a book's depth ladder: the bars, difference and sentence here, and the
    microstructure's `depth`).
    """
    views: dict[str, ReadoutView] = {}
    for view in READOUT_VIEWS:
        depth = int(view)
        bt, at = _book_side_depth_total(bids, depth), _book_side_depth_total(asks, depth)
        imb = _book_imbalance_from_totals(bt, at)
        views[view] = ReadoutView(
            imbalance=imb,
            pct=_pct(imb),
            bid_total=bt,
            ask_total=at,
            difference=None if bt is None or at is None else abs(bt - at),
            total_depth=None if bt is None or at is None else bt + at,
            span_bid=_span(bids, depth),
            span_ask=_span(asks, depth),
        )
    return views


def _readout(bids: Levels, asks: Levels, book_time_ms: float | None) -> Readout:
    """Return one book's readout: its views, its touch and the count of its levels."""
    touch = None
    if bids and asks:
        touch = (
            "CROSSED" if bids[0][0] > asks[0][0] else "LOCKED" if bids[0][0] == asks[0][0] else None
        )
    status = "ok" if bids and asks else "one_sided" if bids or asks else "empty"
    return Readout(
        status=status,
        book_time_ms=book_time_ms,
        views=_views(bids, asks),
        touch_state=touch,
        one_sided_text=_ONE_SIDED["BIDS" if bids else "ASKS"] if status == "one_sided" else None,
        levels=(len(bids), len(asks)),
    )


def book_readout(books: Mapping[str, Book | None]) -> Mapping[str, Readout]:
    """Return the imbalance readout of each Schwab book and of their composite, by venue.

    Read from each venue's newest book (`state.newest_book`, every venue of BOOK_VENUES; None:
    no book). The composite is of the books held (`books` names them): with one, that book; with
    none, no_book, `books` naming the two it reads. Its time is its older book's.
    """
    out: dict[str, Readout] = {}
    held: dict[str, Book] = {}
    for v in BOOK_VENUES:
        book = books[v]
        if book is None:
            out[v] = Readout("no_book", None, _NO_VIEWS)
            continue
        held[v] = book
        bids = _sorted_valid_levels(book.pairs("BIDS"), descending=True)
        asks = _sorted_valid_levels(book.pairs("ASKS"), descending=False)
        out[v] = _readout(bids, asks, book.book_time_ms)
    if not held:
        out[COMPOSITE] = Readout("no_book", None, _NO_VIEWS, books=list(BOOK_VENUES))
        return out
    times = [t for b in held.values() if (t := b.book_time_ms) is not None]
    (bids, bid_partial), (asks, ask_partial) = (_composite_side(held, s) for s in ("BIDS", "ASKS"))
    # its time is its older book's; a book with no time leaves it none
    composite = _readout(bids, asks, min(times) if len(times) == len(held) else None)
    out[COMPOSITE] = composite._replace(books=list(held), dedup_partial=bid_partial or ask_partial)
    return out


def _standing(points: Points, venue: str, view: str, first: int, last: int) -> list[float | None]:
    """Return the headline percentage of `venue` and `view` standing in each second first..last.

    Each whole second's value is the newest readout received by that second's end (Schwab sends
    a book only when it changes, so the last one stands).
    """
    out: list[float | None]
    cur: float | None
    out, i, cur = [], 0, None
    for sec in range(first, last + 1):
        while i < len(points) and points[i][0] < sec + 1:
            cur = points[i][1][venue].views[view].pct
            i += 1
        out.append(cur)
    return out


def _tilt(pct: float | None) -> str | None:
    if pct is None:
        return None
    if abs(pct) < OF_TILT_PCT:
        return "BALANCED"
    return "BID_HEAVY" if pct > 0 else "OFFER_HEAVY"


def _tilts(values: list[float | None], first: int) -> list[tuple[str | None, int | None]]:
    """Return each second's tilt and the second the value entered it; (None, None) while unknown."""
    shown: list[tuple[str | None, int | None]]
    shown, since, prev = [], None, None
    for k, value in enumerate(values):
        tilt = _tilt(value)
        if tilt != prev:
            since = None if tilt is None else first + k
        prev = tilt
        shown.append((tilt, since))
    return shown


def _flips(shown: list[tuple[str | None, int | None]], first: int, last: int) -> int:
    """Count the flips arriving in the two minutes to second `last`.

    A flip is the tilt (`_tilts`, from
    second `first`) reaching the side opposite the one it last held, bid to offer or back.
    BALANCED is no side, so bid, BALANCED, offer is one flip, on arrival; the first lean is none;
    after an unknown value the count of sides starts over.
    """
    flips, held = 0, None
    for k, (tilt, _since) in enumerate(shown):
        if tilt is None:
            held = None
        elif tilt in _SIDE:
            if (
                held is not None
                and _SIDE[tilt] != held
                and first + k > last - OF_TAPE_WINDOW_2M_SEC
            ):
                flips += 1
            held = _SIDE[tilt]
    return flips


def _lean(values: list[float | None]) -> str | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return (
        "BID_HEAVY"
        if all(v > 0 for v in known)
        else "OFFER_HEAVY"
        if all(v < 0 for v in known)
        else "MIXED"
    )


def _sentence(bid: float | None, ask: float | None) -> str | None:
    """Return arithmetic about the displayed book: how many more shares one side shows.

    Displayed shares only, not who will trade: displayed orders are mostly cancelled and partly
    hidden or off the book.
    """
    if bid is None or ask is None:
        return None
    diff = abs(bid - ask)
    if diff == 0:
        return "Equal shares bid and offered."
    more, fewer = ("bid", "offered") if bid > ask else ("offered", "bid")
    return f"{count_text(diff)} more shares {more} than {fewer}."


def _opposite(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a * b < 0


class LeanSeries(TypedDict):
    """One lean sparkline of a view: its window and step in seconds, its side, and its values.

    `lean` is BID_HEAVY or OFFER_HEAVY while every value known is on that side, else MIXED; None
    with no value known.
    """

    seconds: int
    step: int
    lean: str | None
    values: list[float | None]


class CardView(TypedDict):
    """One venue's view on the Liquidity card, standing at its end second (_card_view)."""

    bid_total: float | None
    ask_total: float | None
    difference: float | None
    total_depth: float | None
    pct: float | None
    pct_text: str | None
    tilt: str | None
    side_word: str | None
    tilt_text: str | None
    held_sec: int | None
    held_open: bool
    held_text: str | None
    sentence: str | None
    flips_2m: int
    bid_text: str | None
    ask_text: str | None
    difference_text: str | None
    total_text: str | None
    span_bid_text: str | None
    span_ask_text: str | None
    lean: dict[str, LeanSeries]


class NoView(TypedDict):
    """A venue's view with no end second: no value, and its book's state in words (_lean_words)."""

    pct: None
    tilt: None
    side_word: str | None
    tilt_text: str | None


class VenueCard(TypedDict):
    """One venue on the Liquidity card (readout_card): its readout's state, and its views."""

    status: str
    book_time_ms: float | None
    touch_state: str | None
    one_sided_text: str | None
    books: list[str] | None
    dedup_partial: bool | None
    touch_pct: float | None
    touch_text: str | None
    touch_flag: str | None
    levels_text: str | None
    views: dict[str, CardView | NoView]


class ReadoutCard(TypedDict):
    """The Liquidity card's values (readout_card): each venue, and where the two books disagree."""

    venues: dict[str, VenueCard]
    disagree: dict[str, bool]
    detail: dict[str, str]


def _card_view(r: Readout, points: Points, v: str, view: str, last: int) -> CardView:
    """Return one venue's view on the Liquidity card, standing at its end second `last`."""
    first = last - OF_LEAN_KEPT_SEC
    sm = _standing(points, v, view, first, last)
    shown = _tilts(sm, first)
    tilt, since = shown[-1]
    known_from = next((first + k for k, s in enumerate(sm) if s is not None), None)
    snap = r.views[view]
    bid, ask = snap.bid_total, snap.ask_total
    held = None if since is None else last - since
    side_word, tilt_text = _lean_words(tilt, r.status)
    return {
        "bid_total": bid,
        "ask_total": ask,
        "difference": snap.difference,
        "total_depth": snap.total_depth,
        "pct": sm[-1],
        "pct_text": percent_text(sm[-1]),
        "tilt": tilt,
        "side_word": side_word,
        # the same words as running text says them (the Desk's strip, Right Now's unit)
        "tilt_text": tilt_text,
        "held_sec": held,
        "held_open": since is not None and since == known_from,
        "held_text": None if held is None else f"FOR {'≥' if since == known_from else ''}{held}s",
        "sentence": _CROSSED_SENTENCE if r.touch_state == "CROSSED" else _sentence(bid, ask),
        "flips_2m": _flips(shown, first, last),
        "bid_text": count_text(bid),
        "ask_text": count_text(ask),
        "difference_text": count_text(snap.difference),
        "total_text": count_text(snap.total_depth),
        # how far the book's levels reach in price
        "span_bid_text": price_text(snap.span_bid),
        "span_ask_text": price_text(snap.span_ask),
        "lean": {
            name: {
                "seconds": window,
                "step": step,
                "lean": _lean(sm[-(window + 1) :]),
                "values": sm[-(window + 1) :: step],
            }
            for name, window, step in OF_LEAN_WINDOWS
        },
    }


def readout_card(
    readout: Mapping[str, Readout], points: Points, ends: Mapping[str, float | None]
) -> ReadoutCard:
    """Return the Liquidity card's values, every venue and view.

    The headline (the percentage standing at
    the venue's end second: now while its book is live, else its last value's), its
    tilt, its side word and the tilt as running text says it (with no tilt, the book's state
    that is why: _lean_words), the seconds the tilt has held
    (held_open: at
    least that long, the tilt standing since the first value known), the flat totals, the
    sentence (withheld while the book is crossed), the spans, the touch and its flag, the flips
    in two minutes, and the 2m and 5m lean series. `readout`: the newest; `points`: the readouts
    kept, (receive time,
    readout) oldest first; `ends`: venue -> its end time, None with no value.
    """
    venues: dict[str, VenueCard] = {}
    for v, r in readout.items():
        end = ends[v]
        views: dict[str, CardView | NoView] = {}
        side_word, tilt_text = _lean_words(None, r.status)
        for view in READOUT_VIEWS:
            if end is None:
                views[view] = {
                    "pct": None,
                    "tilt": None,
                    "side_word": side_word,
                    "tilt_text": tilt_text,
                }
                continue
            views[view] = _card_view(r, points, v, view, int(end))
        touch = r.views["1"].pct
        venues[v] = {
            "status": r.status,
            "book_time_ms": r.book_time_ms,
            "touch_state": r.touch_state,
            "one_sided_text": r.one_sided_text,
            "books": r.books,
            "dedup_partial": r.dedup_partial,
            "touch_pct": touch,
            "touch_text": percent_text(touch),
            "touch_flag": None if r.touch_state is None else _TOUCH_FLAG[r.touch_state],
            "levels_text": f"Levels available: bids {r.levels[0]} · asks {r.levels[1]}"
            if r.levels is not None and min(r.levels) < OF_BOOK_DEPTH_DEEP
            else None,
            "views": views,
        }
    return {
        "venues": venues,
        "disagree": {
            view: _opposite(
                venues["NYSE_BOOK"]["views"][view]["pct"],
                venues["NASDAQ_BOOK"]["views"][view]["pct"],
            )
            for view in READOUT_VIEWS
        },
        "detail": READOUT_DETAIL,
    }


# ─────────────────────────────────────────────────────────────────────────────
# TAPE METRICS
# ─────────────────────────────────────────────────────────────────────────────


def _window_start_ms(now: float, window_sec: float) -> float:
    """Return the first millisecond of the window of `window_sec` that ends at `now`."""
    return now * 1000.0 - int(window_sec * 1000)


def _compute_cum_delta_slope(
    prints: list[KeptPrint], now: float, window_sec: float = 60.0
) -> float | None:
    """Slope of the estimated cumulative delta in receive order (l1_trade_observation's walk)."""
    points = iter_signed_cum_points(prints, _window_start_ms(now, window_sec))
    if len(points) < 2:
        return None
    xs = np.array([p[0] for p in points])
    ys = np.array([p[1] for p in points])
    return float(np.polyfit(xs, ys, 1)[0])


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────────────────────────────────────


class EngineFlow(TypedDict):
    """What OrderFlowEngine.compute returns for one symbol.

    Each flow number with its text as the screen shows it, and the window the cumulative delta
    sums.
    """

    top_book_pressure: float | None
    tape_pressure_30s: float | None
    tape_pressure_2m: float | None
    tape_pressure_5m: float | None
    tape_unsigned_30s: float | None
    tape_unsigned_2m: float | None
    tape_unsigned_5m: float | None
    cum_delta_unsigned: float | None
    cum_delta_proxy: float | None
    cum_delta_slope: float | None
    top_book_pressure_text: str | None
    tape_pressure_30s_text: str | None
    tape_pressure_2m_text: str | None
    tape_pressure_5m_text: str | None
    tape_unsigned_30s_text: str | None
    tape_unsigned_2m_text: str | None
    tape_unsigned_5m_text: str | None
    cum_delta_unsigned_text: str | None
    cum_delta_proxy_text: str | None
    cum_delta_slope_text: str | None
    cum_delta_window: str | None


class OrderFlowEngine:
    """Order Flow Engine: computes metrics from Schwab data using only identified field paths."""

    def compute(self, data: FlowInput, *, now: float) -> EngineFlow:
        """Compute the tape flow of one symbol at `now`.

        `now` is in epoch seconds; missing data yields None. The symbol's book is
        compute_book_microstructure's, which a panel that shows both calls beside this.
        """
        prints = data.prints  # the tape, in receive order
        cum_first, cum_last = cum_delta_window(prints)
        ms = now * 1000.0
        # each flow number: the pressures, each value's unsigned share of the size it covers,
        # the cumulative delta
        # top-of-book SIZE pressure (streamed BID_SIZE / ASK_SIZE), not a depth imbalance
        top = _compute_top_book_pressure(data)
        pressure_30s = compute_tape_pressure(prints, OF_TAPE_WINDOW_30S_SEC, ms)
        pressure_2m = compute_tape_pressure(prints, OF_TAPE_WINDOW_2M_SEC, ms)
        pressure_5m = compute_tape_pressure(prints, OF_TAPE_WINDOW_5M_SEC, ms)
        unsigned_30s = unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_30S_SEC))
        unsigned_2m = unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_2M_SEC))
        unsigned_5m = unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_5M_SEC))
        unsigned = unsigned_share(prints)
        proxy = compute_cum_delta_proxy(prints)
        slope = _compute_cum_delta_slope(prints, now)

        return {
            "top_book_pressure": top,
            "tape_pressure_30s": pressure_30s,
            "tape_pressure_2m": pressure_2m,
            "tape_pressure_5m": pressure_5m,
            "tape_unsigned_30s": unsigned_30s,
            "tape_unsigned_2m": unsigned_2m,
            "tape_unsigned_5m": unsigned_5m,
            "cum_delta_unsigned": unsigned,
            "cum_delta_proxy": proxy,
            "cum_delta_slope": slope,
            # beside each number its text as the screen shows it, to the decimals of its kind:
            # a pressure and the slope 3, an unsigned share 2, the cumulative delta 1
            "top_book_pressure_text": fixed_text(top, 3),
            "tape_pressure_30s_text": fixed_text(pressure_30s, 3),
            "tape_pressure_2m_text": fixed_text(pressure_2m, 3),
            "tape_pressure_5m_text": fixed_text(pressure_5m, 3),
            "tape_unsigned_30s_text": fixed_text(unsigned_30s, 2),
            "tape_unsigned_2m_text": fixed_text(unsigned_2m, 2),
            "tape_unsigned_5m_text": fixed_text(unsigned_5m, 2),
            "cum_delta_unsigned_text": fixed_text(unsigned, 2),
            "cum_delta_proxy_text": fixed_text(proxy, 1),
            "cum_delta_slope_text": fixed_text(slope, 3),
            # the window the cumulative delta sums: the tape's first and last print (Schwab trade
            # time), served beside the number
            "cum_delta_window": (
                "prints " + ct_label(cum_first) + " to " + ct_label(cum_last)
                if cum_first is not None and cum_last is not None
                else None
            ),
        }
