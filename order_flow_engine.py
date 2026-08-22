"""
order_flow_engine.py — Order Flow Engine
========================================
Computes order flow metrics from Schwab streaming/REST data using ONLY
fields from the identified Schwab field list.

Input: dict `data` with optional:
  - content.* (Level 2, tape, top of book)
  - quote (volume, bids, asks)
  - callExpDateMap / putExpDateMap (options flow)
  - candles (OHLCV; 1m bars for execution-aligned context and RVOL fallback)
  - screeners (volume context)
  - fundamental (avg volume for rvol)

Output: dict of order flow metrics for scoring and regime classification.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import math as _of_math

from math_exposure import MISSING_GREEK_SENTINEL

log = logging.getLogger(__name__)

# ── STACK-WIRE-5: named thresholds (Phase 6 ablation surface) ──
OF_COMPOSITE_WEIGHT_BOOK: float = 0.25
OF_COMPOSITE_WEIGHT_TAPE: float = 0.20
OF_COMPOSITE_WEIGHT_CUM_DELTA: float = 0.20
# NOTE (mission TRUTH_V1): the former OF_COMPOSITE_WEIGHT_ABSORPTION leg was REMOVED. Two defects:
# (1) `_compute_absorption` returns a NON-NEGATIVE volume/price-range density, so feeding it as a
#     SIGNED [-1,1] leg injected a near-constant BULLISH bias (magnitude used as direction); and
# (2) absorption is NOT_ADMITTED (proxy, dual-authored, no predictive evidence) — a signal with no
#     out-of-sample evidence may not influence the composite/verdict. Present-weight renormalization
#     means no re-weighting of the remaining legs is required.
OF_COMPOSITE_WEIGHT_OPTIONS: float = 0.15
# DEPRECATED (mission TRUTH_V1): the RVOL composite leg was removed. Relative volume is a
# participation MAGNITUDE, not a direction (high/low volume is not bullish/bearish) — the same
# magnitude-as-direction defect as the removed absorption leg. RVOL's conviction role stays in
# `_readiness`. These three constants are retained only as historical record, no longer a leg.
OF_COMPOSITE_WEIGHT_RVOL: float = 0.05
OF_COMPOSITE_MIN_LEGS: int = 2
OF_CLIP_LOW: float = -1.0
OF_CLIP_HIGH: float = 1.0
OF_RVOL_TERM_LOW: float = -0.5
OF_RVOL_TERM_HIGH: float = 0.5
OF_DIRECTION_BULLISH_THRESHOLD: float = 0.15
OF_DIRECTION_BEARISH_THRESHOLD: float = -0.15
OF_READINESS_STRONG_ABS: float = 0.25
OF_READINESS_MODERATE_ABS: float = 0.1
OF_RVOL_READINESS_OK: float = 1.2
OF_TAPE_WINDOW_30S_SEC: float = 30.0
OF_TAPE_WINDOW_2M_SEC: float = 120.0
OF_TAPE_WINDOW_5M_SEC: float = 300.0
OF_CUM_DELTA_NORM_DIVISOR: float = 10000.0
OF_OPTIONS_DELTA_NORM_DIVISOR: float = 50000.0
OF_ABSORPTION_PRICE_EPS: float = 0.01
# Book-depth ladder for _compute_book_imbalance: top of book, shallow, deep.
OF_BOOK_DEPTH_TOP: int = 1
OF_BOOK_DEPTH_SHALLOW: int = 3
OF_BOOK_DEPTH_DEEP: int = 5
# RVOL neutral center: RVOL = 1.0 means realized volume == average; the composite uses (rvol - center).
OF_RVOL_NEUTRAL_CENTER: float = 1.0
# Default minimum legs for _weighted_mean_present when callers omit min_present.
# (Composite scoring explicitly passes OF_COMPOSITE_MIN_LEGS; this is a safe-default fallback.)
OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT: int = 2

try:
    import numpy as np
    import pandas as pd
except ImportError:
    np = None  # type: ignore
    pd = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# DATA EXTRACTION — safe access to nested structures
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(val: Any) -> Optional[float]:
    """Convert to float; None if invalid. SINGLE SOURCE: delegates to the canonical
    numeric_contract.float_finite_or_none so a NaN/±inf field is rejected identically
    everywhere — this used to accept NaN/inf, counting a bad field the exposure engine
    drops (so the same contract diverged across order-flow vs exposures)."""
    from numeric_contract import float_finite_or_none
    return float_finite_or_none(val)


def _nonnegative_float(val: Any) -> Optional[float]:
    """Non-negative vendor quantity (size/volume): 0 valid, negatives+non-finite dropped.
    SINGLE SOURCE: delegates to numeric_contract.float_nonnegative_or_none so totalVolume
    reads identically here, in the exposure engine, and in the REST aggregation."""
    from numeric_contract import float_nonnegative_or_none
    return float_nonnegative_or_none(val)


def _safe_int(val: Any) -> Optional[int]:
    """Convert to int; None if invalid. SINGLE SOURCE: finite-gates through
    numeric_contract.float_finite_or_none first, so NaN/±inf are rejected — raw int()
    caught only TypeError/ValueError and leaked an uncaught OverflowError on +inf."""
    from numeric_contract import float_finite_or_none
    v = float_finite_or_none(val)
    return int(v) if v is not None else None


def _collect_from_nested(obj: Any, key: str, collector: list) -> None:
    """Recursively collect values for a key from nested dicts/lists."""
    if obj is None:
        return
    if isinstance(obj, dict):
        if key in obj:
            v = obj[key]
            if v is not None and not isinstance(v, (dict, list)):
                collector.append(v)
        for v in obj.values():
            _collect_from_nested(v, key, collector)
    elif isinstance(obj, list):
        for item in obj:
            _collect_from_nested(item, key, collector)


def _get_nested(obj: Any, *keys: str) -> Optional[Any]:
    """Get value at path keys[0].keys[1]...; handles dict and list (first item)."""
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and len(cur) > 0:
            cur = cur[0].get(k) if isinstance(cur[0], dict) else None
        else:
            return None
    return cur


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
            p = _safe_float(level.get("BID_PRICE"))
            v = _safe_float(level.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v))
        elif isinstance(level, list):
            for sub in level:
                if isinstance(sub, dict):
                    p = _safe_float(sub.get("BID_PRICE"))
                    v = _safe_float(sub.get("TOTAL_VOLUME"))
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
            p = _safe_float(level.get("ASK_PRICE"))
            v = _safe_float(level.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v))
        elif isinstance(level, list):
            for sub in level:
                if isinstance(sub, dict):
                    p = _safe_float(sub.get("ASK_PRICE"))
                    v = _safe_float(sub.get("TOTAL_VOLUME"))
                    if p is not None and v is not None:
                        out.append((p, v))
    return out


def _iter_tape_prints(content_items: list) -> list[dict]:
    """
    Extract tape prints (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS) from content.
    """
    out = []
    for c in content_items:
        if not isinstance(c, dict):
            continue
        lp = c.get("LAST_PRICE")
        ls = c.get("LAST_SIZE")
        tt = c.get("TRADE_TIME_MILLIS")
        if lp is not None or ls is not None or tt is not None:
            out.append({
                "price": _safe_float(lp),
                "size": _safe_int(ls),
                "time_millis": _safe_int(tt),
            })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BOOK METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _latest_book_snapshot(items: list) -> Optional[dict]:
    """Return the most recent content item that has both BIDS and ASKS."""
    for item in reversed(items):
        if isinstance(item, dict) and item.get("BIDS") and item.get("ASKS"):
            return item
    return None


def _book_side_depth_total(levels: list[tuple[float, float]], depth: int) -> Optional[float]:
    """Σ TOTAL_VOLUME over the best `depth` levels (best-first). None when the side has no
    levels. THE single depth-aggregation — `_compute_book_imbalance` and the microstructure
    depth ladder both call this, so the imbalance and the published side totals are the SAME
    computation, not two formulas that happen to agree."""
    if not levels:
        return None
    return sum(v for _, v in levels[:depth])


def _book_imbalance_from_totals(bid_total: Optional[float], ask_total: Optional[float]) -> Optional[float]:
    """THE single book-imbalance formula: (bid - ask) / (bid + ask). None if a side total is
    absent or the combined depth is non-positive. Shared by the engine score path and the
    microstructure payload so there is exactly one imbalance producer."""
    if bid_total is None or ask_total is None:
        return None
    total = bid_total + ask_total
    if total <= 0:
        return None
    return (bid_total - ask_total) / total


def _compute_book_imbalance(data: dict, depth: int) -> Optional[float]:
    """
    Book imbalance at given depth: (bid_vol - ask_vol) / (bid_vol + ask_vol).
    ONE CANONICAL PATH: reads the SAME `_extract_canonical_book` (sorted + validated levels)
    and the SAME `_book_side_depth_total` + `_book_imbalance_from_totals` helpers the
    microstructure depth ladder uses — it does not walk or sum the raw book on its own. The
    engine's compute() no longer calls this; it reads book_imbalance from the single
    compute_book_microstructure result. Kept for standalone/tests, consistent by construction.
    """
    cb = _extract_canonical_book(data)
    if not cb["has_book"]:
        return None
    return _book_imbalance_from_totals(
        _book_side_depth_total(cb["bid_levels"], depth),
        _book_side_depth_total(cb["ask_levels"], depth),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOP OF BOOK
# ─────────────────────────────────────────────────────────────────────────────

def _latest_quote_snapshot(items: list) -> Optional[dict]:
    """Return the most recent content item with BID_SIZE or ASK_SIZE (or BID_PRICE/ASK_PRICE)."""
    for item in reversed(items):
        if not isinstance(item, dict):
            continue
        if (
            item.get("BID_SIZE") is not None
            or item.get("ASK_SIZE") is not None
            or item.get("BID_PRICE") is not None
            or item.get("ASK_PRICE") is not None
        ):
            return item
    return None


def _compute_top_book_pressure(data: dict) -> tuple[Optional[float], Optional[str]]:
    """
    Top-of-book pressure: (bid_size - ask_size) / (bid_size + ask_size).
    Uses: content.*.BID_SIZE, ASK_SIZE or quote.bidSize, quote.askSize.
    Returns (pressure, source_tier).
    """
    items = _iter_content(data)
    bid_sz, ask_sz = None, None
    source_tier = "unavailable"
    snapshot = _latest_quote_snapshot(items)
    if snapshot:
        bid_sz = _safe_float(snapshot.get("BID_SIZE"))
        ask_sz = _safe_float(snapshot.get("ASK_SIZE"))
        if bid_sz is not None and ask_sz is not None:
            source_tier = "schwab_stream"
    if bid_sz is None or ask_sz is None:
        quote = data.get("quote") or {}
        extended = data.get("extended") or {}
        bid_sz = bid_sz or _safe_float(quote.get("bidSize")) or _safe_float(extended.get("bidSize"))
        ask_sz = ask_sz or _safe_float(quote.get("askSize")) or _safe_float(extended.get("askSize"))
        if bid_sz is not None and ask_sz is not None and source_tier == "unavailable":
            source_tier = "schwab_quote"
    if bid_sz is None or ask_sz is None:
        return None, "unavailable"
    total = bid_sz + ask_sz
    if total <= 0:
        return None, source_tier
    return (bid_sz - ask_sz) / total, source_tier


def _resolve_bid_ask_prices(data: dict) -> tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Resolve Schwab bid/ask prices and leaf provenance labels."""
    items = _iter_content(data)
    bid_p, ask_p = None, None
    bid_leaf, ask_leaf = None, None
    snapshot = _latest_quote_snapshot(items)
    if snapshot:
        bid_p = _safe_float(snapshot.get("BID_PRICE"))
        ask_p = _safe_float(snapshot.get("ASK_PRICE"))
        if bid_p is not None:
            bid_leaf = "streaming.BID_PRICE"
        if ask_p is not None:
            ask_leaf = "streaming.ASK_PRICE"
    if bid_p is None or ask_p is None:
        quote = data.get("quote") or {}
        extended = data.get("extended") or {}
        underlying = data.get("underlying") or {}
        if bid_p is None:
            bid_p = _safe_float(quote.get("bidPrice"))
            if bid_p is not None:
                bid_leaf = "quotes.quote.bidPrice"
        if bid_p is None:
            bid_p = _safe_float(extended.get("bidPrice"))
            if bid_p is not None:
                bid_leaf = "quotes.extended.bidPrice"
        if bid_p is None:
            bid_p = _safe_float(underlying.get("bid"))
            if bid_p is not None:
                bid_leaf = "chains.underlying.bid"
        if ask_p is None:
            ask_p = _safe_float(quote.get("askPrice"))
            if ask_p is not None:
                ask_leaf = "quotes.quote.askPrice"
        if ask_p is None:
            ask_p = _safe_float(extended.get("askPrice"))
            if ask_p is not None:
                ask_leaf = "quotes.extended.askPrice"
        if ask_p is None:
            ask_p = _safe_float(underlying.get("ask"))
            if ask_p is not None:
                ask_leaf = "chains.underlying.ask"
    return bid_p, ask_p, bid_leaf, ask_leaf


