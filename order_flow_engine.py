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
OF_COMPOSITE_WEIGHT_ABSORPTION: float = 0.15
OF_COMPOSITE_WEIGHT_OPTIONS: float = 0.15
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


def _compute_book_imbalance(data: dict, depth: int) -> Optional[float]:
    """
    Book imbalance at given depth: (bid_vol - ask_vol) / (bid_vol + ask_vol).
    Uses: content.*.BIDS/ASKS with BID_PRICE, TOTAL_VOLUME, ASK_PRICE.
    """
    items = _iter_content(data)
    item = _latest_book_snapshot(items)
    if not item:
        return None
    bids = _iter_bids_levels(item)[:depth]
    asks = _iter_asks_levels(item)[:depth]
    if not bids or not asks:
        return None
    bid_vol = sum(v for _, v in bids)
    ask_vol = sum(v for _, v in asks)
    total = bid_vol + ask_vol
    if total <= 0:
        return None
    return (bid_vol - ask_vol) / total


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


def _compute_absorption(data: dict) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Absorption: large size at a level that doesn't move price.
    Replenishment: bid/ask depth rebuild after a fill.
    Uses: content.*.BIDS, ASKS (BID_VOLUME, ASK_VOLUME at price levels),
          content.*.LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS.
    """
    items = _iter_content(data)
    earlier = _earliest_book_snapshot(items)
    later = _latest_book_snapshot(items)
    if not earlier or not later or earlier is later:
        return None, None, None
    bids_earlier = sum(v for _, v in _iter_bids_levels(earlier))
    asks_earlier = sum(v for _, v in _iter_asks_levels(earlier))
    bids_later = sum(v for _, v in _iter_bids_levels(later))
    asks_later = sum(v for _, v in _iter_asks_levels(later))
    bid_change = bids_later - bids_earlier if bids_earlier else 0
    ask_change = asks_later - asks_earlier if asks_earlier else 0
    replenishment = (bid_change + ask_change) / 2.0 if (bids_earlier or asks_earlier) else 0.0
    # Absorption: when volume trades but price doesn't move much (simplified)
    prints = _iter_tape_prints(items)
    if not prints:
        return None, None, None
    total_sz = sum(p["size"] for p in prints if p.get("size") is not None and p["size"] > 0)
    prices = [p.get("price") for p in prints if p.get("price") is not None]
    price_range = max(prices) - min(prices) if len(prices) >= 2 else 0.0
    # absorption = high volume, low price movement
    absorption = (total_sz / (price_range + OF_ABSORPTION_PRICE_EPS)) if total_sz > 0 else 0.0
    direction = "bid" if bid_change > ask_change else ("ask" if ask_change > bid_change else "neutral")
    return absorption, replenishment, direction


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
                avg = _safe_float((f or {}).get("avg10DaysVolume")) or _safe_float((f or {}).get("avg1DayVolume")) or _safe_float((f or {}).get("vol10DayAvg")) or _safe_float((f or {}).get("vol1DayAvg"))
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

def _compute_institutional_flow_proxy(data: dict) -> Optional[float]:
    """
    Proxy for institutional flow: large trades + options activity + book imbalance.
    Uses: tape (large LAST_SIZE), options flow, book imbalance.
    """
    cum = _compute_cum_delta_proxy(data)
    book_imb = _compute_book_imbalance(data, OF_BOOK_DEPTH_DEEP)
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
    absorption: Optional[float],
    options_flow: Optional[float],
    rvol: Optional[float],
) -> Optional[float]:
    """
    Composite score over present legs only (FIND-OF3/OF4 / STACK-WIRE-5 weights).
    Uses OF_COMPOSITE_WEIGHT_* constants; None when fewer than OF_COMPOSITE_MIN_LEGS legs.
    """
    return _weighted_mean_present(
        [
            (OF_COMPOSITE_WEIGHT_BOOK, book_imbalance, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_TAPE, tape_pressure, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_CUM_DELTA, cum_delta, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_ABSORPTION, absorption, OF_CLIP_LOW, OF_CLIP_HIGH),
            (OF_COMPOSITE_WEIGHT_OPTIONS, options_flow, OF_CLIP_LOW, OF_CLIP_HIGH),
            (
                OF_COMPOSITE_WEIGHT_RVOL,
                (rvol - OF_RVOL_NEUTRAL_CENTER) if rvol is not None else None,
                OF_RVOL_TERM_LOW,
                OF_RVOL_TERM_HIGH,
            ),
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

    def compute(self, data: dict) -> dict:
        """
        Compute all order flow metrics from the input data dict.
        Returns a dict with all metrics; missing data yields None where applicable.
        """
        if not isinstance(data, dict):
            return self._empty_result()

        # Book metrics (from Level 2 BIDS/ASKS when streamer available)
        book_imbalance_1 = _compute_book_imbalance(data, OF_BOOK_DEPTH_TOP)
        book_imbalance_3 = _compute_book_imbalance(data, OF_BOOK_DEPTH_SHALLOW)
        book_imbalance_5 = _compute_book_imbalance(data, OF_BOOK_DEPTH_DEEP)

        # Top of book (quote.bidSize/askSize — always from REST)
        top_book_pressure, top_book_pressure_source = _compute_top_book_pressure(data)

        # REST fallback: when streamer has no depth, use top-of-book only
        # Store in same field so frontend renders without changes. Streamer takes precedence.
        if book_imbalance_5 is None and top_book_pressure is not None:
            book_imbalance_5 = top_book_pressure
            log.debug("Book Imb: REST proxy (top of book only)")

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

        # Absorption
        absorption_score, replenishment_score, absorption_direction = _compute_absorption(data)

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

        # Institutional proxy
        institutional_flow_proxy_score = _compute_institutional_flow_proxy(data)

        # Composite score and regime
        order_flow_score = _compute_order_flow_score(
            book_for_score,
            tape_for_score,
            cum_delta_proxy,
            absorption_score,
            options_flow_score,
            rvol,
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
            "absorption_score": absorption_score,
            "replenishment_score": replenishment_score,
            "replenishment_score_source": (
                "derived_bid_ask_depth_change_midpoint"
                if replenishment_score is not None
                else None
            ),
            "absorption_direction": absorption_direction,
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
            "absorption_score": None,
            "replenishment_score": None,
            "replenishment_score_source": None,
            "absorption_direction": None,
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
