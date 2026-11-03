"""
app/options/order_flow/engine.py — Order Flow Engine
========================================
The book microstructure and the tape flow of one symbol, from Schwab streaming fields.

Input: dict `data` with ``content`` (the streamed book and tape items), ``top`` (the top of
book as Schwab last sent it) and ``book_live`` (whether the feed delivers the book now).
"""

from __future__ import annotations

import collections
import itertools
import math
import statistics

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


Exchanges = tuple[tuple[str, float], ...]


def _exchange_sizes(rows: object, size_key: str) -> Exchanges | None:
    """A level's own rows, one per exchange or market maker (EXCHANGE, BID_VOLUME or ASK_VOLUME),
    as sent. None when the level carries none, or a row lacks its code or a size."""
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for row in rows:
        code = row.get("EXCHANGE") if isinstance(row, dict) else None
        size = schwab_count(row.get(size_key)) if isinstance(row, dict) else None
        if not isinstance(code, str) or not code or size is None:
            return None
        out.append((code, size))
    return tuple(out)


def _side_levels(content_item: dict, side: str) -> list[tuple[float, float, Exchanges | None]]:
    """One side of a Schwab book, "BIDS" or "ASKS": (price, TOTAL_VOLUME, the level's per-exchange
    sizes) for each level, as sent. A level without a number for both price and size is not a
    level."""
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


def _flat(content_item: dict, side: str) -> list[tuple[float, float]]:
    """One side of a Schwab book as (price, TOTAL_VOLUME) pairs."""
    return [(p, v) for p, v, _ in _side_levels(content_item, side)]


# ─────────────────────────────────────────────────────────────────────────────
# BOOK METRICS
# ─────────────────────────────────────────────────────────────────────────────


def _latest_book_snapshot(items: list) -> dict | None:
    """Return the most recent book content item (a one-sided book included: the side Schwab sent
    no levels for is empty)."""
    for item in reversed(items):
        if isinstance(item, dict) and ("BIDS" in item or "ASKS" in item):
            return item
    return None


def _book_side_depth_total(levels: list[tuple[float, float]], depth: int) -> float | None:
    """Σ TOTAL_VOLUME over the best `depth` levels (best-first). None when the side has no
    levels. The microstructure depth ladder's one depth aggregation."""
    if not levels:
        return None
    return sum(v for _, v in levels[:depth])


def _book_imbalance_from_totals(bid_total: float | None, ask_total: float | None) -> float | None:
    """THE single book-imbalance formula: (bid - ask) / (bid + ask). None if a side total is
    absent or the combined depth is non-positive."""
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
    """The top of book the caller supplies as ``data["top"]`` -- bid, ask, bid_size, ask_size,
    mark -- each the last value Schwab sent; absent when Schwab has sent none."""
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


def _resolve_bid_ask_prices(
    data: dict,
) -> tuple[float | None, float | None, str | None, str | None]:
    """Level-one BID_PRICE / ASK_PRICE and their leaf labels."""
    t = _top(data)
    bid_p, ask_p = t.get("bid"), t.get("ask")
    return (
        bid_p,
        ask_p,
        "streaming.BID_PRICE" if bid_p is not None else None,
        "streaming.ASK_PRICE" if ask_p is not None else None,
    )


def _resolve_quote_mark(data: dict) -> tuple[float | None, str | None]:
    """Streamed MARK, the spread-fraction denominator (a MARK of 0 divides nothing)."""
    mark_p = _top(data).get("mark")
    if mark_p is not None and mark_p > 0:
        return mark_p, "streaming.MARK"
    return None, None


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
    """Normalize a raw book side ONCE: drop a level Schwab sent no price or size for (the raw
    readers drop -999, text, NaN and a negative size), then SORT so `[:N]` is the true Top-N
    regardless of the vendor's array order: bids DESCENDING, asks ASCENDING."""
    valid = [(p, v) for (p, v) in levels if p is not None and v is not None]
    valid.sort(key=lambda pv: pv[0], reverse=descending)
    return valid


