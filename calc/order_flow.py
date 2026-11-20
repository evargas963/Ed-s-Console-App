"""Order Flow Engine.

The book microstructure and the tape flow of one symbol, from Schwab streaming fields.

Input: a FlowInput, the newest book of its Schwab service, the top of book as Schwab last sent
it, the tape in receive order and whether the feed delivers the book now.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

import numpy as np

from calc.l1_trade_observation import (
    compute_cum_delta_proxy,
    compute_tape_pressure,
    cum_delta_window,
    iter_signed_cum_points,
    unsigned_share,
)
from numeric_contract import (
    count_text,
    fixed_text,
    float_finite_or_none,
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


class WallCandidate(TypedDict):
    """A level whose displayed size is an outlier on its side (_book_wall_candidates)."""

    side: str
    price: float
    #: its price as the screen shows it (price_text)
    price_text: str | None
    volume: float
    #: its size as the screen shows it (count_text)
    volume_text: str | None
    #: its size over the median of its side's levels
    median_mult: float
    #: that ratio as the screen shows it (fixed_text, one decimal)
    median_mult_text: str | None


@dataclass(frozen=True)
class Book:
    """One Schwab book message (NYSE_BOOK, NASDAQ_BOOK or OPTIONS_BOOK).

    Read once by State (app.options.order_flow.state.read_book). Holds its service, BOOK_TIME,
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
    prints: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
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
# result. Nothing re-walks or re-sums the raw book. `compute_book_microstructure` memoizes the
# structural state per (ticker, BOOK_TIME), so the book panel (`push.book.book`) and the engine
# SERIALIZE the same computed state rather than recomputing it independently.
# Every field is classified NATIVE (a Schwab wire field), DERIVED (a deterministic function of
# NATIVE fields), or PROXY (temporal inference). STATIC book state only — no aggressor/CVD/
# absorption/iceberg (see `deferred`). No opaque composite score.

#: HEURISTIC only: a displayed level is a WALL CANDIDATE when its size is at least this multiple
#: of the MEDIAN level size across the ladder. A relative size-outlier convention (tunable, and
#: blind to hidden/reserve size) — NOT an objectively-known liquidity wall. Surfaced with each
#: candidate's `median_mult` so the API never asserts a proven wall. magic-threshold-ok:
#: relative (× median).
OF_BOOK_WALL_MEDIAN_MULT: float = 3.0

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


def _extract_canonical_book(data: FlowInput) -> dict[str, Any]:
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
    return {
        "has_book": snapshot is not None,
        "venue": snapshot.service if snapshot else None,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "book_time_ms": snapshot.book_time_ms if snapshot else None,
        "mark": mark,
    }


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


def _book_pressure_curve(
    levels: list[tuple[float, float]], max_levels: int
) -> list[dict[str, float | str | None]]:
    """Cumulative displayed depth per level (best-first): the depth-pressure curve.

    Each level's size with its text as the screen shows it (count_text).
    """
    out: list[dict[str, float | str | None]] = []
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