def _resolve_quote_mark(data: dict) -> tuple[Optional[float], Optional[str]]:
    """Schwab mark leaf for spread fraction denominator (no bid+ask midpoint synthesis)."""
    items = _iter_content(data)
    snapshot = _latest_quote_snapshot(items)
    if snapshot:
        mark_p = _safe_float(snapshot.get("MARK"))
        if mark_p is not None and mark_p > 0:
            return mark_p, "streaming.MARK"
    quote = data.get("quote") or {}
    extended = data.get("extended") or {}
    regular = data.get("regular") or {}
    for val, leaf in (
        (_safe_float(quote.get("mark")), "quotes.quote.mark"),
        (_safe_float(extended.get("mark")), "quotes.extended.mark"),
        (_safe_float(regular.get("mark")), "quotes.regular.mark"),
    ):
        if val is not None and val > 0:
            return val, leaf
    return None, None


def _compute_spread(data: dict) -> dict[str, Any]:
    """
    Bid-ask spread with explicit unit discipline: ``spread_pts`` (ask-bid points)
    and ``spread_frac`` (pts / midpoint). Never mix units on a single field.
    """
    bid_p, ask_p, bid_leaf, ask_leaf = _resolve_bid_ask_prices(data)
    if bid_p is None or ask_p is None:
        return {
            "spread_pts": None,
            "spread_frac": None,
            "spread_pts_source": None,
            "spread_frac_source": None,
            "spread_bid_leaf": bid_leaf,
            "spread_ask_leaf": ask_leaf,
        }
    spread_pts = round(ask_p - bid_p, 4)
    mark_p, mark_leaf = _resolve_quote_mark(data)
    spread_frac = None
    spread_frac_source = None
    if mark_p is not None and mark_p > 0:
        spread_frac = round(spread_pts / mark_p, 6)
        spread_frac_source = f"derived_bid_ask_fraction_schwab_mark_{mark_leaf or 'mark'}"
    leaf_tag = bid_leaf or ask_leaf or "schwab_bid_ask"
    return {
        "spread_pts": spread_pts,
        "spread_frac": spread_frac,
        "spread_pts_source": f"derived_bid_ask_pts_{leaf_tag}",
        "spread_frac_source": spread_frac_source,
        "spread_bid_leaf": bid_leaf,
        "spread_ask_leaf": ask_leaf,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL BOOK MICROSTRUCTURE  (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1)
# ─────────────────────────────────────────────────────────────────────────────
# ONE canonical book path. `_extract_canonical_book` walks + validates + SORTS the live
# book EXACTLY ONCE into a normalized state; every metric — and the engine's
# book_imbalance_1/3/5 and the institutional-flow consumer — is derived from that single
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
OF_MICRO_DEPTH_LADDER: tuple[int, ...] = (OF_BOOK_DEPTH_TOP, OF_BOOK_DEPTH_SHALLOW, OF_BOOK_DEPTH_DEEP)

#: Per-ticker carry cache: ticker -> (canonical_book_identity, structural_payload). Lets the route
#: serialize the engine's already-computed state for an UNCHANGED book instead of re-walking raw
#: data. Validity keys on the canonical book's CONTENT identity (see `_canonical_book_identity`),
#: NOT on BOOK_TIME alone — BOOK_TIME is not assumed unique, so a changed ladder under a repeated
#: BOOK_TIME must yield a different identity and force recompute.
_MICRO_STRUCTURAL_CACHE: dict[str, tuple[tuple, dict]] = {}


def _sorted_valid_levels(levels: list[tuple[float, float]], *, descending: bool) -> list[tuple[float, float]]:
    """Normalize a raw book side ONCE: drop invalid levels (non-positive price, negative or
    non-finite displayed size — the raw reader already drops non-finite via _safe_float), then
    SORT so `[:N]` is the true Top-N regardless of the vendor's array order: bids DESCENDING,
    asks ASCENDING."""
    valid = [(p, v) for (p, v) in levels if p is not None and v is not None and p > 0 and v >= 0]
    valid.sort(key=lambda pv: pv[0], reverse=descending)
    return valid


def _extract_canonical_book(data: dict) -> dict:
    """THE single extraction/normalization of the live book. Walks the content ONCE, validates
    and sorts both sides, and resolves the L1 top-of-book. Every downstream metric reads this
    result; nothing else re-walks the raw book."""
    items = _iter_content(data)
    snapshot = _latest_book_snapshot(items)
    quote_snap = _latest_quote_snapshot(items)

    bid, ask, bid_leaf, ask_leaf = _resolve_bid_ask_prices(data)
    bid_size = _safe_int(quote_snap.get("BID_SIZE")) if quote_snap else None
    ask_size = _safe_int(quote_snap.get("ASK_SIZE")) if quote_snap else None
    if bid_size is not None and bid_size < 0:   # reject invalid displayed size
        bid_size = None
    if ask_size is not None and ask_size < 0:
        ask_size = None

    bid_levels = _sorted_valid_levels(_iter_bids_levels(snapshot), descending=True) if snapshot else []
    ask_levels = _sorted_valid_levels(_iter_asks_levels(snapshot), descending=False) if snapshot else []
    mark, mark_leaf = _resolve_quote_mark(data)
    return {
        "has_book": snapshot is not None,
        "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size,
        "bid_leaf": bid_leaf, "ask_leaf": ask_leaf,
        "bid_levels": bid_levels, "ask_levels": ask_levels,
        "book_time_ms": _safe_float(snapshot.get("BOOK_TIME")) if snapshot else None,
        "mark": mark, "mark_leaf": mark_leaf,
    }


def _canonical_book_identity(cb: dict) -> tuple:
    """Hashable CONTENT identity of the canonical book — every field the structural state is
    derived from. The carry cache validates on THIS, never on BOOK_TIME alone: if the same ticker
    receives a changed ladder (or changed top-of-book / mark) under a repeated BOOK_TIME, the
    identity differs and `compute_book_microstructure` recomputes instead of serving stale state.
    BOOK_TIME is included, but only as one component — its uniqueness is not assumed."""
    return (
        cb["book_time_ms"],
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
        depth[str(n)] = {"bid_total": bt, "ask_total": at, "imbalance": _book_imbalance_from_totals(bt, at)}
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
            "book_source": "schwab_streaming_book" if cb["has_book"] else "unavailable",
            "top_of_book_bid_leaf": cb["bid_leaf"],
            "top_of_book_ask_leaf": cb["ask_leaf"],
        },
        "classification": {
            "top_of_book.bid": "NATIVE", "top_of_book.ask": "NATIVE",
            "top_of_book.bid_size": "NATIVE", "top_of_book.ask_size": "NATIVE",
            "mid": "DERIVED", "microprice": "DERIVED", "crossed": "DERIVED",
            "spread_pts": "DERIVED", "spread_frac": "DERIVED",
            "depth.*.bid_total": "DERIVED", "depth.*.ask_total": "DERIVED",
            "depth.*.imbalance": "DERIVED",
            "depth_pressure": "DERIVED", "book_slope": "DERIVED",
            "liquidity_concentration": "DERIVED",
            "wall_candidates": "DERIVED-HEURISTIC (size-outlier convention; see wall_method)",
            "ages.book_age_sec": "DERIVED", "ages.quote_age_sec": "DERIVED",
            "provenance.book_time_ms": "NATIVE", "provenance.exchange_quote_ts": "NATIVE",
            "provenance.server_received_ts": "DERIVED",
        },
        "deferred": [
            "aggressor_side (PROXY: needs trade-vs-quote classification history)",
            "cvd / cum_delta (PROXY: exists as cum_delta_proxy in the engine, tape-based)",
            "absorption / replenishment (PROXY: exists in the engine, 2-snapshot compare)",
            "iceberg / add-pull / institutional_flow (PROXY: no evidence base in this slice)",
        ],
    }


