"""Order Flow Engine (app/options/order_flow/engine.py).

The book microstructure and the tape flow of one symbol, from Schwab streaming fields.

Input: dict `data` with ``content`` (the streamed book and tape items), ``top`` (the top of
book as Schwab last sent it) and ``book_live`` (whether the feed delivers the book now).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import numpy as np

from l1_trade_observation import (
    canonical_tape_prints,
    cum_delta_window,
    iter_signed_cum_points,
)
from l1_trade_observation import (
    compute_cum_delta_proxy as _canonical_cum_delta,
)
from l1_trade_observation import (
    compute_tape_pressure as _canonical_tape_pressure,
)
from numeric_contract import (
    float_finite_or_none,
    percent_text,
    price_text,
    schwab_count,
    schwab_number,
    shares_text,
)
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


def _iter_content(data: dict) -> list:
    """Yield all content items (content.*) as a flat list."""
    content = data.get("content")
    if content is None:
        return []
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        return list(content.values())
    return []


Exchanges = tuple[tuple[str, float, float | None], ...]


def _exchange_sizes(rows: object, size_key: str) -> Exchanges | None:
    """Return a level's own rows, one per exchange or market maker, as sent.

    Each row is (EXCHANGE, BID_VOLUME or ASK_VOLUME, its quote time;
    docs/schwab/schwab_streamer_api.pdf §4 Book Market Makers: field 2, "Quote time in
    milliseconds", which schwab-py names SEQUENCE; None when not sent). None when the level
    carries none, or a row lacks its code or size.
    """
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        code, size = row.get("EXCHANGE"), schwab_count(row.get(size_key))
        if not isinstance(code, str) or not code or size is None:
            return None
        out.append((code, size, schwab_number(row.get("SEQUENCE"))))
    return tuple(out)


#: one level of a book: (price, TOTAL_VOLUME, the level's per-exchange rows), as Schwab sent them
Level = tuple[float, float, Exchanges | None]


@dataclass(frozen=True)
class Book:
    """One Schwab book message (NYSE_BOOK, NASDAQ_BOOK or OPTIONS_BOOK), read once (read_book).

    Holds its service, BOOK_TIME, and each side's levels in the order Schwab sent them.
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


def read_book(content_item: dict, service: str) -> Book | None:
    """Read a Schwab book message; this is its one reader.

    None when it carries neither side (a side Schwab sent no levels for is empty).
    """
    if content_item.get("BIDS") is None and content_item.get("ASKS") is None:
        return None
    return Book(
        service,
        schwab_number(content_item.get("BOOK_TIME")),
        tuple(_side_levels(content_item, "BIDS")),
        tuple(_side_levels(content_item, "ASKS")),
    )


def _side_levels(content_item: dict, side: str) -> list[Level]:
    """Return one side of a Schwab book, "BIDS" or "ASKS".

    (price, TOTAL_VOLUME, the level's per-exchange sizes) for each level, as sent. A level
    without a number for both price and size is not a level.
    """
    price_key, size_key = (
        ("BID_PRICE", "BID_VOLUME") if side == "BIDS" else ("ASK_PRICE", "ASK_VOLUME")
    )
    raw = content_item.get(side)
    if not raw:
        return []
    out = []
    for level in raw if isinstance(raw, list) else [raw]:
        for lv in level if isinstance(level, list) else [level]:
            if not isinstance(lv, dict):
                continue
            p = schwab_number(lv.get(price_key))
            v = schwab_count(lv.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v, _exchange_sizes(lv.get(side), size_key)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BOOK METRICS
# ─────────────────────────────────────────────────────────────────────────────


def _latest_book_snapshot(items: list) -> Book | None:
    """Return the most recent book.

    A one-sided book included: the side Schwab sent no levels for is empty.
    """
    for item in reversed(items):
        if isinstance(item, Book):
            return item
    return None


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


def _top(data: dict) -> dict:
    """Return the top of book the caller supplies as ``data["top"]``.

    Its bid, ask, bid_size, ask_size and mark are each the last value Schwab sent; absent when
    Schwab has sent none.
    """
    t = data.get("top")
    return t if isinstance(t, dict) else {}


def _compute_top_book_pressure(data: dict) -> float | None:
    """Top-of-book pressure: (bid_size - ask_size) / (bid_size + ask_size), streamed sizes."""
    t = _top(data)
    bid_sz, ask_sz = t.get("bid_size"), t.get("ask_size")
    if bid_sz is None or ask_sz is None:
        return None
    total = bid_sz + ask_sz
    if total <= 0:
        return None
    return (bid_sz - ask_sz) / total


def _resolve_bid_ask_prices(data: dict) -> tuple[float | None, float | None]:
    """Level-one BID_PRICE / ASK_PRICE as Schwab sent them."""
    t = _top(data)
    return t.get("bid"), t.get("ask")


def _resolve_quote_mark(data: dict) -> float | None:
    """LEVELONE_OPTIONS MARK as Schwab sent it; a reported 0 is 0 (AGENTS.md rule 2)."""
    return _top(data).get("mark")


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL BOOK MICROSTRUCTURE  (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1)
# ─────────────────────────────────────────────────────────────────────────────
# ONE canonical book path. `_extract_canonical_book` walks + validates + SORTS the live
# book EXACTLY ONCE into a normalized state; every metric is derived from that single
# result. Nothing re-walks or re-sums the raw book. `compute_book_microstructure` memoizes the
# structural state per (ticker, BOOK_TIME), so `/api/order-flow/microstructure` and the engine
# SERIALIZE the same computed state rather than recomputing it independently.
# Every field is classified NATIVE (a Schwab wire field), DERIVED (a deterministic function of
# NATIVE fields), or PROXY (temporal inference). STATIC book state only — no aggressor/CVD/
# absorption/iceberg (see `deferred`). No opaque composite score.

#: HEURISTIC only: a displayed level is a WALL CANDIDATE when its size is at least this multiple
#: of the MEDIAN level size across the ladder. A relative size-outlier convention (tunable, and
#: blind to hidden/reserve size) — NOT an objectively-known liquidity wall. Surfaced with each
#: candidate's `median_mult` and a self-describing `wall_method` block so the API never asserts
#: a proven wall. magic-threshold-ok: relative (× median), carries its method in the payload.
OF_BOOK_WALL_MEDIAN_MULT: float = 3.0

#: Depth ladder for the canonical depth totals/imbalance — the existing 1/3/5 ladder.
OF_MICRO_DEPTH_LADDER: tuple[int, ...] = (
    OF_BOOK_DEPTH_TOP,
    OF_BOOK_DEPTH_SHALLOW,
    OF_BOOK_DEPTH_DEEP,
)

#: Per-ticker carry cache: ticker -> (canonical_book_identity, structural_payload). Lets the route
#: serialize the engine's already-computed state for an UNCHANGED book instead of re-walking raw
#: data. Validity keys on the canonical book's CONTENT identity (see `_canonical_book_identity`),
#: NOT on BOOK_TIME alone — BOOK_TIME is not assumed unique, so a changed ladder under a repeated
#: BOOK_TIME must yield a different identity and force recompute.
_MICRO_STRUCTURAL_CACHE: dict[str, tuple[tuple, dict]] = {}


def _sorted_valid_levels(
    levels: list[tuple[float, float]], *, descending: bool
) -> list[tuple[float, float]]:
    """Normalize a raw book side ONCE.

    Drop a level Schwab sent no price or size for (the raw readers drop -999, text, NaN and a
    negative size), then SORT so `[:N]` is the true Top-N regardless of the vendor's array
    order: bids DESCENDING, asks ASCENDING.
    """
    valid = [(p, v) for (p, v) in levels if p is not None and v is not None]
    valid.sort(key=lambda pv: pv[0], reverse=descending)
    return valid


def _extract_canonical_book(data: dict) -> dict:
    """Extract and normalize the live book: THE single extraction/normalization.

    Walks the content ONCE, validates and sorts both sides, and carries the live top of book
    (``data["top"]``). Every downstream metric reads this result; nothing else re-walks the raw
    book.
    """
    snapshot = _latest_book_snapshot(_iter_content(data))
    bid, ask = _resolve_bid_ask_prices(data)
    t = _top(data)
    bid_size = schwab_count(t.get("bid_size"))
    ask_size = schwab_count(t.get("ask_size"))

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


def _canonical_book_identity(cb: dict) -> tuple:
    """Return the hashable CONTENT identity of the canonical book.

    It holds every field the structural state is derived from. The carry cache validates on
    THIS, never on BOOK_TIME alone: if the same ticker receives a changed ladder (or changed
    top-of-book / mark) under a repeated BOOK_TIME, the identity differs and
    `compute_book_microstructure` recomputes instead of serving stale state. BOOK_TIME is
    included, but only as one component — its uniqueness is not assumed.
    """
    return (
        cb["book_time_ms"],
        cb["venue"],
        cb["bid"],
        cb["ask"],
        cb["bid_size"],
        cb["ask_size"],
        cb["mark"],
        tuple(cb["bid_levels"]),
        tuple(cb["ask_levels"]),
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


def _book_pressure_curve(levels: list[tuple[float, float]], max_levels: int) -> list[dict]:
    """Cumulative displayed depth per level (best-first): the depth-pressure curve."""
    out: list[dict] = []
    cum = 0.0
    for price, vol in levels[:max_levels]:
        cum += vol
        out.append({"price": price, "volume": vol, "cum": cum})
    return out


def _book_slope(levels: list[tuple[float, float]], depth: int, total: float | None) -> float | None:
    """Return the displayed depth density across the best `depth` levels.

        book_slope = (canonical top-`depth` TOTAL_VOLUME) / |best_price − last_level_price|
    Units: shares per $1 of book depth = dVolume/dPrice (depth per unit price), NOT a
    price-impact slope. Higher = liquidity packed near the touch. Reuses the CANONICAL depth
    total (passed in) rather than re-summing. None if a side has <2 levels (no span), the
    top-`depth` levels share one price (zero span), or the total is absent.
    """
    lv = levels[:depth]
    if len(lv) < 2 or total is None:
        return None
    span = abs(lv[0][0] - lv[-1][0])
    if span <= 0:
        return None
    return total / span


def _book_concentration(levels: list[tuple[float, float]], total: float | None) -> float | None:
    """Return the fraction of the top-`depth` displayed volume resting at the touch.

    The touch is the best level; the volume is the canonical top-`depth` displayed volume.
        liquidity_concentration = best_level_volume / (canonical top-`depth` TOTAL_VOLUME)
    Range [0, 1]. 1.0 = all near-book size at the inside (fragile); low = distributed down the
    ladder (resilient). Reuses the CANONICAL depth total (passed in), not a private re-sum. A
    single-level side returns 1.0. None if the side is empty or the total is non-positive.
    """
    if not levels or total is None or total <= 0:
        return None
    return levels[0][1] / total


def _book_wall_candidates(levels: list[tuple[float, float]], side: str, depth: int) -> list[dict]:
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
    out: list[dict] = []
    for price, vol in lv:
        if vol >= OF_BOOK_WALL_MEDIAN_MULT * median:
            out.append({"side": side, "price": price, "volume": vol, "median_mult": vol / median})
    return out


def _microstructure_structural(cb: dict) -> dict:
    """Return everything derivable from a single canonical book snapshot, no wall-clock `now`.

    Age fields and the per-serialization timestamps are stamped by `compute_book_microstructure`,
    so this structural state is safe to carry/memoize per (ticker, BOOK_TIME).
    """
    bid, ask = cb["bid"], cb["ask"]
    bid_size, ask_size = cb["bid_size"], cb["ask_size"]
    bid_levels, ask_levels = cb["bid_levels"], cb["ask_levels"]
    have_quotes = bid is not None and ask is not None
    crossed = have_quotes and bid > ask

    microprice = _microprice(bid, ask, bid_size, ask_size)
    spread_pts = ask - bid if have_quotes else None
    mark = cb["mark"]
    # the spread over a MARK of 0 is undefined: no value
    spread_frac = spread_pts / mark if spread_pts is not None and mark else None

    # Depth ladder: the readout's flat views (`_readout`, the one producer of a book's top-N
    # totals and imbalance), carried; slope and concentration reuse its top-5 totals.
    ladder = _readout(bid_levels, ask_levels, cb["book_time_ms"])["views"]
    depth: dict[str, dict] = {}
    for n in OF_MICRO_DEPTH_LADDER:
        lv = ladder[str(n)]
        depth[str(n)] = {
            "bid_total": lv["bid_total"],
            "ask_total": lv["ask_total"],
            "imbalance": lv["imbalance"],
        }
    deep_bt, deep_at = (
        ladder[str(OF_BOOK_DEPTH_DEEP)]["bid_total"],
        ladder[str(OF_BOOK_DEPTH_DEEP)]["ask_total"],
    )

    return {
        "status": "ok" if cb["has_book"] else "no_book",
        "top_of_book": {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size},
        "crossed": crossed,
        "mark": mark,
        "microprice": microprice,
        "spread_pts": spread_pts,
        "spread_frac": spread_frac,
        "depth": depth,
        "depth_pressure": {
            "bid": _book_pressure_curve(bid_levels, OF_BOOK_DEPTH_DEEP),
            "ask": _book_pressure_curve(ask_levels, OF_BOOK_DEPTH_DEEP),
        },
        "book_slope": {
            "bid": _book_slope(bid_levels, OF_BOOK_DEPTH_DEEP, deep_bt),
            "ask": _book_slope(ask_levels, OF_BOOK_DEPTH_DEEP, deep_at),
        },
        "liquidity_concentration": {
            "bid": _book_concentration(bid_levels, deep_bt),
            "ask": _book_concentration(ask_levels, deep_at),
        },
        "wall_candidates": (
            _book_wall_candidates(bid_levels, "bid", OF_BOOK_DEPTH_DEEP)
            + _book_wall_candidates(ask_levels, "ask", OF_BOOK_DEPTH_DEEP)
        ),
        "wall_method": {
            "basis": "displayed level TOTAL_VOLUME >= mult x median top-N level size",
            "mult": OF_BOOK_WALL_MEDIAN_MULT,
            "depth": OF_BOOK_DEPTH_DEEP,
            "heuristic": True,
            "note": "size-outlier candidates in the DISPLAYED book only; blind to hidden/reserve "
            "size; NOT an objectively-known liquidity wall",
        },
        "provenance_structural": {
            "book_time_ms": cb["book_time_ms"],
            "n_bid_levels": len(bid_levels),
            "n_ask_levels": len(ask_levels),
            "book_source": cb["venue"] if cb["has_book"] else "unavailable",
        },
        "classification": {
            "top_of_book.bid": "NATIVE",
            "top_of_book.ask": "NATIVE",
            "top_of_book.bid_size": "NATIVE",
            "top_of_book.ask_size": "NATIVE",
            "mark": "NATIVE",
            "microprice": "DERIVED",
            "crossed": "DERIVED",
            "spread_pts": "DERIVED",
            "spread_frac": "DERIVED",
            "depth.*.bid_total": "DERIVED",
            "depth.*.ask_total": "DERIVED",
            "depth.*.imbalance": "DERIVED",
            "depth_pressure": "DERIVED",
            "book_slope": "DERIVED",
            "liquidity_concentration": "DERIVED",
            "wall_candidates": "DERIVED-HEURISTIC (size-outlier convention; see wall_method)",
            "ages.book_age_sec": "DERIVED",
            "ages.quote_age_sec": "DERIVED",
            "ages.book_stale": "DERIVED",
            "provenance.book_time_ms": "NATIVE",
            "provenance.exchange_quote_ts": "NATIVE",
            "provenance.server_received_ts": "DERIVED",
        },
        "deferred": [
            "aggressor_side (PROXY: needs trade-vs-quote classification history)",
            "cvd / cum_delta (PROXY: exists as cum_delta_proxy in the engine, tape-based)",
            "absorption / replenishment (PROXY: exists in the engine, 2-snapshot compare)",
            "iceberg / add-pull / institutional_flow (PROXY: no evidence base in this slice)",
        ],
    }


def book_age_sec(book_time_ms: float | None, now: float) -> float | None:
    """Seconds from Schwab's BOOK_TIME to `now`; None with no book time."""
    return None if book_time_ms is None else now - book_time_ms / 1000.0


def compute_book_microstructure(data: dict, *, now_ts: float, ticker: str | None = None) -> dict:
    """Compute the canonical L2 book microstructure for one symbol at `now_ts` (epoch seconds).

    The ONE producer the engine and the `/api/order-flow/microstructure` route both read.
    `data.content`
    carries the live streaming book + top-of-book
    (app.options.order_flow.state.get_content_for_symbol); `data.exchange_quote_ts` (optional) is
    the plane's exchange quote clock; `data.book_live` is the live rule's answer for the book's
    service (absent: not live). The structural state
    is extracted/computed ONCE and memoized per (ticker, BOOK_TIME); a caller with the same
    unchanged book SERIALIZES the cached state instead of re-walking raw data. Only the age
    fields depend on `now` and are always stamped fresh. Fail-closed: no book snapshot -> status
    'no_book' with null metrics (no fabricated values).
    """
    now = now_ts
    cb = _extract_canonical_book(data)
    book_time_ms = cb["book_time_ms"]

    # Carry only when the canonical book CONTENT is byte-for-byte identical — not merely the same
    # BOOK_TIME. A changed ladder under a repeated BOOK_TIME has a different identity and
    # recomputes.
    identity = _canonical_book_identity(cb)
    cached = _MICRO_STRUCTURAL_CACHE.get(ticker) if ticker else None
    if cached is not None and cached[0] == identity:
        structural = cached[1]  # carry: identical canonical book, no recompute
    else:
        structural = _microstructure_structural(cb)
        if ticker:
            _MICRO_STRUCTURAL_CACHE[ticker] = (identity, structural)

    # Ages + per-serialization stamps are the only wall-clock-dependent fields.
    exch_ts = float_finite_or_none(data.get("exchange_quote_ts"))
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
        # passes as data["book_live"]; None with no book
        "book_stale": None if age is None else data.get("book_live") is not True,
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
#: the zones of the headline percentage, a guide: BALANCED under 10, leaning under 70, very
#: one-sided from 70
OF_ZONE_LEANING_PCT: float = 10.0
OF_ZONE_ONE_SIDED_PCT: float = 70.0
#: the headline is the median of the last OF_SMOOTH_SEC one-second values
OF_SMOOTH_SEC: int = 5
#: a zone changes once the smoothed value has stood in another zone this many seconds
OF_ZONE_DWELL_SEC: int = 3
#: this many flips in two minutes read CHOPPY, fewer STEADY
OF_CHOPPY_FLIPS: int = 5
#: the lean sparklines: (name, window in seconds, one point every this many seconds)
OF_LEAN_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("2m", int(OF_TAPE_WINDOW_2M_SEC), 1),
    ("5m", int(OF_TAPE_WINDOW_5M_SEC), 5),
)
#: the one-second values kept: the longest window, with its smoothing and dwell before it
OF_LEAN_KEPT_SEC: int = int(OF_TAPE_WINDOW_5M_SEC) + OF_SMOOTH_SEC + OF_ZONE_DWELL_SEC
ZONE_WORDS = {
    "VERY_BID": "VERY ONE-SIDED · BID HEAVY",
    "BID_HEAVY": "BID HEAVY",
    "BALANCED": "BALANCED",
    "OFFER_HEAVY": "OFFER HEAVY",
    "VERY_OFFER": "VERY ONE-SIDED · OFFER HEAVY",
}
#: a zone's side, for flips: BALANCED is none
_SIDE = {"VERY_BID": "BID", "BID_HEAVY": "BID", "OFFER_HEAVY": "OFFER", "VERY_OFFER": "OFFER"}
#: the detail panel's words
READOUT_DETAIL = {
    "weights": "Headline weights by price level from the touch: "
    + ", ".join(f"{w:.2f}" for w in OF_LEVEL_WEIGHTS)
    + f" (exp(-{OF_LEVEL_DECAY}·(k-1)), normalized; renormalized over the levels a thin side has)."
    " Starting weights from a vendor study (VisualHFT, touch-weighted), adjustable.",
    "zones": "Zones, a provisional guide and not a research finding: BALANCED under"
    f" {OF_ZONE_LEANING_PCT:.0f}% (Bookmap's colour-switch line); BID or OFFER HEAVY from"
    f" {OF_ZONE_LEANING_PCT:.0f}% to under {OF_ZONE_ONE_SIDED_PCT:.0f}%; VERY ONE-SIDED from"
    f" {OF_ZONE_ONE_SIDED_PCT:.0f}% (a VisualHFT vendor study, not a peer-reviewed paper). The"
    " middle range grades direction only, not strength. The headline is the median of the last"
    f" {OF_SMOOTH_SEC} seconds; a zone changes after {OF_ZONE_DWELL_SEC} seconds across its line;"
    " a flip is a change of side, bid to offer or back, held that long; "
    f"{OF_CHOPPY_FLIPS} or more flips in 2 minutes read CHOPPY.",
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
_CROSSED_SENTENCE = "Book crossed — bid and ask overlap, no balancing sentence."
_TOUCH_FLAG = {"CROSSED": "BOOK CROSSED", "LOCKED": "BOOK LOCKED"}

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


def _readout(bids: Levels, asks: Levels, book_time_ms: float | None) -> dict:
    """Return one book's views.

    The flat totals of its best 1, 3 and 5 levels and their imbalance (the
    one producer of a book's depth ladder: the bars, difference and sentence here, and the
    microstructure's `depth`), and the headline percentage (the weighted view's flat totals are
    the top five's).
    """
    views = {}
    for view in READOUT_VIEWS:
        depth = OF_BOOK_DEPTH_DEEP if view == "weighted" else int(view)
        bt, at = _book_side_depth_total(bids, depth), _book_side_depth_total(asks, depth)
        imb = _book_imbalance_from_totals(bt, at)
        both = bt is not None and at is not None
        views[view] = {
            "imbalance": imb,
            "pct": _pct(_book_imbalance_from_totals(_weighted_total(bids), _weighted_total(asks)))
            if view == "weighted"
            else _pct(imb),
            "bid_total": bt,
            "ask_total": at,
            "difference": abs(bt - at) if both else None,
            "total_depth": bt + at if both else None,
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


def book_readout(books: dict[str, Book | None]) -> dict[str, dict]:
    """Return the imbalance readout of each Schwab book and of their composite.

    Read from each venue's newest book (`state.newest_book`, every venue of BOOK_VENUES; None:
    no book). The composite is of the books held (`books` names them): with one, that book; with
    none, no_book, `books` naming the two it reads. Its time is its older book's.
    """
    out: dict[str, dict] = {}
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
    times = [b.book_time_ms for b in held.values()]
    (bids, bid_partial), (asks, ask_partial) = (_composite_side(held, s) for s in ("BIDS", "ASKS"))
    out[COMPOSITE] = _readout(bids, asks, None if None in times else min(times))
    out[COMPOSITE]["books"] = list(held)
    out[COMPOSITE]["dedup_partial"] = bid_partial or ask_partial
    return out


def _headline(readout: dict[str, dict], venue: str, view: str) -> float | None:
    r = readout[venue]
    return r["views"][view]["pct"] if "views" in r else None


def _standing(points: list[tuple[float, dict]], venue: str, view: str, first: int, last: int):
    """Return the headline percentage of `venue` and `view` standing in each second first..last.

    Each whole second's value is the newest readout received by that second's end (Schwab sends
    a book only when it changes, so the last one stands).
    """
    out, i, cur = [], 0, None
    for sec in range(first, last + 1):
        while i < len(points) and points[i][0] < sec + 1:
            cur = _headline(points[i][1], venue, view)
            i += 1
        out.append(cur)
    return out


def _smoothed(values: list) -> list:
    """Each second's median of the last OF_SMOOTH_SEC values; unknown while the value is."""
    return [
        None
        if values[i] is None
        else statistics.median(
            v for v in values[max(0, i - OF_SMOOTH_SEC + 1) : i + 1] if v is not None
        )
        for i in range(len(values))
    ]


def _zone(pct: float | None) -> str | None:
    if pct is None:
        return None
    if abs(pct) < OF_ZONE_LEANING_PCT:
        return "BALANCED"
    if abs(pct) < OF_ZONE_ONE_SIDED_PCT:
        return "BID_HEAVY" if pct > 0 else "OFFER_HEAVY"
    return "VERY_BID" if pct > 0 else "VERY_OFFER"


def _dwelled(smoothed: list, first: int) -> list[tuple[str | None, int | None]]:
    """Return each second's zone shown.

    Once the smoothed values have stood outside the shown zone
    OF_ZONE_DWELL_SEC seconds in a row, whichever zones they crossed, the zone they stand in
    then, dated from the second they entered it. Each second's zone and that second; (None, None)
    while the value is unknown.
    """
    shown = []
    zone = since = left = entered = prev = None
    for k, s in enumerate(smoothed):
        z = _zone(s)
        if z != prev:
            entered = first + k
        prev = z
        if z is None:
            zone = since = left = None
        elif zone is None:
            zone, since = z, entered
        elif z == zone:
            left = None
        else:
            if left is None:
                left = first + k
            if first + k - left + 1 >= OF_ZONE_DWELL_SEC:
                zone, since, left = z, entered, None
        shown.append((zone, since))
    return shown


def _flips(shown: list[tuple[str | None, int | None]], first: int, last: int) -> int:
    """Count the flips arriving in the two minutes to second `last`.

    A flip is the zone shown (`_dwelled`, from
    second `first`) reaching the side opposite the one it last held, bid to offer or back.
    BALANCED is no side, so bid, BALANCED, offer is one flip, on arrival; the first lean is none;
    after an unknown value the count of sides starts over.
    """
    flips, held = 0, None
    for k, (zone, _since) in enumerate(shown):
        if zone is None:
            held = None
        elif zone in _SIDE:
            if (
                held is not None
                and _SIDE[zone] != held
                and first + k > last - OF_TAPE_WINDOW_2M_SEC
            ):
                flips += 1
            held = _SIDE[zone]
    return flips


def _lean(values: list) -> str | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return (
        "BUYERS"
        if all(v > 0 for v in known)
        else "SELLERS"
        if all(v < 0 for v in known)
        else "MIXED"
    )


def _sentence(zone: str | None, bid: float | None, ask: float | None) -> str | None:
    """Return arithmetic about the displayed book.

    The flat shares one side would need to match the other.
    """
    if zone is None or bid is None or ask is None:
        return None
    diff = abs(bid - ask)
    if diff == 0:
        return "Balanced — no shares needed to balance."
    if zone == "BALANCED":
        return f"Nearly balanced — {shares_text(diff)} shares would even the book."
    return f"To balance, market makers {'sell' if bid > ask else 'buy'} {shares_text(diff)} shares."


def _opposite(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a * b < 0


def readout_card(readout: dict[str, dict], points: list[tuple[float, dict]], ends: dict) -> dict:
    """Return the Liquidity card's values, every venue and view.

    The headline (the smoothed percentage at
    the venue's end second: now while its book is live, else its last value's), its live value,
    zone and side word held OF_ZONE_DWELL_SEC, the seconds the zone has held (held_open: at
    least that long, the zone standing since the first value known), the flat totals, the
    sentence (withheld while the book is crossed), the spans, the touch and its flag, the flips
    in two minutes, and the 2m and 5m lean series. `readout`: the newest; `points`: the readouts
    kept, (receive time,
    readout) oldest first; `ends`: venue -> its end time, None with no value.
    """
    venues: dict[str, dict] = {}
    for v, r in readout.items():
        end = ends.get(v)
        views = {}
        for view in READOUT_VIEWS:
            snap = r["views"][view] if "views" in r else {}
            if end is None:
                views[view] = {"pct": None, "live_pct": snap.get("pct"), "zone": None}
                continue
            last = int(end)
            first = last - OF_LEAN_KEPT_SEC
            sm = _smoothed(_standing(points, v, view, first, last))
            shown = _dwelled(sm, first)
            zone, since = shown[-1]
            known_from = next((first + k for k, s in enumerate(sm) if s is not None), None)
            flips = _flips(shown, first, last)
            bid, ask = snap.get("bid_total"), snap.get("ask_total")
            live = snap.get("pct")
            held = None if since is None else last - since
            views[view] = {
                **{k: snap.get(k) for k in ("bid_total", "ask_total", "difference", "total_depth")},
                "pct": sm[-1],
                "pct_text": percent_text(sm[-1]),
                "live_pct": live,
                "live_text": percent_text(live),
                "zone": zone,
                "side_word": ZONE_WORDS.get(zone) if zone else None,
                "held_sec": held,
                "held_open": since is not None and since == known_from,
                "held_text": None
                if held is None
                else f"HELD {'≥' if since == known_from else ''}{held}s",
                "sentence": _CROSSED_SENTENCE
                if r.get("touch_state") == "CROSSED"
                else _sentence(zone, bid, ask),
                "divergence": _DIVERGENCE
                if view == "weighted" and _opposite(live, snap.get("imbalance"))
                else None,
                "flips_2m": flips,
                "flips_word": "CHOPPY" if flips >= OF_CHOPPY_FLIPS else "STEADY",
                "bid_text": shares_text(bid),
                "ask_text": shares_text(ask),
                "difference_text": shares_text(snap.get("difference")),
                "total_text": shares_text(snap.get("total_depth")),
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


def _compute_tape_pressure(data: dict, window_sec: float, now: float) -> float | None:
    """PROXY reconstructed L1 tick-rule pressure. ONE FAUCET: l1_trade_observation."""
    return _canonical_tape_pressure(
        canonical_tape_prints(_iter_content(data)), window_sec, now * 1000.0
    )


# ─────────────────────────────────────────────────────────────────────────────
# CUMULATIVE DELTA PROXY
# ─────────────────────────────────────────────────────────────────────────────


def _compute_cum_delta_proxy(data: dict) -> float | None:
    """PROXY reconstructed L1 tick-rule signed size sum. ONE FAUCET: l1_trade_observation."""
    return _canonical_cum_delta(canonical_tape_prints(_iter_content(data)))


def _compute_cum_delta_slope(data: dict, now: float, window_sec: float = 60.0) -> float | None:
    """Slope of PROXY cum-delta in receive order. ONE signed-size walk: l1_trade_observation."""
    points = iter_signed_cum_points(
        canonical_tape_prints(_iter_content(data)), window_sec, now * 1000.0
    )
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

    def compute(self, data: dict, *, now: float, ticker: str | None = None) -> dict:
        """Compute the book microstructure and the tape flow of one symbol at `now`.

        `now` is in epoch seconds; missing data yields None.
        """
        # the book, extracted once by its one producer; `ticker` lets the route serialize this
        # same computed state (carry, not recompute)
        book_micro = compute_book_microstructure(data, now_ts=now, ticker=ticker)
        # top-of-book SIZE pressure (streamed BID_SIZE / ASK_SIZE), not a depth imbalance
        top_book_pressure = _compute_top_book_pressure(data)

        # Tape metrics
        tape_pressure_30s = _compute_tape_pressure(data, OF_TAPE_WINDOW_30S_SEC, now)
        tape_pressure_2m = _compute_tape_pressure(data, OF_TAPE_WINDOW_2M_SEC, now)
        tape_pressure_5m = _compute_tape_pressure(data, OF_TAPE_WINDOW_5M_SEC, now)

        # Cumulative delta
        cum_delta_proxy = _compute_cum_delta_proxy(data)
        cum_first, cum_last = cum_delta_window(canonical_tape_prints(_iter_content(data)))
        cum_delta_slope = _compute_cum_delta_slope(data, now)

        return {
            # Carry the single canonical microstructure state so the route serializes THIS
            # computed result (same book) rather than recomputing from raw data.
            "book_microstructure": book_micro,
            "top_book_pressure": top_book_pressure,
            "tape_pressure_30s": tape_pressure_30s,
            "tape_pressure_2m": tape_pressure_2m,
            "tape_pressure_5m": tape_pressure_5m,
            "cum_delta_proxy": cum_delta_proxy,
            # the window the cumulative delta sums: the tape's first and last print (Schwab trade
            # time), served beside the number
            "cum_delta_window": (
                "prints " + ct_label(cum_first) + " to " + ct_label(cum_last)
                if cum_first is not None
                else None
            ),
            "cum_delta_slope": cum_delta_slope,
        }