def _book_wall_candidates(
    levels: list[tuple[float, float]], side: str, depth: int
) -> list[WallCandidate]:
    """Return HEURISTIC displayed-size anomalies as wall candidates.

    They are candidates, NOT objectively-known liquidity walls. A level is a candidate when its
    size ≥ OF_BOOK_WALL_MEDIAN_MULT × the MEDIAN level size across the best `depth` levels: a
    relative size outlier in the DISPLAYED order book only (it cannot see hidden/reserve size,
    and the multiple is a tunable convention, not a proven boundary). Each entry carries
    `median_mult` (its size ÷ the median) so a consumer sees HOW anomalous rather than a binary
    truth. Empty when there is no positive median or nothing clears the multiple.
    """
    lv = levels[:depth]
    vols = sorted(v for _, v in lv)
    if not vols:
        return []
    n = len(vols)
    median = vols[n // 2] if n % 2 else (vols[n // 2 - 1] + vols[n // 2]) / 2.0
    if median <= 0:
        return []
    out: list[WallCandidate] = []
    for price, vol in lv:
        if vol >= OF_BOOK_WALL_MEDIAN_MULT * median:
            out.append(
                {
                    "side": side,
                    "price": price,
                    "price_text": price_text(price),
                    "volume": vol,
                    "volume_text": count_text(vol),
                    "median_mult": vol / median,
                    "median_mult_text": fixed_text(vol / median, 1),
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
    "wall_candidates": "DERIVED-HEURISTIC (size-outlier convention)",
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
    "cvd / cum_delta (PROXY: exists as cum_delta_proxy in the engine, tape-based)",
    "absorption / replenishment (PROXY: exists in the engine, 2-snapshot compare)",
    "iceberg / add-pull / institutional_flow (PROXY: no evidence base in this slice)",
)


def _microstructure_structural(cb: dict[str, Any]) -> dict[str, Any]:
    """Return everything derivable from a single canonical book snapshot, no wall-clock `now`.

    Age fields and the per-serialization timestamps are stamped by `compute_book_microstructure`,
    so this structural state is safe to carry/memoize per (ticker, BOOK_TIME).
    """
    bid, ask = cb["bid"], cb["ask"]
    bid_size, ask_size = cb["bid_size"], cb["ask_size"]
    bid_levels, ask_levels = cb["bid_levels"], cb["ask_levels"]
    # unknown without both quotes
    crossed = None if bid is None or ask is None else bid > ask

    microprice = _microprice(bid, ask, bid_size, ask_size)
    spread_pts = None if bid is None or ask is None else ask - bid
    mark = cb["mark"]

    # Depth ladder: the readout's flat views (`_readout`, the one producer of a book's top-N
    # totals and imbalance), carried.
    ladder = _readout(bid_levels, ask_levels, cb["book_time_ms"])["views"]
    depth: dict[str, dict[str, float | str | None]] = {}
    for n in OF_MICRO_DEPTH_LADDER:
        lv = ladder[str(n)]
        depth[str(n)] = {
            "bid_total": lv["bid_total"],
            "ask_total": lv["ask_total"],
            "bid_total_text": count_text(lv["bid_total"]),
            "ask_total_text": count_text(lv["ask_total"]),
            "imbalance": lv["imbalance"],
            "imbalance_text": fixed_text(lv["imbalance"], 3),
        }

    return {
        "status": "ok" if cb["has_book"] else "no_book",
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
        "depth": depth,
        "depth_pressure": {
            "bid": _book_pressure_curve(bid_levels, OF_BOOK_DEPTH_DEEP),
            "ask": _book_pressure_curve(ask_levels, OF_BOOK_DEPTH_DEEP),
            # the ladder's scale: the largest size of the levels it draws; None with none
            "max_volume": max(
                (v for _p, v in bid_levels[:OF_BOOK_DEPTH_DEEP] + ask_levels[:OF_BOOK_DEPTH_DEEP]),
                default=None,
            ),
        },
        "wall_candidates": (
            _book_wall_candidates(bid_levels, "bid", OF_BOOK_DEPTH_DEEP)
            + _book_wall_candidates(ask_levels, "ask", OF_BOOK_DEPTH_DEEP)
        ),
        "provenance_structural": {
            "book_time_ms": cb["book_time_ms"],
            "n_bid_levels": len(bid_levels),
            "n_ask_levels": len(ask_levels),
            "book_source": cb["venue"] if cb["has_book"] else "unavailable",
        },
        "classification": dict(_BOOK_CLASSIFICATION),
        "deferred": list(_BOOK_DEFERRED),
    }


def book_age_sec(book_time_ms: float | None, now: float) -> float | None:
    """Seconds from Schwab's BOOK_TIME to `now`; None with no book time."""
    return None if book_time_ms is None else now - book_time_ms / 1000.0


def compute_book_microstructure(data: FlowInput, *, now_ts: float) -> dict[str, Any]:
    """Compute the canonical L2 book microstructure for one symbol at `now_ts` (epoch seconds).

    The ONE producer the engine and the book panel (`push.book.book`) both read.
    `data.book` is the newest book of its Schwab service (app.options.order_flow.state
    .newest_book) and `data.top` the top of book; `data.exchange_quote_ts` (optional) is
    the plane's exchange quote clock; `data.book_live` is the live rule's answer for the book's
    service (absent: not live). Pure: computed from the book given on every call (about 90 us on
    a real book). Only the age fields depend on `now`. Fail-closed: no book snapshot -> status
    'no_book' with null metrics (no fabricated values).
    """
    now = now_ts
    cb = _extract_canonical_book(data)
    book_time_ms = cb["book_time_ms"]
    structural = _microstructure_structural(cb)

    # Ages + per-serialization stamps are the only wall-clock-dependent fields.
    exch_ts = float_finite_or_none(data.exchange_quote_ts)
    payload = dict(structural)
    prov = dict(structural["provenance_structural"])
    prov["exchange_quote_ts"] = exch_ts  # NATIVE (plane quote clock)
    prov["server_received_ts"] = now  # DERIVED (server wall clock at serialization)
    payload.pop("provenance_structural", None)
    payload["provenance"] = prov
    age = book_age_sec(book_time_ms, now)
    payload["ages"] = {
        "book_age_sec": age,
        "quote_age_sec": None if exch_ts is None else now - exch_ts,
        # the live rule (live_market_plane.feed_live_for on the book's service), which the caller
        # passes as data.book_live; None with no book
        "book_stale": None if age is None else data.book_live is not True,
    }
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# ORDER IMBALANCE READOUT — the Desk Liquidity card
# ─────────────────────────────────────────────────────────────────────────────

#: the two Schwab equity books, and their deduped union
BOOK_VENUES: tuple[str, ...] = ("NYSE_BOOK", "NASDAQ_BOOK")
COMPOSITE = "COMPOSITE"
#: the card's views: the weighted top-5 headline, then the flat depths
READOUT_VIEWS: tuple[str, ...] = ("weighted", "1", "3", "5")
#: level k (1 = the touch) weighs exp(-OF_LEVEL_DECAY * (k - 1)), the top five normalized to sum
#: 1 (0.43, 0.26, 0.16, 0.10, 0.06): starting weights, adjustable
OF_LEVEL_DECAY: float = 0.5
_RAW_WEIGHTS = tuple(math.exp(-OF_LEVEL_DECAY * k) for k in range(OF_BOOK_DEPTH_DEEP))
OF_LEVEL_WEIGHTS: tuple[float, ...] = tuple(w / sum(_RAW_WEIGHTS) for w in _RAW_WEIGHTS)
#: the headline percentage reads BALANCED under this, else the side it leans to (Bookmap's
#: Imbalance indicator shows the ratio in the buyer's or seller's colour from 10%;
#: docs/SOURCES.md bookmap-imbalance)
OF_TILT_PCT: float = 10.0
#: the lean sparklines: (name, window in seconds, one point every this many seconds)
OF_LEAN_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("2m", int(OF_TAPE_WINDOW_2M_SEC), 1),
    ("5m", int(OF_TAPE_WINDOW_5M_SEC), 5),
)
#: the one-second values kept: the longest window
OF_LEAN_KEPT_SEC: int = int(OF_TAPE_WINDOW_5M_SEC)
TILT_WORDS = {"BID_HEAVY": "BID HEAVY", "BALANCED": "BALANCED", "OFFER_HEAVY": "OFFER HEAVY"}
#: a tilt's side, for flips: BALANCED is none
_SIDE = {"BID_HEAVY": "BID", "OFFER_HEAVY": "OFFER"}
#: the detail panel's words
READOUT_DETAIL = {
    "weights": "Headline weights by price level from the touch: "
    + ", ".join(f"{w:.2f}" for w in OF_LEVEL_WEIGHTS)
    + f" (exp(-{OF_LEVEL_DECAY}·(k-1)), normalized; renormalized over the levels a thin side has)."
    " Starting weights from a vendor study (VisualHFT, touch-weighted), adjustable.",
    "tilt": f"The headline is the book's percentage each second, as it is. BALANCED under"
    f" {OF_TILT_PCT:.0f}%; BID or OFFER HEAVY from {OF_TILT_PCT:.0f}%"
    " (Bookmap's colour-switch line): direction only, not strength. A flip is a change of"
    " side, bid to offer or back.",
    "construction": "Composite: every exchange's and market maker's quote from the books Schwab"
    " sends for this symbol, one per contributor by side; where a contributor quotes in both"
    " books (Nasdaq's NSDQ, for SPY and IWM), the copy with the newer quote time Schwab sent;"
    " then the shares summed at each distinct price and the best five prices per side. With one"
    " book, the composite is that book. Never the two books' level totals summed.",
    "spans": "Top 5 covers different price ranges on the two venues — the percentages are over"
    " different prices, so compare directions, not magnitudes. The touch is the only"
    " like-for-like comparison across venues.",
    "books": "NYSE_BOOK is each exchange's best quote grouped by price, not order depth."
    " NASDAQ_BOOK carries Nasdaq's own quote and market makers' quotes.",
}
_DIVERGENCE = "Touch and deeper book disagree"
_CROSSED_SENTENCE = "Book crossed — the best bid is above the best offer."
_TOUCH_FLAG: dict[str | None, str] = {"CROSSED": "BOOK CROSSED", "LOCKED": "BOOK LOCKED"}

Levels = list[tuple[float, float]]


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


def _weighted_total(levels: Levels) -> float | None:
    """Return Σ weight × shares over the best five levels.

    OF_LEVEL_WEIGHTS renormalized to sum 1 over the levels the side has; None for an empty side.
    """
    if not levels:
        return None
    weights = OF_LEVEL_WEIGHTS[: len(levels)]
    return sum(w * v for w, (_p, v) in zip(weights, levels, strict=False)) / sum(weights)


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


def _readout(bids: Levels, asks: Levels, book_time_ms: float | None) -> dict[str, Any]:
    """Return one book's views.

    The flat totals of its best 1, 3 and 5 levels and their imbalance (the
    one producer of a book's depth ladder: the bars, difference and sentence here, and the
    microstructure's `depth`), and the headline percentage (the weighted view's flat totals are
    the top five's).
    """
    views: dict[str, dict[str, float | None]] = {}
    for view in READOUT_VIEWS:
        depth = OF_BOOK_DEPTH_DEEP if view == "weighted" else int(view)
        bt, at = _book_side_depth_total(bids, depth), _book_side_depth_total(asks, depth)
        imb = _book_imbalance_from_totals(bt, at)
        views[view] = {
            "imbalance": imb,
            "pct": _pct(_book_imbalance_from_totals(_weighted_total(bids), _weighted_total(asks)))
            if view == "weighted"
            else _pct(imb),
            "bid_total": bt,
            "ask_total": at,
            "difference": None if bt is None or at is None else abs(bt - at),
            "total_depth": None if bt is None or at is None else bt + at,
            "span_bid": _span(bids, depth),
            "span_ask": _span(asks, depth),
        }
    touch = None
    if bids and asks:
        touch = (
            "CROSSED" if bids[0][0] > asks[0][0] else "LOCKED" if bids[0][0] == asks[0][0] else None
        )
    status = "ok" if bids and asks else "one_sided" if bids or asks else "empty"
    return {
        "status": status,
        "book_time_ms": book_time_ms,
        "touch_state": touch,
        "one_sided_text": _ONE_SIDED["BIDS" if bids else "ASKS"] if status == "one_sided" else None,
        "levels": {"bid": len(bids), "ask": len(asks)},
        "views": views,
    }


def book_readout(books: dict[str, Book | None]) -> dict[str, dict[str, Any]]:
    """Return the imbalance readout of each Schwab book and of their composite.

    Read from each venue's newest book (`state.newest_book`, every venue of BOOK_VENUES; None:
    no book). The composite is of the books held (`books` names them): with one, that book; with
    none, no_book, `books` naming the two it reads. Its time is its older book's.
    """
    out: dict[str, dict[str, Any]] = {}
    held: dict[str, Book] = {}
    for v in BOOK_VENUES:
        book = books[v]
        if book is None:
            out[v] = {"status": "no_book", "book_time_ms": None}
            continue
        held[v] = book
        bids = _sorted_valid_levels(book.pairs("BIDS"), descending=True)
        asks = _sorted_valid_levels(book.pairs("ASKS"), descending=False)
        out[v] = _readout(bids, asks, book.book_time_ms)
    if not held:
        out[COMPOSITE] = {"status": "no_book", "book_time_ms": None, "books": list(BOOK_VENUES)}
        return out
    times = [t for b in held.values() if (t := b.book_time_ms) is not None]
    (bids, bid_partial), (asks, ask_partial) = (_composite_side(held, s) for s in ("BIDS", "ASKS"))
    # its time is its older book's; a book with no time leaves it none
    out[COMPOSITE] = _readout(bids, asks, min(times) if len(times) == len(held) else None)
    out[COMPOSITE]["books"] = list(held)
    out[COMPOSITE]["dedup_partial"] = bid_partial or ask_partial
    return out


def _headline(readout: dict[str, dict[str, Any]], venue: str, view: str) -> float | None:
    r = readout[venue]
    return r["views"][view]["pct"] if "views" in r else None


def _standing(
    points: list[tuple[float, dict[str, Any]]], venue: str, view: str, first: int, last: int
) -> list[float | None]:
    """Return the headline percentage of `venue` and `view` standing in each second first..last.

    Each whole second's value is the newest readout received by that second's end (Schwab sends
    a book only when it changes, so the last one stands).
    """
    out: list[float | None]
    cur: float | None
    out, i, cur = [], 0, None
    for sec in range(first, last + 1):
        while i < len(points) and points[i][0] < sec + 1:
            cur = _headline(points[i][1], venue, view)
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


def _card_view(
    r: dict[str, Any],
    snap: dict[str, Any],
    points: list[tuple[float, dict[str, Any]]],
    v: str,
    view: str,
    last: int,
) -> dict[str, Any]:
    """Return one venue's view on the Liquidity card, standing at its end second `last`."""
    first = last - OF_LEAN_KEPT_SEC
    sm = _standing(points, v, view, first, last)
    shown = _tilts(sm, first)
    tilt, since = shown[-1]
    known_from = next((first + k for k, s in enumerate(sm) if s is not None), None)
    bid, ask = snap.get("bid_total"), snap.get("ask_total")
    held = None if since is None else last - since
    return {
        **{k: snap.get(k) for k in ("bid_total", "ask_total", "difference", "total_depth")},
        "pct": sm[-1],
        "pct_text": percent_text(sm[-1]),
        "tilt": tilt,
        "side_word": TILT_WORDS.get(tilt) if tilt else None,
        "held_sec": held,
        "held_open": since is not None and since == known_from,
        "held_text": None if held is None else f"HELD {'≥' if since == known_from else ''}{held}s",
        "sentence": _CROSSED_SENTENCE if r.get("touch_state") == "CROSSED" else _sentence(bid, ask),
        "divergence": _DIVERGENCE
        if view == "weighted" and _opposite(sm[-1], snap.get("imbalance"))
        else None,
        "flips_2m": _flips(shown, first, last),
        "bid_text": count_text(bid),
        "ask_text": count_text(ask),
        "difference_text": count_text(snap.get("difference")),
        "total_text": count_text(snap.get("total_depth")),
        # how far the book's levels reach in price
        "span_bid_text": price_text(snap.get("span_bid")),
        "span_ask_text": price_text(snap.get("span_ask")),
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
    readout: dict[str, dict[str, Any]],
    points: list[tuple[float, dict[str, Any]]],
    ends: Mapping[str, float | None],
) -> dict[str, Any]:
    """Return the Liquidity card's values, every venue and view.

    The headline (the percentage standing at
    the venue's end second: now while its book is live, else its last value's), its
    tilt and side word, the seconds the tilt has held (held_open: at
    least that long, the tilt standing since the first value known), the flat totals, the
    sentence (withheld while the book is crossed), the spans, the touch and its flag, the flips
    in two minutes, and the 2m and 5m lean series. `readout`: the newest; `points`: the readouts
    kept, (receive time,
    readout) oldest first; `ends`: venue -> its end time, None with no value.
    """
    venues: dict[str, dict[str, Any]] = {}
    for v, r in readout.items():
        end = ends.get(v)
        views: dict[str, dict[str, Any]] = {}
        for view in READOUT_VIEWS:
            snap: dict[str, Any] = r["views"][view] if "views" in r else {}
            if end is None:
                views[view] = {"pct": None, "tilt": None}
                continue
            views[view] = _card_view(r, snap, points, v, view, int(end))
        touch = r["views"]["1"]["pct"] if "views" in r else None
        levels = r.get("levels")
        venues[v] = {
            **{
                k: r.get(k)
                for k in (
                    "status",
                    "book_time_ms",
                    "touch_state",
                    "one_sided_text",
                    "books",
                    "dedup_partial",
                )
            },
            "touch_pct": touch,
            "touch_text": percent_text(touch),
            "touch_flag": _TOUCH_FLAG.get(r.get("touch_state")),
            "levels_text": f"Levels available: bids {levels['bid']} · asks {levels['ask']}"
            if levels and min(levels.values()) < OF_BOOK_DEPTH_DEEP
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
    prints: list[dict[str, Any]], now: float, window_sec: float = 60.0
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


class OrderFlowEngine:
    """Order Flow Engine: computes metrics from Schwab data using only identified field paths."""

    def compute(self, data: FlowInput, *, now: float) -> dict[str, Any]:
        """Compute the book microstructure and the tape flow of one symbol at `now`.

        `now` is in epoch seconds; missing data yields None.
        """
        # the book, by its one producer (the book panel calls the same one)
        book_micro = compute_book_microstructure(data, now_ts=now)
        prints = data.prints  # the tape, in receive order
        cum_first, cum_last = cum_delta_window(prints)
        ms = now * 1000.0
        # each flow number and the decimals the screen shows it with: the pressures, each
        # value's unsigned share of the size it covers, the cumulative delta
        flow = {
            # top-of-book SIZE pressure (streamed BID_SIZE / ASK_SIZE), not a depth imbalance
            "top_book_pressure": (_compute_top_book_pressure(data), 3),
            "tape_pressure_30s": (compute_tape_pressure(prints, OF_TAPE_WINDOW_30S_SEC, ms), 3),
            "tape_pressure_2m": (compute_tape_pressure(prints, OF_TAPE_WINDOW_2M_SEC, ms), 3),
            "tape_pressure_5m": (compute_tape_pressure(prints, OF_TAPE_WINDOW_5M_SEC, ms), 3),
            "tape_unsigned_30s": (
                unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_30S_SEC)),
                2,
            ),
            "tape_unsigned_2m": (
                unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_2M_SEC)),
                2,
            ),
            "tape_unsigned_5m": (
                unsigned_share(prints, _window_start_ms(now, OF_TAPE_WINDOW_5M_SEC)),
                2,
            ),
            "cum_delta_unsigned": (unsigned_share(prints), 2),
            "cum_delta_proxy": (compute_cum_delta_proxy(prints), 1),
            "cum_delta_slope": (_compute_cum_delta_slope(prints, now), 3),
        }

        return {
            # Carry the single canonical microstructure state so the route serializes THIS
            # computed result (same book) rather than recomputing from raw data.
            "book_microstructure": book_micro,
            # each flow number, and beside it its text as the screen shows it
            **{name: value for name, (value, _places) in flow.items()},
            **{f"{name}_text": fixed_text(value, places) for name, (value, places) in flow.items()},
            # the window the cumulative delta sums: the tape's first and last print (Schwab trade
            # time), served beside the number
            "cum_delta_window": (
                "prints " + ct_label(cum_first) + " to " + ct_label(cum_last)
                if cum_first is not None and cum_last is not None
                else None
            ),
        }
