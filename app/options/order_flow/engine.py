"""
app/options/order_flow/engine.py — Order Flow Engine
========================================
The book microstructure of one symbol, from Schwab streaming fields. No trade side is
inferred (docs/DATA_FLOW.md decision 9): Schwab supplies no aggressor.

Input: dict `data` with ``content`` (the streamed books), ``top`` (the live top of book, when
live) and ``book_live``.
"""

from __future__ import annotations

from typing import Any, Optional

from numeric_contract import float_finite_or_none, schwab_count, schwab_number


# Book-depth ladder: top of book, shallow, deep.
OF_BOOK_DEPTH_TOP: int = 1
OF_BOOK_DEPTH_SHALLOW: int = 3
OF_BOOK_DEPTH_DEEP: int = 5


# ─────────────────────────────────────────────────────────────────────────────
# DATA EXTRACTION — safe access to nested structures
# ─────────────────────────────────────────────────────────────────────────────

def _schwab_int(val: Any) -> Optional[int]:
    """A whole-number Schwab field (size, days, epoch ms) as sent."""
    v = schwab_number(val)
    return int(v) if v is not None else None






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


def _iter_bids_levels(content_item: dict) -> list[tuple[float, float]]:
    """
    Extract (price, total_volume) for each bid level from content.*.BIDS.
    Uses: BID_PRICE, TOTAL_VOLUME per level.
    """
    bids = content_item.get("BIDS")
    if not bids:
        return []
    out = []
    for level in (bids if isinstance(bids, list) else [bids]):
        if isinstance(level, dict):
            p = schwab_number(level.get("BID_PRICE"))
            v = schwab_count(level.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v))
        elif isinstance(level, list):
            for sub in level:
                if isinstance(sub, dict):
                    p = schwab_number(sub.get("BID_PRICE"))
                    v = schwab_count(sub.get("TOTAL_VOLUME"))
                    if p is not None and v is not None:
                        out.append((p, v))
    return out


def _iter_asks_levels(content_item: dict) -> list[tuple[float, float]]:
    """
    Extract (price, total_volume) for each ask level from content.*.ASKS.
    """
    asks = content_item.get("ASKS")
    if not asks:
        return []
    out = []
    for level in (asks if isinstance(asks, list) else [asks]):
        if isinstance(level, dict):
            p = schwab_number(level.get("ASK_PRICE"))
            v = schwab_count(level.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v))
        elif isinstance(level, list):
            for sub in level:
                if isinstance(sub, dict):
                    p = schwab_number(sub.get("ASK_PRICE"))
                    v = schwab_count(sub.get("TOTAL_VOLUME"))
                    if p is not None and v is not None:
                        out.append((p, v))
    return out




# ─────────────────────────────────────────────────────────────────────────────
# BOOK METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _latest_book_snapshot(items: list) -> Optional[dict]:
    """The newest book Schwab sent, whatever rests on it: an empty side is the book's state,
    never a reason to read an older book."""
    for item in reversed(items):
        if isinstance(item, dict) and item.get("BIDS") is not None and item.get("ASKS") is not None:
            return item
    return None


def _book_side_depth_total(levels: list[tuple[float, float]], depth: int) -> Optional[float]:
    """Σ TOTAL_VOLUME over the best `depth` levels (best-first). None when the side has no
    levels. The microstructure depth ladder's one depth aggregation."""
    if not levels:
        return None
    return sum(v for _, v in levels[:depth])


def _book_imbalance_from_totals(bid_total: Optional[float], ask_total: Optional[float]) -> Optional[float]:
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
    """The live top of book the caller supplies as ``data["top"]`` -- bid, ask, bid_size,
    ask_size, mark -- already judged live by the one live rule for its symbol
    (live_market_plane.quote_is_fresh for a ticker, feed_live_for for an option contract);
    absent when it is not live."""
    t = data.get("top")
    return t if isinstance(t, dict) else {}


def _top_book_pressure(bid_sz: Optional[float], ask_sz: Optional[float]) -> Optional[float]:
    """Top-of-book pressure: (bid_size - ask_size) / (bid_size + ask_size), streamed sizes."""
    if bid_sz is None or ask_sz is None:
        return None
    total = bid_sz + ask_sz
    if total <= 0:
        return None
    return (bid_sz - ask_sz) / total