def _extract_canonical_book(data: dict) -> dict:
    """THE single extraction/normalization of the live book. Walks the content ONCE, validates
    and sorts both sides, and carries the live top of book (``data["top"]``). Every downstream
    metric reads this result; nothing else re-walks the raw book."""
    snapshot = _latest_book_snapshot(_iter_content(data))
    bid, ask, bid_leaf, ask_leaf = _resolve_bid_ask_prices(data)
    t = _top(data)
    bid_size = schwab_count(t.get("bid_size"))
    ask_size = schwab_count(t.get("ask_size"))

    bid_levels = _sorted_valid_levels(_flat(snapshot, "BIDS"), descending=True) if snapshot else []
    ask_levels = _sorted_valid_levels(_flat(snapshot, "ASKS"), descending=False) if snapshot else []
    mark, mark_leaf = _resolve_quote_mark(data)
    return {
        "has_book": snapshot is not None,
        "venue": snapshot.get("SERVICE") if snapshot else None,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bid_leaf": bid_leaf,
        "ask_leaf": ask_leaf,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "book_time_ms": schwab_number(snapshot.get("BOOK_TIME")) if snapshot else None,
        "mark": mark,
        "mark_leaf": mark_leaf,
    }


def _canonical_book_identity(cb: dict) -> tuple:
    """Hashable CONTENT identity of the canonical book — every field the structural state is
    derived from. The carry cache validates on THIS, never on BOOK_TIME alone: if the same ticker
    receives a changed ladder (or changed top-of-book / mark) under a repeated BOOK_TIME, the
    identity differs and `compute_book_microstructure` recomputes instead of serving stale state.
    BOOK_TIME is included, but only as one component — its uniqueness is not assumed."""
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
    """Size-weighted top-of-book fair price:
        microprice = (bid·ask_size + ask·bid_size) / (bid_size + ask_size)
    Each price is weighted by the OPPOSITE side's size, so heavier bid size pulls the fair
    price toward the ask (imminent buy pressure). DERIVED from Schwab's quotes as sent. None on
    a missing leg (Schwab sent none) or zero total size (nothing to weight)."""
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
    """Displayed depth density across the best `depth` levels:
        book_slope = (canonical top-`depth` TOTAL_VOLUME) / |best_price − last_level_price|
    Units: shares per $1 of book depth = dVolume/dPrice (depth per unit price), NOT a
    price-impact slope. Higher = liquidity packed near the touch. Reuses the CANONICAL depth
    total (passed in) rather than re-summing. None if a side has <2 levels (no span), the
    top-`depth` levels share one price (zero span), or the total is absent."""
    lv = levels[:depth]
    if len(lv) < 2 or total is None:
        return None
    span = abs(lv[0][0] - lv[-1][0])
    if span <= 0:
        return None
    return total / span


def _book_concentration(levels: list[tuple[float, float]], total: float | None) -> float | None:
    """Fraction of the canonical top-`depth` displayed volume resting at the touch (best level):
        liquidity_concentration = best_level_volume / (canonical top-`depth` TOTAL_VOLUME)
    Range [0, 1]. 1.0 = all near-book size at the inside (fragile); low = distributed down the
    ladder (resilient). Reuses the CANONICAL depth total (passed in), not a private re-sum. A
    single-level side returns 1.0. None if the side is empty or the total is non-positive."""
    if not levels or total is None or total <= 0:
        return None
    return levels[0][1] / total