def compute_book_microstructure(data: dict, *, now_ts: Optional[float] = None,
                                ticker: Optional[str] = None) -> dict:
    """Canonical L2 book microstructure for one symbol — the ONE producer the engine's
    book_imbalance and the `/api/order-flow/microstructure` route both read. `data.content`
    carries the live streaming book + top-of-book (order_flow_live_state.get_content_for_symbol);
    `data.exchange_quote_ts` (optional) is the plane's exchange quote clock. The structural state
    is extracted/computed ONCE and memoized per (ticker, BOOK_TIME); a caller with the same
    unchanged book SERIALIZES the cached state instead of re-walking raw data. Only the age
    fields depend on `now` and are always stamped fresh. Fail-closed: no book snapshot -> status
    'no_book' with null metrics (no fabricated values)."""
    import time
    now = time.time() if now_ts is None else now_ts

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
    exch_ts = _safe_float(data.get("exchange_quote_ts"))
    payload = dict(structural)
    prov = dict(structural["provenance_structural"])
    prov["exchange_quote_ts"] = exch_ts             # NATIVE (plane quote clock)
    prov["server_received_ts"] = now                # DERIVED (server wall clock at serialization)
    payload.pop("provenance_structural", None)
    payload["provenance"] = prov
    payload["ages"] = {
        "book_age_sec": round(now - book_time_ms / 1000.0, 3) if book_time_ms else None,
        "quote_age_sec": round(now - exch_ts, 3) if exch_ts else None,
    }
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# TAPE METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _compute_tape_pressure(data: dict, window_sec: float) -> Optional[float]:
    """
    Tape pressure over a time window: sum(uptick_direction * size) / sum(size).
    Direction is inferred from LAST_PRICE movement vs the previous print's price.
    Uses: content.*.LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS.
    """
    prints = _iter_tape_prints(_iter_content(data))
    if not prints:
        return None
    now_ms = None
    for p in prints:
        t = p.get("time_millis")
        if t is not None:
            now_ms = t
            break
    if now_ms is None:
        now_ms = 0
    cutoff_ms = now_ms - int(window_sec * 1000)
    total_delta = 0.0
    total_sz = 0
    prev_price = None
    for p in sorted(prints, key=lambda x: x.get("time_millis") if x.get("time_millis") is not None else 0):
        t = p.get("time_millis")
        price = p.get("price")
        # Out-of-window prints still seed prev_price so the first in-window
        # print can be classified vs the most recent prior trade price.
        if t is not None and t < cutoff_ms:
            if price is not None:
                prev_price = price
            continue
        size = p.get("size")
        if size is None or size <= 0:
            # No size to add to volume, but the price is still a real trade
            # — keep it as the comparison anchor for the next sized print.
            if price is not None:
                prev_price = price
            continue
        if prev_price is not None and price is not None:
            if price > prev_price:
                total_delta += size
            elif price < prev_price:
                total_delta -= size
        total_sz += size
        if price is not None:
            prev_price = price
    if total_sz <= 0:
        return None
    return total_delta / total_sz if total_sz else None