def _resolve_bid_ask_prices(data: dict) -> tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Level-one BID_PRICE / ASK_PRICE and their leaf labels."""
    t = _top(data)
    bid_p, ask_p = t.get("bid"), t.get("ask")
    return (bid_p, ask_p, "streaming.BID_PRICE" if bid_p is not None else None,
            "streaming.ASK_PRICE" if ask_p is not None else None)


def _resolve_quote_mark(data: dict) -> tuple[Optional[float], Optional[str]]:
    """Streamed MARK, the spread-fraction denominator (a MARK of 0 divides nothing)."""
    mark_p = _top(data).get("mark")
    if mark_p is not None and mark_p > 0:
        return mark_p, "streaming.MARK"
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL BOOK MICROSTRUCTURE  (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1)
# ─────────────────────────────────────────────────────────────────────────────
# One book path. `_extract_canonical_book` walks, validates and sorts the newest book once;
# every metric is derived from that result. `compute_book_microstructure` carries the
# structural state while the book's content is unchanged. Every field is classified NATIVE (a
# Schwab wire field) or DERIVED (a function of NATIVE fields). The book's state only: no trade
# side, delta or absorption, and no composite score.

#: HEURISTIC only: a displayed level is a WALL CANDIDATE when its size is at least this multiple
#: of the MEDIAN level size across the ladder. A relative size-outlier convention (tunable, and
#: blind to hidden/reserve size) — NOT an objectively-known liquidity wall. Surfaced with each
#: candidate's `median_mult` and a self-describing `wall_method` block so the API never asserts
#: a proven wall. magic-threshold-ok: relative (× median), carries its method in the payload.
OF_BOOK_WALL_MEDIAN_MULT: float = 3.0

#: Depth ladder for the canonical depth totals/imbalance — the existing 1/3/5 ladder.
OF_MICRO_DEPTH_LADDER: tuple[int, ...] = (OF_BOOK_DEPTH_TOP, OF_BOOK_DEPTH_SHALLOW, OF_BOOK_DEPTH_DEEP)

#: Per-ticker carry cache: ticker -> (canonical_book_identity, structural_payload). Lets the route
#: serialize the engine's already-computed state for an UNCHANGED book instead of re-walking raw
#: data. Validity keys on the canonical book's CONTENT identity (see `_canonical_book_identity`),
#: NOT on BOOK_TIME alone — BOOK_TIME is not assumed unique, so a changed ladder under a repeated
#: BOOK_TIME must yield a different identity and force recompute.
_MICRO_STRUCTURAL_CACHE: dict[str, tuple[tuple, dict]] = {}


def _sorted_valid_levels(levels: list[tuple[float, float]], *, descending: bool) -> list[tuple[float, float]]:
    """Normalize a raw book side ONCE: drop invalid levels (non-positive price, negative or
    non-finite displayed size — the raw reader already drops non-finite via schwab_count), then
    SORT so `[:N]` is the true Top-N regardless of the vendor's array order: bids DESCENDING,
    asks ASCENDING."""
    valid = [(p, v) for (p, v) in levels if p is not None and v is not None and p > 0 and v >= 0]
    valid.sort(key=lambda pv: pv[0], reverse=descending)
    return valid


def _extract_canonical_book(data: dict) -> dict:
    """THE single extraction/normalization of the live book. Walks the content ONCE, validates
    and sorts both sides, and carries the live top of book (``data["top"]``). Every downstream
    metric reads this result; nothing else re-walks the raw book."""
    snapshot = _latest_book_snapshot(_iter_content(data))
    bid, ask, bid_leaf, ask_leaf = _resolve_bid_ask_prices(data)
    t = _top(data)
    bid_size = _schwab_int(t.get("bid_size"))
    ask_size = _schwab_int(t.get("ask_size"))

    bid_levels = _sorted_valid_levels(_iter_bids_levels(snapshot), descending=True) if snapshot else []
    ask_levels = _sorted_valid_levels(_iter_asks_levels(snapshot), descending=False) if snapshot else []
    mark, mark_leaf = _resolve_quote_mark(data)
    return {
        # a book with nothing resting on either side is no book to measure
        "has_book": bool(bid_levels or ask_levels),
        "venue": snapshot.get("SERVICE") if snapshot else None,
        "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size,
        "bid_leaf": bid_leaf, "ask_leaf": ask_leaf,
        "bid_levels": bid_levels, "ask_levels": ask_levels,
        "book_time_ms": schwab_number(snapshot.get("BOOK_TIME")) if snapshot else None,
        "mark": mark, "mark_leaf": mark_leaf,
    }


def _canonical_book_identity(cb: dict) -> tuple:
    """Hashable CONTENT identity of the canonical book — every field the structural state is
    derived from. The carry cache validates on THIS, never on BOOK_TIME alone: if the same ticker
    receives a changed ladder (or changed top-of-book / mark) under a repeated BOOK_TIME, the
    identity differs and `compute_book_microstructure` recomputes instead of serving stale state.
    BOOK_TIME is included, but only as one component — its uniqueness is not assumed."""
    return (
        cb["book_time_ms"], cb["venue"],
        cb["bid"], cb["ask"], cb["bid_size"], cb["ask_size"], cb["mark"],
        tuple(cb["bid_levels"]), tuple(cb["ask_levels"]),
    )


def _microprice(bid: Optional[float], ask: Optional[float],
                bid_size: Optional[float], ask_size: Optional[float]) -> Optional[float]:
    """Size-weighted top-of-book fair price:
        microprice = (bid·ask_size + ask·bid_size) / (bid_size + ask_size)
    Each price is weighted by the OPPOSITE side's size, so heavier bid size pulls the fair
    price toward the ask (imminent buy pressure). DERIVED. Fail-closed → None on any missing
    leg, a non-positive price, a negative size, zero total size, or a CROSSED book (bid > ask),
    where a size-weighted average between the quotes is meaningless."""
    if bid is None or ask is None or bid_size is None or ask_size is None:
        return None
    if bid <= 0 or ask <= 0 or bid_size < 0 or ask_size < 0:
        return None
    if bid > ask:                      # crossed / inverted book → invalid microstructure input
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


def _book_slope(levels: list[tuple[float, float]], depth: int, total: Optional[float]) -> Optional[float]:
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


def _book_concentration(levels: list[tuple[float, float]], total: Optional[float]) -> Optional[float]:
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
            out.append({"side": side, "price": price, "volume": vol,
                        "median_mult": round(vol / median, 2)})
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

    # Crossed book WITHHOLDS both mid and microprice (a mid between inverted quotes is meaningless).
    mid = (bid + ask) / 2.0 if (have_quotes and not crossed) else None
    microprice = _microprice(bid, ask, bid_size, ask_size)  # also self-rejects crossed
    spread_pts = round(ask - bid, 4) if have_quotes else None
    mark = cb["mark"]
    spread_frac = round(spread_pts / mark, 6) if (spread_pts is not None and mark and mark > 0) else None

    # Depth ladder — totals aggregated ONCE per (side, depth); imbalance, slope and concentration
    # all reuse these SAME canonical totals. One aggregation authority (`_book_side_depth_total`).
    depth: dict[str, dict] = {}
    totals: dict[int, tuple[Optional[float], Optional[float]]] = {}
    for n in OF_MICRO_DEPTH_LADDER:
        bt = _book_side_depth_total(bid_levels, n)
        at = _book_side_depth_total(ask_levels, n)
        totals[n] = (bt, at)
        imb = _book_imbalance_from_totals(bt, at)
        # the heavier side, by the imbalance's sign (no threshold): what every panel labels
        side = None if imb is None else "BID" if imb > 0 else "ASK" if imb < 0 else "EVEN"
        depth[str(n)] = {"bid_total": bt, "ask_total": at, "imbalance": imb, "side": side,
                         # the imbalance as the screen prints it: "+20.0%"
                         "imbalance_disp": None if imb is None else f"{imb:+.1%}"}
    deep_bt, deep_at = totals[OF_BOOK_DEPTH_DEEP]

    return {
        "status": "ok" if cb["has_book"] else "no_book",
        "top_of_book": {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size},
        "crossed": crossed,
        "mid": mid,
        "microprice": microprice,
        "spread_pts": spread_pts,
        "spread_frac": spread_frac,
        # top-of-book SIZE pressure (streamed BID_SIZE / ASK_SIZE), not a depth imbalance
        "top_book_pressure": _top_book_pressure(bid_size, ask_size),
        "depth": depth,
        "depth_pressure": {
            "bid": _book_pressure_curve(bid_levels, OF_BOOK_DEPTH_DEEP),
            "ask": _book_pressure_curve(ask_levels, OF_BOOK_DEPTH_DEEP),
        },
        "book_slope": {"bid": _book_slope(bid_levels, OF_BOOK_DEPTH_DEEP, deep_bt),
                       "ask": _book_slope(ask_levels, OF_BOOK_DEPTH_DEEP, deep_at)},
        "liquidity_concentration": {"bid": _book_concentration(bid_levels, deep_bt),
                                    "ask": _book_concentration(ask_levels, deep_at)},
        "wall_candidates": (_book_wall_candidates(bid_levels, "bid", OF_BOOK_DEPTH_DEEP)
                            + _book_wall_candidates(ask_levels, "ask", OF_BOOK_DEPTH_DEEP)),
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
            "top_of_book.bid": "NATIVE", "top_of_book.ask": "NATIVE",
            "top_of_book.bid_size": "NATIVE", "top_of_book.ask_size": "NATIVE",
            "mid": "DERIVED", "microprice": "DERIVED", "crossed": "DERIVED",
            "spread_pts": "DERIVED", "spread_frac": "DERIVED", "top_book_pressure": "DERIVED",
            "depth.*.bid_total": "DERIVED", "depth.*.ask_total": "DERIVED",
            "depth.*.imbalance": "DERIVED",
            "depth_pressure": "DERIVED", "book_slope": "DERIVED",
            "liquidity_concentration": "DERIVED",
            "wall_candidates": "DERIVED-HEURISTIC (size-outlier convention; see wall_method)",
            "ages.book_age_sec": "DERIVED", "ages.quote_age_sec": "DERIVED",
            "ages.book_stale": "DERIVED",
            "provenance.book_time_ms": "NATIVE", "provenance.exchange_quote_ts": "NATIVE",
            "provenance.server_received_ts": "DERIVED",
        },
    }


def compute_book_microstructure(data: dict, *, now_ts: float,
                                ticker: Optional[str] = None) -> dict:
    """Canonical L2 book microstructure for one symbol at `now_ts` (epoch seconds) — the ONE
    producer the equity and the option microstructure routes read. `data.content`
    carries the symbol's streamed books (app.options.order_flow.state.get_content_for_symbol);
    `data.exchange_quote_ts` (optional) is the plane's exchange quote clock; `data.book_live` is
    the live rule's answer for the book's service (absent: not live). The structural state
    is extracted/computed ONCE and memoized per (ticker, BOOK_TIME); a caller with the same
    unchanged book SERIALIZES the cached state instead of re-walking raw data. Only the age
    fields depend on `now` and are always stamped fresh. Fail-closed: no book snapshot -> status
    'no_book' with null metrics (no fabricated values)."""
    now = now_ts
    cb = _extract_canonical_book(data)
    book_time_ms = cb["book_time_ms"]

    # Carry only when the canonical book CONTENT is byte-for-byte identical — not merely the same
    # BOOK_TIME. A changed ladder under a repeated BOOK_TIME has a different identity and recomputes.
    identity = _canonical_book_identity(cb)
    cached = _MICRO_STRUCTURAL_CACHE.get(ticker) if ticker else None
    if cached is not None and cached[0] == identity:
        structural = cached[1]                       # carry: identical canonical book, no recompute
    else:
        structural = _microstructure_structural(cb)
        if ticker:
            _MICRO_STRUCTURAL_CACHE[ticker] = (identity, structural)

    # Ages + per-serialization stamps are the only wall-clock-dependent fields.
    exch_ts = float_finite_or_none(data.get("exchange_quote_ts"))
    payload = dict(structural)
    prov = dict(structural["provenance_structural"])
    prov["exchange_quote_ts"] = exch_ts             # NATIVE (plane quote clock)
    prov["server_received_ts"] = now                # DERIVED (server wall clock at serialization)
    payload.pop("provenance_structural", None)
    payload["provenance"] = prov
    book_age_sec = round(now - book_time_ms / 1000.0, 3) if book_time_ms else None
    payload["ages"] = {
        "book_age_sec": book_age_sec,
        "quote_age_sec": round(now - exch_ts, 3) if exch_ts else None,
        # the live rule (live_market_plane.feed_live_for on the book's service), which the caller
        # passes as data["book_live"]; None with no book
        "book_stale": None if book_age_sec is None else data.get("book_live") is not True,
    }
    return payload