def _book_wall_candidates(levels: list[tuple[float, float]], side: str, depth: int) -> list[dict]:
    """HEURISTIC displayed-size anomalies — candidates, NOT objectively-known liquidity walls.
    A level is a candidate when its size ≥ OF_BOOK_WALL_MEDIAN_MULT × the MEDIAN level size
    across the best `depth` levels: a relative size outlier in the DISPLAYED order book only
    (it cannot see hidden/reserve size, and the multiple is a tunable convention, not a proven
    boundary). Each entry carries `median_mult` (its size ÷ the median) so a consumer sees HOW
    anomalous rather than a binary truth. Empty when there is no positive median or nothing
    clears the multiple."""
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
    """Everything derivable from a single canonical book snapshot — no wall-clock `now`. Age
    fields and the per-serialization timestamps are stamped by `compute_book_microstructure`,
    so this structural state is safe to carry/memoize per (ticker, BOOK_TIME)."""
    bid, ask = cb["bid"], cb["ask"]
    bid_size, ask_size = cb["bid_size"], cb["ask_size"]
    bid_levels, ask_levels = cb["bid_levels"], cb["ask_levels"]
    have_quotes = bid is not None and ask is not None
    crossed = have_quotes and bid > ask

    # computed from Schwab's quotes as sent, a crossed book included (served with `crossed`)
    mid = (bid + ask) / 2.0 if have_quotes else None
    microprice = _microprice(bid, ask, bid_size, ask_size)
    spread_pts = ask - bid if have_quotes else None
    mark = cb["mark"]
    spread_frac = spread_pts / mark if (spread_pts is not None and mark is not None) else None

    # Depth ladder — totals aggregated ONCE per (side, depth); imbalance, slope and concentration
    # all reuse these SAME canonical totals. One aggregation authority (`_book_side_depth_total`).
    depth: dict[str, dict] = {}
    totals: dict[int, tuple[float | None, float | None]] = {}
    for n in OF_MICRO_DEPTH_LADDER:
        bt = _book_side_depth_total(bid_levels, n)
        at = _book_side_depth_total(ask_levels, n)
        totals[n] = (bt, at)
        imb = _book_imbalance_from_totals(bt, at)
        # the heavier side, by the imbalance's sign (no threshold): what every panel labels
        side = None if imb is None else "BID" if imb > 0 else "ASK" if imb < 0 else "EVEN"
        depth[str(n)] = {"bid_total": bt, "ask_total": at, "imbalance": imb, "side": side}
    deep_bt, deep_at = totals[OF_BOOK_DEPTH_DEEP]

    return {
        "status": "ok" if cb["has_book"] else "no_book",
        "top_of_book": {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size},
        "crossed": crossed,
        "mid": mid,
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
            "top_of_book_bid_leaf": cb["bid_leaf"],
            "top_of_book_ask_leaf": cb["ask_leaf"],
        },
        "classification": {
            "top_of_book.bid": "NATIVE",
            "top_of_book.ask": "NATIVE",
            "top_of_book.bid_size": "NATIVE",
            "top_of_book.ask_size": "NATIVE",
            "mid": "DERIVED",
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


def compute_book_microstructure(data: dict, *, now_ts: float, ticker: str | None = None) -> dict:
    """Canonical L2 book microstructure for one symbol at `now_ts` (epoch seconds) — the ONE
    producer the engine and the `/api/order-flow/microstructure` route both read. `data.content`
    carries the live streaming book + top-of-book
    (app.options.order_flow.state.get_content_for_symbol); `data.exchange_quote_ts` (optional) is
    the plane's exchange quote clock; `data.book_live` is the live rule's answer for the book's
    service (absent: not live). The structural state
    is extracted/computed ONCE and memoized per (ticker, BOOK_TIME); a caller with the same
    unchanged book SERIALIZES the cached state instead of re-walking raw data. Only the age
    fields depend on `now` and are always stamped fresh. Fail-closed: no book snapshot -> status
    'no_book' with null metrics (no fabricated values)."""
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
    book_age_sec = now - book_time_ms / 1000.0 if book_time_ms else None
    payload["ages"] = {
        "book_age_sec": book_age_sec,
        "quote_age_sec": now - exch_ts if exch_ts else None,
        # the live rule (live_market_plane.feed_live_for on the book's service), which the caller
        # passes as data["book_live"]; None with no book
        "book_stale": None if book_age_sec is None else data.get("book_live") is not True,
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
#: this many sign changes of the smoothed value in two minutes read CHOPPY, fewer STEADY
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
READOUT_GUIDE = (
    "Weighted headline: level weights "
    + ", ".join(f"{w:.2f}" for w in OF_LEVEL_WEIGHTS)
    + " from the touch (exp(-0.5·(k-1)), normalized). Zones, a guide and not a research finding:"
    f" BALANCED under {OF_ZONE_LEANING_PCT:.0f}%, leaning {OF_ZONE_LEANING_PCT:.0f}% to under"
    f" {OF_ZONE_ONE_SIDED_PCT:.0f}%, very one-sided from {OF_ZONE_ONE_SIDED_PCT:.0f}%. Headline:"
    f" median of the last {OF_SMOOTH_SEC} seconds; a zone changes after {OF_ZONE_DWELL_SEC}"
    f" seconds across its line; {OF_CHOPPY_FLIPS} or more sign changes in 2 minutes read CHOPPY."
)
_DIVERGENCE = "Touch and deeper book disagree"

Levels = list[tuple[float, float]]


def _composite_side(
    books: list[tuple[float | None, dict]], side: str
) -> tuple[Levels, Levels, bool]:
    """The deduped union of one side of both books. Each exchange or market maker counts once,
    from the book with the newer BOOK_TIME; its code is matched without regard to case
    (NASDAQ_BOOK sends arcx where NYSE_BOOK sends ARCX). Returns the levels (price, shares) best
    first, the copies left out (price, shares), and whether a level carried no per-exchange rows,
    its TOTAL_VOLUME then taken whole (the dedup partial). A book whose BOOK_TIME is unknown comes
    after one whose time is known."""
    sizes: collections.defaultdict[float, float] = collections.defaultdict(float)
    dropped: Levels = []
    partial = False
    taken: set[str] = set()
    timed = sorted((b for b in books if b[0] is not None), key=lambda b: b[0], reverse=True)
    for _time, item in timed + [b for b in books if b[0] is None]:
        mine: set[str] = set()
        for price, total, rows in _side_levels(item, side):
            if rows is None:
                partial = True
                sizes[price] += total
                continue
            for code, size in rows:
                if code.upper() in taken:
                    dropped.append((price, size))
                else:
                    mine.add(code.upper())
                    sizes[price] += size
        taken |= mine
    return sorted(sizes.items(), reverse=side == "BIDS"), dropped, partial


def _counted_twice(levels: Levels, dropped: Levels, depth: int, side: str) -> float:
    """The shares of the copies left out that sit inside the composite's best `depth` levels: what
    summing the two books would count twice there."""
    if len(levels) < depth:
        return sum(s for _p, s in dropped)
    edge = levels[depth - 1][0]
    return sum(s for p, s in dropped if (p >= edge if side == "BIDS" else p <= edge))


def _weighted_total(levels: Levels) -> float | None:
    """Σ OF_LEVEL_WEIGHTS[k] × shares over the best five levels; None for an empty side."""
    if not levels:
        return None
    return sum(w * v for w, (_p, v) in zip(OF_LEVEL_WEIGHTS, levels, strict=False))


def _pct(bid: float | None, ask: float | None) -> float | None:
    imb = _book_imbalance_from_totals(bid, ask)
    return None if imb is None else imb * 100.0


def _readout(bids: Levels, asks: Levels, book_time_ms: float | None) -> dict:
    """One book's views: the headline percentage, and the flat totals the bars, the difference and
    the sentence use (the weighted view's are the flat top five)."""
    views = {}
    for view in READOUT_VIEWS:
        depth = OF_BOOK_DEPTH_DEEP if view == "weighted" else int(view)
        bt, at = _book_side_depth_total(bids, depth), _book_side_depth_total(asks, depth)
        flat = _pct(bt, at)
        both = bt is not None and at is not None
        v = {
            "pct": _pct(_weighted_total(bids), _weighted_total(asks))
            if view == "weighted"
            else flat,
            "flat_pct": flat,
            "bid_total": bt,
            "ask_total": at,
            "difference": abs(bt - at) if both else None,
            "total_depth": bt + at if both else None,
        }
        views[view] = v
    touch = None
    if bids and asks:
        touch = (
            "CROSSED" if bids[0][0] > asks[0][0] else "LOCKED" if bids[0][0] == asks[0][0] else None
        )
    return {
        "status": "ok" if bids and asks else "one_sided" if bids or asks else "empty",
        "book_time_ms": book_time_ms,
        "touch_state": touch,
        "views": views,
    }


def book_readout(contents: dict[str, list]) -> dict[str, dict]:
    """The imbalance readout of each Schwab book and of their deduped composite, from each
    venue's content (`state.get_content_for_symbol` for that venue, every venue of BOOK_VENUES).
    The composite's time is its older book's. No book: status no_book."""
    books = {v: _latest_book_snapshot(contents[v]) for v in BOOK_VENUES}
    out: dict[str, dict] = {}
    for v, item in books.items():
        if item is None:
            out[v] = {"status": "no_book", "book_time_ms": None}
            continue
        bids = _sorted_valid_levels(_flat(item, "BIDS"), descending=True)
        asks = _sorted_valid_levels(_flat(item, "ASKS"), descending=False)
        out[v] = _readout(bids, asks, schwab_number(item.get("BOOK_TIME")))
    held = [(schwab_number(i.get("BOOK_TIME")), i) for i in books.values() if i is not None]
    if not held:
        out[COMPOSITE] = {"status": "no_book", "book_time_ms": None}
        return out
    bids, bid_dropped, bid_partial = _composite_side(held, "BIDS")
    asks, ask_dropped, ask_partial = _composite_side(held, "ASKS")
    times = [t for t, _i in held]
    out[COMPOSITE] = _readout(bids, asks, None if None in times else min(times))
    for view, v in out[COMPOSITE]["views"].items():
        depth = OF_BOOK_DEPTH_DEEP if view == "weighted" else int(view)
        v["counted_twice"] = {
            "bid": _counted_twice(bids, bid_dropped, depth, "BIDS"),
            "ask": _counted_twice(asks, ask_dropped, depth, "ASKS"),
        }
    out[COMPOSITE]["books"] = [v for v, i in books.items() if i is not None]
    out[COMPOSITE]["dedup_partial"] = bid_partial or ask_partial
    return out


def lean_point(readout: dict[str, dict]) -> dict[str, float | None]:
    """The headline percentage of every venue and view of one readout, keyed "venue|view": the
    one-second value the lean series keeps."""
    return {
        f"{v}|{view}": r["views"][view]["pct"] if "views" in r else None
        for v, r in readout.items()
        for view in READOUT_VIEWS
    }


def _standing(points: list[tuple[float, dict]], key: str, first: int, last: int) -> list:
    """The value standing in each whole second first..last: the newest point received by that
    second's end (Schwab sends a book only when it changes, so the last one stands)."""
    out, i, cur = [], 0, None
    for sec in range(first, last + 1):
        while i < len(points) and points[i][0] < sec + 1:
            cur = points[i][1].get(key)
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


def _dwelled(smoothed: list, first: int) -> tuple[str | None, int | None]:
    """The zone the smoothed values stand in, a new zone taken once they have stood in it
    OF_ZONE_DWELL_SEC seconds, and the second it began; (None, None) while the value is
    unknown."""
    zone = since = cand = cand_at = None
    run = 0
    for k, s in enumerate(smoothed):
        z = _zone(s)
        if z is None:
            zone = since = cand = None
        elif zone is None:
            zone, since, cand = z, first + k, None
        elif z == zone:
            cand = None
        elif z == cand:
            run += 1
            if run >= OF_ZONE_DWELL_SEC:
                zone, since, cand = z, cand_at, None
        else:
            cand, cand_at, run = z, first + k, 1
    return zone, since


def _flips(smoothed: list) -> int:
    """How many times the smoothed value changed sign (a zero or unknown value is skipped)."""
    signs = [s > 0 for s in smoothed if s is not None and s != 0]
    return sum(1 for a, b in itertools.pairwise(signs) if a != b)


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
    """Arithmetic about the displayed book: the flat shares one side would need to match the
    other."""
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
    """The Liquidity card's values, every venue and view: the headline (the smoothed percentage at
    the venue's end second: now while its book is live, else its last value's), its live value,
    zone and side word held OF_ZONE_DWELL_SEC, the seconds the zone has held (held_open: since
    before the values kept), the flat totals, the sentence, the touch, the flips in two minutes,
    and the 2m and 5m lean series. `points`: the lean series, (receive time, lean_point) oldest
    first; `ends`: venue -> its end time, None with no value."""
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
            sm = _smoothed(_standing(points, f"{v}|{view}", first, last))
            zone, since = _dwelled(sm, first)
            flips = _flips(sm[-(int(OF_TAPE_WINDOW_2M_SEC) + 1) :])
            bid, ask = snap.get("bid_total"), snap.get("ask_total")
            views[view] = {
                **{
                    k: snap.get(k)
                    for k in ("flat_pct", "bid_total", "ask_total", "difference", "total_depth")
                },
                "pct": sm[-1],
                "pct_text": percent_text(sm[-1]),
                "live_pct": snap.get("pct"),
                "live_text": percent_text(snap.get("pct")),
                "zone": zone,
                "side_word": ZONE_WORDS.get(zone) if zone else None,
                "held_sec": None if since is None else last - since,
                "held_open": since == first,
                "sentence": _sentence(zone, bid, ask),
                "divergence": _DIVERGENCE
                if view == "weighted" and _opposite(snap.get("pct"), snap.get("flat_pct"))
                else None,
                "flips_2m": flips,
                "flips_word": "CHOPPY" if flips >= OF_CHOPPY_FLIPS else "STEADY",
                "bid_text": shares_text(bid),
                "ask_text": shares_text(ask),
                "difference_text": shares_text(snap.get("difference")),
                "total_text": shares_text(snap.get("total_depth")),
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
            if "counted_twice" in snap:
                twice = snap["counted_twice"]
                views[view]["counted_twice"] = twice
                views[view]["counted_twice_text"] = (
                    f"Counted twice by summing both books: {shares_text(twice['bid'])} bid,"
                    f" {shares_text(twice['ask'])} ask shares"
                )
        touch = r["views"]["1"]["pct"] if "views" in r else None
        venues[v] = {
            **{
                k: r.get(k)
                for k in ("status", "book_time_ms", "touch_state", "books", "dedup_partial")
            },
            "touch_pct": touch,
            "touch_text": percent_text(touch),
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
        "weights": list(OF_LEVEL_WEIGHTS),
        "guide": READOUT_GUIDE,
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
    """
    Order Flow Engine — computes metrics from Schwab data using only
    identified field paths.
    """

    def compute(self, data: dict, *, now: float, ticker: str | None = None) -> dict:
        """The book microstructure and the tape flow of one symbol at `now` (epoch seconds);
        missing data yields None."""
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