# ─────────────────────────────────────────────────────────────────────────────
# CUMULATIVE DELTA PROXY
# ─────────────────────────────────────────────────────────────────────────────

def _compute_cum_delta_proxy(data: dict) -> Optional[float]:
    """
    Cumulative delta proxy from tape: sum of (direction * size) across prints.
    Direction is inferred from LAST_PRICE movement vs the previous print's price.
    Uses: content.*.LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS.
    Returns None when no print contributed a positive Schwab size.
    """
    prints = _iter_tape_prints(_iter_content(data))
    if not prints:
        return None
    total = 0.0
    saw_size = False
    prev_price = None
    for p in sorted(prints, key=lambda x: x.get("time_millis") if x.get("time_millis") is not None else 0):
        price = p.get("price")
        size = p.get("size")
        if size is None or size <= 0:
            # No size to count, but the price still anchors the next comparison.
            if price is not None:
                prev_price = price
            continue
        saw_size = True
        if prev_price is not None and price is not None:
            if price > prev_price:
                total += size
            elif price < prev_price:
                total -= size
        if price is not None:
            prev_price = price
    return total if saw_size else None


def _compute_cum_delta_slope(data: dict, window_sec: float = 60.0) -> Optional[float]:
    """
    Slope of cumulative delta over time (simple linear regression).
    Direction is inferred from LAST_PRICE movement vs the previous print's price.
    """
    prints = _iter_tape_prints(_iter_content(data))
    if len(prints) < 2:
        return None
    sorted_prints = sorted(
        [p for p in prints if p.get("time_millis") is not None],
        key=lambda x: x.get("time_millis") or 0,
    )
    if len(sorted_prints) < 2:
        return None
    cutoff = (sorted_prints[-1].get("time_millis") or 0) - int(window_sec * 1000)
    points = []
    cum = 0.0
    prev_price = None
    for p in sorted_prints:
        t = p.get("time_millis") or 0
        price = p.get("price")
        # Out-of-window prints still seed prev_price.
        if t < cutoff:
            if price is not None:
                prev_price = price
            continue
        size = p.get("size")
        if size is None or size <= 0:
            if price is not None:
                prev_price = price
            continue
        if prev_price is not None and price is not None:
            if price > prev_price:
                cum += size
            elif price < prev_price:
                cum -= size
        if price is not None:
            prev_price = price
        points.append((t / 1000.0, cum))
    if len(points) < 2:
        return None
    if np is not None:
        xs = np.array([p[0] for p in points])
        ys = np.array([p[1] for p in points])
        slope = float(np.polyfit(xs, ys, 1)[0])
        return slope
    # fallback: (last - first) / time_span
    t0, y0 = points[0]
    t1, y1 = points[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    return (y1 - y0) / dt


# ─────────────────────────────────────────────────────────────────────────────
# ABSORPTION / REPLENISHMENT
# ─────────────────────────────────────────────────────────────────────────────

def _earliest_book_snapshot(items: list) -> Optional[dict]:
    """Return the earliest content item that has both BIDS and ASKS."""
    for item in items:
        if isinstance(item, dict) and item.get("BIDS") and item.get("ASKS"):
            return item
    return None


# RETIRED (mission TRUTH_V1): _compute_absorption (P1) was a whole-buffer volume/price-range density
# mislabeled "absorption" — never level-based, no validity evidence. It was removed from the composite
# and its output keys (absorption_score/replenishment_score/absorption_direction) were dropped at the
# L1 boundary with zero executable consumers, so the function is deleted rather than kept as dead code.
# The model/UI-facing absorption_score is the separate institutional_behavior producer (P2), the sole
# remaining authority for that name (ONE FAUCET).


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONS FLOW
# ─────────────────────────────────────────────────────────────────────────────

def _iter_option_exp_levels(exp_map: dict) -> list[dict]:
    """Flatten callExpDateMap/putExpDateMap to list of strike-level data."""
    out = []
    if not isinstance(exp_map, dict):
        return out
    for exp_key, strikes in exp_map.items():
        if not isinstance(strikes, dict):
            continue
        for strike_key, opt in strikes.items():
            # Schwab: opt is list of contracts; take first. Also support single dict.
            if isinstance(opt, list) and len(opt) > 0:
                opt = opt[0] if isinstance(opt[0], dict) else None
            if not isinstance(opt, dict):
                continue
            d_raw = _safe_float(opt.get("delta"))
            d_val = d_raw if (d_raw is not None and d_raw != MISSING_GREEK_SENTINEL
                              and _of_math.isfinite(d_raw)) else None
            g_raw = _safe_float(opt.get("gamma"))
            g_val = g_raw if (g_raw is not None and g_raw != MISSING_GREEK_SENTINEL
                              and _of_math.isfinite(g_raw)) else None
            v_raw = _safe_float(opt.get("vega"))
            v_val = v_raw if (v_raw is not None and v_raw != MISSING_GREEK_SENTINEL
                              and _of_math.isfinite(v_raw)) else None
            t_raw = _safe_float(opt.get("theta"))
            t_val = t_raw if (t_raw is not None and t_raw != MISSING_GREEK_SENTINEL
                              and _of_math.isfinite(t_raw)) else None
            iv_raw = _safe_float(opt.get("volatility"))
            iv_val = iv_raw if (iv_raw is not None and iv_raw > 0
                                and iv_raw != MISSING_GREEK_SENTINEL
                                and _of_math.isfinite(iv_raw)) else None
            tt_raw = opt.get("tradeTimeInLong")
            tt_val: Optional[int] = None
            if tt_raw is not None and not isinstance(tt_raw, bool):
                try:
                    tt_f = float(tt_raw)
                    if _of_math.isfinite(tt_f):
                        tt_val = int(tt_f)
                except (TypeError, ValueError):
                    tt_val = None
            out.append({
                "exp": exp_key,
                "strike": _safe_float(opt.get("strikePrice")),
                "totalVolume": _safe_float(opt.get("totalVolume")),
                "openInterest": _safe_float(opt.get("openInterest")),
                "lastSize": _safe_float(opt.get("lastSize")),
                "bidSize": _safe_float(opt.get("bidSize")),
                "askSize": _safe_float(opt.get("askSize")),
                "bid": _safe_float(opt.get("bid")),
                "ask": _safe_float(opt.get("ask")),
                "mark": _safe_float(opt.get("mark")),
                "delta": d_val,
                "gamma": g_val,
                "vega": v_val,
                "theta": t_val,
                "volatility": iv_val,
                "daysToExpiration": _safe_int(opt.get("daysToExpiration")),
                "tradeTimeInLong": tt_val,
            })
    return out


def _option_contract_volume(c: dict, *, tick_mode: bool) -> tuple[Optional[float], Optional[str]]:
    """Schwab volume leaf: totalVolume default; lastSize only when tick_mode is explicit."""
    if tick_mode:
        v = _nonnegative_float(c.get("lastSize"))
        if v is not None:
            return v, "schwab_chain_lastSize_tick_mode"
        return None, None
    v = _nonnegative_float(c.get("totalVolume"))
    if v is not None:
        return v, "schwab_chain_totalVolume"
    return None, None


def _compute_options_flow(
    data: dict,
) -> tuple[Optional[float], Optional[str], Optional[float], Optional[float], Optional[str]]:
    """
    Options flow score, direction, call/put ratio, delta-weighted flow, volume_source.
    Uses: callExpDateMap.*, putExpDateMap.* (totalVolume; lastSize only in tick_mode).
    """
    tick_mode = bool(data.get("options_flow_tick_mode"))
    calls = _iter_option_exp_levels(data.get("callExpDateMap") or {})
    puts = _iter_option_exp_levels(data.get("putExpDateMap") or {})
    if not calls and not puts:
        return None, None, None, None, None
    call_vols: list[float] = []
    put_vols: list[float] = []
    volume_sources: set[str] = set()
    for c in calls:
        v, src = _option_contract_volume(c, tick_mode=tick_mode)
        if v is not None:
            call_vols.append(v)
            if src:
                volume_sources.add(src)
    for p in puts:
        v, src = _option_contract_volume(p, tick_mode=tick_mode)
        if v is not None:
            put_vols.append(v)
            if src:
                volume_sources.add(src)
    call_vol = sum(call_vols)
    put_vol = sum(put_vols)
    total_opt_vol = call_vol + put_vol
    if total_opt_vol <= 0:
        return None, None, None, None, None
    vol_source = next(iter(volume_sources)) if len(volume_sources) == 1 else (
        "mixed_schwab_chain_volume" if volume_sources else None
    )
    call_put_ratio = call_vol / (put_vol + 1e-9)
    delta_weighted = 0.0
    saw_delta_weight = False
    for c in calls:
        d = c.get("delta")
        v, _ = _option_contract_volume(c, tick_mode=tick_mode)
        if d is None or v is None:
            continue
        delta_weighted += d * v
        saw_delta_weight = True
    for p in puts:
        d = p.get("delta")
        v, _ = _option_contract_volume(p, tick_mode=tick_mode)
        if d is None or v is None:
            continue
        delta_weighted -= d * v
        saw_delta_weight = True
    options_flow_score = (call_vol - put_vol) / total_opt_vol
    direction = "call" if options_flow_score > 0 else ("put" if options_flow_score < 0 else "neutral")
    return (
        options_flow_score,
        direction,
        call_put_ratio,
        delta_weighted if saw_delta_weight else None,
        vol_source,
    )


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME CONTEXT (RVOL)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rvol(data: dict) -> tuple[Optional[float], Optional[str]]:
    """
    Relative volume: current volume / average volume.
    Uses: quote.totalVolume, extended.totalVolume, underlying.totalVolume,
          screeners.*.totalVolume, screeners.*.volume,
          fundamental.avg10DaysVolume, fundamental.avg1YearVolume,
          instruments.*.fundamental.avg10DaysVolume, etc.

    Returns (rvol, unavailable_reason). Never substitutes 1.0 when average volume
    is missing or invalid.
    """
    quote = data.get("quote") or {}
    extended = data.get("extended") or {}
    underlying = data.get("underlying") or {}
    current = _safe_float(quote.get("totalVolume"))
    if current is None:
        current = _safe_float(extended.get("totalVolume"))
    if current is None:
        current = _safe_float(underlying.get("totalVolume"))
    if current is None:
        screeners = data.get("screeners") or []
        if isinstance(screeners, list) and len(screeners) > 0:
            s = screeners[0] if isinstance(screeners[0], dict) else {}
            current = _safe_float(s.get("totalVolume")) or _safe_float(s.get("volume"))
    if current is None:
        return None, "current_volume_unavailable"
    fund = data.get("fundamental") or {}
    avg = _safe_float(fund.get("avg10DaysVolume"))
    if avg is None or avg <= 0:
        avg = _safe_float(fund.get("avg1YearVolume"))
    if avg is None or avg <= 0:
        inst = data.get("instruments") or {}
        if isinstance(inst, dict):
            for v in inst.values():
                f = (v or {}).get("fundamental") if isinstance(v, dict) else {}
                avg = _safe_float((f or {}).get("avg10DaysVolume")) or _safe_float((f or {}).get("avg1DayVolume")) or _safe_float((f or {}).get("vol10DayAvg")) or _safe_float((f or {}).get("vol1DayAvg"))  # external-key-ok: Schwab /quotes fundamental block (all four spellings present in schwab_field_dictionary.csv)
                if avg and avg > 0:
                    break
    if avg is None or avg <= 0:
        candles = data.get("candles") or []
        if isinstance(candles, list) and len(candles) > 0:
            vols = [c.get("volume") for c in candles if isinstance(c, dict) and c.get("volume") is not None]
            vols = [_safe_float(v) for v in vols if v is not None]
            if vols:
                avg = sum(vols) / len(vols)
    if avg is None or avg <= 0:
        return None, "avg_volume_unavailable"
    return current / avg, None


# ─────────────────────────────────────────────────────────────────────────────
# INSTITUTIONAL FLOW PROXY
# ─────────────────────────────────────────────────────────────────────────────

def _compute_institutional_flow_proxy(data: dict, *, book_imbalance_5: Optional[float] = None) -> Optional[float]:
    """
    Proxy for institutional flow: large trades + options activity + book imbalance.
    Uses: tape (large LAST_SIZE), options flow, book imbalance.
    ONE CANONICAL PATH: the deep book imbalance is READ from the single canonical
    microstructure result (passed by the engine as `book_imbalance_5`), not re-walked here.
    When called standalone without it, it falls back to the same canonical helper.
    """
    cum = _compute_cum_delta_proxy(data)
    book_imb = book_imbalance_5 if book_imbalance_5 is not None else _compute_book_imbalance(data, OF_BOOK_DEPTH_DEEP)
    opt_score, _, _, delta_w, _ = _compute_options_flow(data)
    components = []
    if cum is not None:
        components.append(max(-1, min(1, cum / OF_CUM_DELTA_NORM_DIVISOR)))
    if book_imb is not None:
        components.append(book_imb)
    if opt_score is not None:
        components.append(opt_score)
    if delta_w is not None and abs(delta_w) > 0:
        components.append(max(-1, min(1, delta_w / OF_OPTIONS_DELTA_NORM_DIVISOR)))
    if not components:
        return None
    return sum(components) / len(components)


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZATION & SCORING
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(val: Optional[float], low: float = -1.0, high: float = 1.0) -> float:
    """Clip and normalize to [-1, 1] range for scoring."""
    if val is None:
        return 0.0
    return max(low, min(high, float(val)))


def _weighted_mean_present(
    terms: list[tuple[float, Optional[float], float, float]],
    *,
    min_present: int = OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT,
) -> Optional[float]:
    """
    Weighted mean over present (non-None) legs; renormalize present weights to 1.0.
    Each term is (weight, raw_value, clip_low, clip_high). Returns None when fewer
    than min_present legs are available (no silent neutral mass from missing inputs).
    """
    present: list[tuple[float, float]] = []
    for weight, raw, low, high in terms:
        if raw is None:
            continue
        present.append((weight, _normalize(raw, low, high)))
    if len(present) < min_present:
        return None
    total_w = sum(w for w, _ in present)
    if total_w <= 0:
        return None
    return sum((w / total_w) * v for w, v in present)


def _compute_order_flow_score(
    book_imbalance: Optional[float],
    tape_pressure: Optional[float],
    cum_delta: Optional[float],
    options_flow: Optional[float],
) -> Optional[float]:
    """
    Composite score over present SIGNED, DIRECTIONAL legs only; None when fewer than
    OF_COMPOSITE_MIN_LEGS legs. Present weights renormalize to 1.0.
    TRUTH_V1: two magnitude-as-direction legs were removed — absorption (non-negative density)
    and RVOL (relative volume is a participation MAGNITUDE, not a direction: high/low volume is
    not bullish/bearish). RVOL's legitimate role is conviction and is retained in `_readiness`.
    NOTE: the surviving legs (book/tape/cum_delta/options) are directional PROXIES; the composite
    itself has NO out-of-sample validation (weights/thresholds were chosen, never fit), so it is
    NOT_ADMITTED as a decision authority — it is withheld from the call_engine vote and kept
    ADVISORY only.
    """
    return _weighted_mean_present(
        [
            (OF_COMPOSITE_WEIGHT_BOOK, book_imbalance, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_TAPE, tape_pressure, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_CUM_DELTA, cum_delta, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_OPTIONS, options_flow, OF_CLIP_LOW, OF_CLIP_HIGH),
        ],
        min_present=OF_COMPOSITE_MIN_LEGS,
    )


def _direction(score: Optional[float]) -> Optional[str]:
    """score > 0.15 → bullish, < -0.15 → bearish, else neutral; None when unavailable or exactly zero."""
    if score is None:
        return None
    if score == 0.0:
        return None
    if score > OF_DIRECTION_BULLISH_THRESHOLD:
        return "bullish"
    if score < OF_DIRECTION_BEARISH_THRESHOLD:
        return "bearish"
    return "neutral"


def _readiness(score: Optional[float], rvol: Optional[float]) -> str:
    """
    green: score strong and rvol > 1.2
    yellow: score moderate, or strong with rvol unknown/unconfirmed (rvol is None)
    red: weak score, or composite unavailable

    When rvol is None, strong readings downgrade to yellow (no fabricated rvol_ok).
    """
    if score is None:
        return "red"
    strong = abs(score) > OF_READINESS_STRONG_ABS
    moderate = OF_READINESS_MODERATE_ABS <= abs(score) <= OF_READINESS_STRONG_ABS
    if rvol is None:
        if strong or moderate:
            return "yellow"
        return "red"
    rvol_ok = rvol > OF_RVOL_READINESS_OK
    if strong and rvol_ok:
        return "green"
    if moderate or (strong and not rvol_ok):
        return "yellow"
    return "red"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class OrderFlowEngine:
    """
    Order Flow Engine — computes metrics from Schwab data using only
    identified field paths.
    """

    def compute(self, data: dict, *, ticker: Optional[str] = None) -> dict:
        """
        Compute all order flow metrics from the input data dict.
        Returns a dict with all metrics; missing data yields None where applicable.
        """
        if not isinstance(data, dict):
            return self._empty_result()

        # ONE CANONICAL BOOK PATH: extract/normalize the book ONCE via the single producer, and
        # READ book_imbalance_1/3/5 from that result. Nothing here re-walks or re-sums the raw
        # book. `ticker` lets the route serialize this same computed state (carry, not recompute).
        book_micro = compute_book_microstructure(data, ticker=ticker)
        book_imbalance_1 = book_micro["depth"]["1"]["imbalance"]
        book_imbalance_3 = book_micro["depth"]["3"]["imbalance"]
        book_imbalance_5 = book_micro["depth"]["5"]["imbalance"]

        # Top of book (quote.bidSize/askSize — always from REST). This is L1 SIZE pressure —
        # a DIFFERENT semantic than an L2 depth imbalance — so it is kept ONLY under its own
        # field `top_book_pressure` and is NEVER written into book_imbalance_1/3/5. When the
        # streaming book is absent those stay None: fail-closed, so the book dimension reads
        # ABSENT rather than a top-of-book proxy mislabeled as depth-5. (Removed the former REST
        # fallback `book_imbalance_5 = top_book_pressure`, which conflated the two under one name.)
        top_book_pressure, top_book_pressure_source = _compute_top_book_pressure(data)

        # Use 5-level for scoring when available (preserve measured 0.0 — FIND-OF1)
        book_for_score = next(
            (v for v in (book_imbalance_5, book_imbalance_3, book_imbalance_1) if v is not None),
            None,
        )
        spread_d = _compute_spread(data)
        spread_pts = spread_d.get("spread_pts")

        # Tape metrics
        tape_pressure_30s = _compute_tape_pressure(data, OF_TAPE_WINDOW_30S_SEC)
        tape_pressure_2m = _compute_tape_pressure(data, OF_TAPE_WINDOW_2M_SEC)
        tape_pressure_5m = _compute_tape_pressure(data, OF_TAPE_WINDOW_5M_SEC)
        tape_for_score = next(
            (v for v in (tape_pressure_2m, tape_pressure_30s, tape_pressure_5m) if v is not None),
            None,
        )

        # Cumulative delta
        cum_delta_proxy = _compute_cum_delta_proxy(data)
        cum_delta_slope = _compute_cum_delta_slope(data)

        # TRUTH_V1: the legacy _compute_absorption (P1) was RETIRED — it computed a volume/price-range
        # density (never level-based absorption), was removed from the composite, and its output keys
        # were dropped at the L1 boundary (zero executable consumers). The model/UI-facing
        # absorption_score is the separate institutional_behavior producer, not this one.

        # Options flow
        (
            options_flow_score,
            options_flow_direction,
            call_put_flow_ratio,
            delta_weighted_options_flow,
            options_flow_volume_source,
        ) = _compute_options_flow(data)

        # Volume context
        rvol, rvol_unavailable_reason = _compute_rvol(data)

        # Institutional proxy — reads the canonical deep book imbalance, does not re-walk.
        institutional_flow_proxy_score = _compute_institutional_flow_proxy(
            data, book_imbalance_5=book_imbalance_5)

        # Composite score and regime. absorption_score and rvol are intentionally NOT legs
        # (mission TRUTH_V1): both are non-directional MAGNITUDES (a density; relative volume).
        # absorption is still emitted below for advisory/PROXY display; rvol feeds `_readiness`
        # (its legitimate conviction role) below.
        order_flow_score = _compute_order_flow_score(
            book_for_score,
            tape_for_score,
            cum_delta_proxy,
            options_flow_score,
        )
        order_flow_direction = _direction(order_flow_score)
        order_flow_regime = order_flow_direction
        order_flow_readiness = (
            "red" if order_flow_score is None else _readiness(order_flow_score, rvol)
        )
        _order_flow_readiness_rvol = (
            "unavailable" if rvol is None and order_flow_score is not None else None
        )

        # Flow Verdict (composite headline) + field arrows/labels
        try:
            from math_exposure import (
                compute_order_flow_verdict,
                order_flow_score_label,
                order_flow_book_label,
                order_flow_opt_label,
                order_flow_field_arrow,
            )
            verdict_d = compute_order_flow_verdict(
                order_flow_score,
                book_imbalance_5,
                cum_delta_proxy,
                options_flow_score,
            )
            of_verdict = verdict_d["verdict"]
            of_verdict_color = verdict_d["verdict_color"]
            of_arrow = verdict_d["arrow"]
            of_agreement = verdict_d["agreement"]
            of_score_arrow = order_flow_field_arrow(order_flow_score)
            of_score_label = order_flow_score_label(order_flow_score)
            of_book_arrow = order_flow_field_arrow(book_imbalance_5, use_book=True)
            of_book_label = order_flow_book_label(book_imbalance_5)
            of_delta_arrow = order_flow_field_arrow(cum_delta_proxy)
            of_opt_arrow = order_flow_field_arrow(options_flow_score)
            of_opt_label = order_flow_opt_label(options_flow_score)
        except ImportError:
            of_verdict = None
            of_verdict_color = None
            of_arrow = None
            of_agreement = "unavailable"
            of_score_arrow = of_book_arrow = of_delta_arrow = of_opt_arrow = None
            of_score_label = of_book_label = of_opt_label = None

        return {
            "book_imbalance_1": book_imbalance_1,
            "book_imbalance_3": book_imbalance_3,
            "book_imbalance_5": book_imbalance_5,
            # Carry the single canonical microstructure state so the route serializes THIS
            # computed result (same book) rather than recomputing from raw data.
            "book_microstructure": book_micro,
            "top_book_pressure": top_book_pressure,
            "top_book_pressure_source": top_book_pressure_source,
            "spread": spread_pts,
            "spread_pts": spread_pts,
            "spread_frac": spread_d.get("spread_frac"),
            "spread_pts_source": spread_d.get("spread_pts_source"),
            "spread_frac_source": spread_d.get("spread_frac_source"),
            "spread_bid_leaf": spread_d.get("spread_bid_leaf"),
            "spread_ask_leaf": spread_d.get("spread_ask_leaf"),
            "tape_pressure_30s": tape_pressure_30s,
            "tape_pressure_2m": tape_pressure_2m,
            "tape_pressure_5m": tape_pressure_5m,
            "cum_delta_proxy": cum_delta_proxy,
            "cum_delta_slope": cum_delta_slope,
            "options_flow_score": options_flow_score,
            "options_flow_direction": options_flow_direction,
            "call_put_flow_ratio": call_put_flow_ratio,
            "delta_weighted_options_flow": delta_weighted_options_flow,
            "options_flow_volume_source": options_flow_volume_source,
            "rvol": rvol,
            "rvol_unavailable_reason": rvol_unavailable_reason,
            "institutional_flow_proxy_score": institutional_flow_proxy_score,
            "order_flow_score": order_flow_score,
            "order_flow_direction": order_flow_direction,
            "order_flow_regime": order_flow_regime,
            "order_flow_readiness": order_flow_readiness,
            "order_flow_verdict": of_verdict,
            "order_flow_verdict_color": of_verdict_color,
            "order_flow_arrow": of_arrow,
            "order_flow_agreement": of_agreement,
            "order_flow_score_arrow": of_score_arrow,
            "order_flow_score_label": of_score_label,
            "order_flow_book_arrow": of_book_arrow,
            "order_flow_book_label": of_book_label,
            "order_flow_delta_arrow": of_delta_arrow,
            "order_flow_opt_arrow": of_opt_arrow,
            "order_flow_opt_label": of_opt_label,
        }

    def _empty_result(self) -> dict:
        """Return template with all keys set to None or default."""
        return {
            "book_imbalance_1": None,
            "book_imbalance_3": None,
            "book_imbalance_5": None,
            "book_microstructure": None,
            "top_book_pressure": None,
            "top_book_pressure_source": None,
            "spread": None,
            "spread_pts": None,
            "spread_frac": None,
            "spread_pts_source": None,
            "spread_frac_source": None,
            "spread_bid_leaf": None,
            "spread_ask_leaf": None,
            "tape_pressure_30s": None,
            "tape_pressure_2m": None,
            "tape_pressure_5m": None,
            "cum_delta_proxy": None,
            "cum_delta_slope": None,
            "options_flow_score": None,
            "options_flow_direction": None,
            "call_put_flow_ratio": None,
            "delta_weighted_options_flow": None,
            "options_flow_volume_source": None,
            "rvol": None,
            "rvol_unavailable_reason": None,
            "institutional_flow_proxy_score": None,
            "order_flow_score": None,
            "order_flow_direction": None,
            "order_flow_regime": None,
            "order_flow_readiness": None,
            "order_flow_readiness_rvol": None,
            "order_flow_verdict": None,
            "order_flow_verdict_color": None,
            "order_flow_arrow": None,
            "order_flow_agreement": "unavailable",
            "order_flow_score_arrow": None,
            "order_flow_score_label": None,
            "order_flow_book_arrow": None,
            "order_flow_book_label": None,
            "order_flow_delta_arrow": None,
            "order_flow_opt_arrow": None,
            "order_flow_opt_label": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# TEST HARNESS
# ─────────────────────────────────────────────────────────────────────────────

def _mock_data() -> dict:
    """Build mock data structure for testing."""
    return {
        "content": [
            {
                "BIDS": [
                    {"BID_PRICE": 150.0, "TOTAL_VOLUME": 200, "NUM_BIDS": 5},
                    {"BID_PRICE": 149.9, "TOTAL_VOLUME": 150, "NUM_BIDS": 4},
                    {"BID_PRICE": 149.8, "TOTAL_VOLUME": 100, "NUM_BIDS": 3},
                ],
                "ASKS": [
                    {"ASK_PRICE": 150.1, "TOTAL_VOLUME": 80, "NUM_ASKS": 3},
                    {"ASK_PRICE": 150.2, "TOTAL_VOLUME": 120, "NUM_ASKS": 4},
                    {"ASK_PRICE": 150.3, "TOTAL_VOLUME": 90, "NUM_ASKS": 3},
                ],
                "BID_PRICE": 150.0,
                "ASK_PRICE": 150.1,
                "BID_SIZE": 50,
                "ASK_SIZE": 30,
                "LAST_PRICE": 150.05,
                "LAST_SIZE": 100,
                "TRADE_TIME_MILLIS": 1000000,
                "BOOK_TIME": 999000,
            },
            {
                "LAST_PRICE": 150.1,
                "LAST_SIZE": 75,
                "TRADE_TIME_MILLIS": 950000,
            },
            {
                "LAST_PRICE": 149.95,
                "LAST_SIZE": 50,
                "TRADE_TIME_MILLIS": 900000,
            },
        ],
        "quote": {
            "bidPrice": 150.0,
            "askPrice": 150.1,
            "bidSize": 50,
            "askSize": 30,
            "totalVolume": 1500000,
            "lastSize": 100,
            "tradeTime": 1000000,
            "quoteTime": 1000000,
        },
        "callExpDateMap": {
            "2025-03-21:1": {
                "150.0": {
                    "strikePrice": 150.0,
                    "totalVolume": 500,
                    "openInterest": 1000,
                    "lastSize": 25,
                    "bidSize": 10,
                    "askSize": 12,
                    "bid": 2.5,
                    "ask": 2.6,
                    "mark": 2.55,
                    "delta": 0.52,
                    "gamma": 0.05,
                    "vega": 0.1,
                    "theta": -0.02,
                    "volatility": 0.25,
                    "daysToExpiration": 11,
                    "tradeTimeInLong": 1000000,
                },
            },
        },
        "putExpDateMap": {
            "2025-03-21:1": {
                "150.0": {
                    "strikePrice": 150.0,
                    "totalVolume": 300,
                    "openInterest": 800,
                    "lastSize": 15,
                    "bidSize": 8,
                    "askSize": 10,
                    "bid": 2.4,
                    "ask": 2.5,
                    "mark": 2.45,
                    "delta": -0.48,
                    "gamma": 0.05,
                    "vega": 0.1,
                    "theta": -0.02,
                    "volatility": 0.26,
                    "daysToExpiration": 11,
                    "tradeTimeInLong": 999000,
                },
            },
        },
        "candles": [
            {"open": 149.5, "high": 150.2, "low": 149.4, "close": 150.0, "volume": 100000, "datetime": 990000},
            {"open": 149.0, "high": 149.8, "low": 148.9, "close": 149.5, "volume": 95000, "datetime": 980000},
        ],
        "fundamental": {"avg10DaysVolume": 800000},
        "screeners": [{"totalVolume": 1500000, "trades": 5000, "volume": 1500000}],
    }


def _main() -> None:
    """Run test harness."""
    engine = OrderFlowEngine()
    data = _mock_data()
    result = engine.compute(data)
    print("Order Flow Engine — Test Run")
    print("=" * 50)
    for k, v in result.items():
        if v is not None and isinstance(v, float) and not math.isnan(v):
            print(f"  {k}: {v:.4f}" if abs(v) < 1e4 else f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    print("=" * 50)
    print(f"  order_flow_score: {result['order_flow_score']:.4f}")
    print(f"  order_flow_direction: {result['order_flow_direction']}")
    print(f"  order_flow_readiness: {result['order_flow_readiness']}")


if __name__ == "__main__":
    _main()
