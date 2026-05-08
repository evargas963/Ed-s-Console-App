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

log = logging.getLogger(__name__)

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
    """Convert to float; return None if invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _nonnegative_float(val: Any) -> Optional[float]:
    out = _safe_float(val)
    if out is None or out < 0:
        return None
    return out


def _safe_int(val: Any) -> Optional[int]:
    """Convert to int; return None if invalid."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


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
    Extract tape prints (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS, TICK) from content.
    """
    out = []
    for c in content_items:
        if not isinstance(c, dict):
            continue
        lp = c.get("LAST_PRICE")
        ls = c.get("LAST_SIZE")
        tt = c.get("TRADE_TIME_MILLIS")
        tick = c.get("TICK")
        tick_amt = c.get("TICK_AMOUNT")
        if lp is not None or ls is not None or tt is not None:
            size = _safe_int(ls)
            if size is None:
                size = _safe_int(tick_amt)
            out.append({
                "price": _safe_float(lp),
                "size": size,
                "time_millis": _safe_int(tt),
                "tick": tick,
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
        if isinstance(item, dict) and (item.get("BID_SIZE") is not None or item.get("BID_PRICE") is not None or item.get("bidSize") is not None):
            return item
    return None


def _compute_top_book_pressure(data: dict) -> Optional[float]:
    """
    Top-of-book pressure: (bid_size - ask_size) / (bid_size + ask_size).
    Uses: content.*.BID_SIZE, ASK_SIZE or quote.bidSize, quote.askSize.
    """
    items = _iter_content(data)
    bid_sz, ask_sz = None, None
    snapshot = _latest_quote_snapshot(items)
    if snapshot:
        bid_sz = _safe_float(snapshot.get("BID_SIZE"))
        ask_sz = _safe_float(snapshot.get("ASK_SIZE"))
    if bid_sz is None or ask_sz is None:
        quote = data.get("quote") or {}
        extended = data.get("extended") or {}
        bid_sz = bid_sz or _safe_float(quote.get("bidSize")) or _safe_float(extended.get("bidSize"))
        ask_sz = ask_sz or _safe_float(quote.get("askSize")) or _safe_float(extended.get("askSize"))
    if bid_sz is None or ask_sz is None:
        return None
    total = bid_sz + ask_sz
    if total <= 0:
        return None
    return (bid_sz - ask_sz) / total


def _compute_spread(data: dict) -> Optional[float]:
    """
    Bid-ask spread: ask_price - bid_price.
    Uses: content.*.BID_PRICE, ASK_PRICE or quote.bidPrice, quote.askPrice.
    """
    items = _iter_content(data)
    bid_p, ask_p = None, None
    snapshot = _latest_quote_snapshot(items)
    if snapshot:
        bid_p = _safe_float(snapshot.get("BID_PRICE"))
        ask_p = _safe_float(snapshot.get("ASK_PRICE"))
    if bid_p is None or ask_p is None:
        quote = data.get("quote") or {}
        extended = data.get("extended") or {}
        underlying = data.get("underlying") or {}
        bid_p = bid_p or _safe_float(quote.get("bidPrice")) or _safe_float(extended.get("bidPrice")) or _safe_float(underlying.get("bid"))
        ask_p = ask_p or _safe_float(quote.get("askPrice")) or _safe_float(extended.get("askPrice")) or _safe_float(underlying.get("ask"))
    if bid_p is None or ask_p is None:
        return None
    return ask_p - bid_p


# ─────────────────────────────────────────────────────────────────────────────
# TAPE METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _compute_tape_pressure(data: dict, window_sec: float) -> Optional[float]:
    """
    Tape pressure over a time window: sum(tick_direction * size) / sum(size).
    Uses: content.*.LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS, TICK, TICK_AMOUNT.
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
    for p in sorted(prints, key=lambda x: x.get("time_millis") or 0):
        t = p.get("time_millis")
        if t is not None and t < cutoff_ms:
            continue
        price = p.get("price")
        size = p.get("size")
        if size is None or size <= 0:
            continue
        tick = p.get("tick")
        if tick == "Up" or tick == "UpTick":
            total_delta += size
        elif tick == "Down" or tick == "DownTick":
            total_delta -= size
        elif prev_price is not None and price is not None:
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
    Uses: content.*.LAST_SIZE, TICK, TICK_AMOUNT.
    """
    prints = _iter_tape_prints(_iter_content(data))
    if not prints:
        return None
    total = 0.0
    saw_size = False
    for p in prints:
        size = p.get("size")
        if size is None or size <= 0:
            continue
        saw_size = True
        tick = p.get("tick")
        if tick == "Up" or tick == "UpTick":
            total += size
        elif tick == "Down" or tick == "DownTick":
            total -= size
    return total if saw_size else None


def _compute_cum_delta_slope(data: dict, window_sec: float = 60.0) -> Optional[float]:
    """
    Slope of cumulative delta over time (simple linear regression).
    """
    prints = _iter_tape_prints(_iter_content(data))
    if len(prints) < 2:
        return None
    # sort by time, compute running cum_delta, then slope
    sorted_prints = sorted(
        [p for p in prints if p.get("time_millis") is not None],
        key=lambda x: x.get("time_millis") or 0,
    )
    if len(sorted_prints) < 2:
        return None
    cutoff = (sorted_prints[-1].get("time_millis") or 0) - int(window_sec * 1000)
    points = []
    cum = 0.0
    for p in sorted_prints:
        t = p.get("time_millis") or 0
        if t < cutoff:
            continue
        size = p.get("size")
        if size is None or size <= 0:
            continue
        tick = p.get("tick")
        if tick in ("Up", "UpTick"):
            cum += size
        elif tick in ("Down", "DownTick"):
            cum -= size
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
    absorption = (total_sz / (price_range + 0.01)) if total_sz > 0 else 0.0
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
            if isinstance(opt, dict):
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
                    "delta": _safe_float(opt.get("delta")),
                    "gamma": _safe_float(opt.get("gamma")),
                    "vega": _safe_float(opt.get("vega")),
                    "theta": _safe_float(opt.get("theta")),
                    "volatility": _safe_float(opt.get("volatility")),
                    "daysToExpiration": _safe_int(opt.get("daysToExpiration")),
                    "tradeTimeInLong": _safe_int(opt.get("tradeTimeInLong")),
                })
    return out


def _compute_options_flow(data: dict) -> tuple[Optional[float], Optional[str], Optional[float], Optional[float]]:
    """
    Options flow score, direction, call/put ratio, delta-weighted flow.
    Uses: callExpDateMap.*, putExpDateMap.* (totalVolume, bid, ask, delta, etc.)
    """
    calls = _iter_option_exp_levels(data.get("callExpDateMap") or {})
    puts = _iter_option_exp_levels(data.get("putExpDateMap") or {})
    if not calls and not puts:
        return None, None, None, None
    call_vols = [_nonnegative_float(c.get("totalVolume")) for c in calls]
    put_vols = [_nonnegative_float(p.get("totalVolume")) for p in puts]
    call_vol = sum(v for v in call_vols if v is not None)
    put_vol = sum(v for v in put_vols if v is not None)
    total_opt_vol = call_vol + put_vol
    if total_opt_vol <= 0:
        return None, None, None, None
    call_put_ratio = call_vol / (put_vol + 1e-9)
    delta_weighted = 0.0
    saw_delta_weight = False
    for c in calls:
        d = _safe_float(c.get("delta"))
        v = _nonnegative_float(c.get("totalVolume"))
        if d is None or v is None:
            continue
        delta_weighted += d * v
        saw_delta_weight = True
    for p in puts:
        d = _safe_float(p.get("delta"))
        v = _nonnegative_float(p.get("totalVolume"))
        if d is None or v is None:
            continue
        delta_weighted -= d * v  # put delta negative for directional
        saw_delta_weight = True
    options_flow_score = (call_vol - put_vol) / total_opt_vol
    direction = "call" if options_flow_score > 0 else ("put" if options_flow_score < 0 else "neutral")
    return options_flow_score, direction, call_put_ratio, delta_weighted if saw_delta_weight else None


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME CONTEXT (RVOL)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rvol(data: dict) -> Optional[float]:
    """
    Relative volume: current volume / average volume.
    Uses: quote.totalVolume, extended.totalVolume, underlying.totalVolume,
          screeners.*.totalVolume, screeners.*.volume,
          fundamental.avg10DaysVolume, fundamental.avg1YearVolume,
          instruments.*.fundamental.avg10DaysVolume, etc.
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
        return None
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
        return 1.0  # no avg available, assume normal
    return current / avg


# ─────────────────────────────────────────────────────────────────────────────
# INSTITUTIONAL FLOW PROXY
# ─────────────────────────────────────────────────────────────────────────────

def _compute_institutional_flow_proxy(data: dict) -> Optional[float]:
    """
    Proxy for institutional flow: large trades + options activity + book imbalance.
    Uses: tape (large LAST_SIZE), options flow, book imbalance.
    """
    cum = _compute_cum_delta_proxy(data)
    book_imb = _compute_book_imbalance(data, 5)
    opt_score, _, _, delta_w = _compute_options_flow(data)
    components = []
    if cum is not None:
        components.append(max(-1, min(1, cum / 10000.0)))  # normalize
    if book_imb is not None:
        components.append(book_imb)
    if opt_score is not None:
        components.append(opt_score)
    if delta_w is not None and abs(delta_w) > 0:
        components.append(max(-1, min(1, delta_w / 50000.0)))
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


def _compute_order_flow_score(
    book_imbalance: Optional[float],
    tape_pressure: Optional[float],
    cum_delta: Optional[float],
    absorption: Optional[float],
    options_flow: Optional[float],
    rvol: Optional[float],
) -> float:
    """
    Composite score:
      0.25 * book_imbalance + 0.20 * tape_pressure + 0.20 * cum_delta +
      0.15 * absorption + 0.15 * options_flow + 0.05 * rvol
    """
    n_book = _normalize(book_imbalance)
    n_tape = _normalize(tape_pressure)
    n_delta = _normalize(cum_delta, -1, 1)
    n_abs = _normalize(absorption)
    n_opt = _normalize(options_flow)
    n_rvol = _normalize((rvol or 1.0) - 1.0, -0.5, 0.5)
    return (
        0.25 * n_book
        + 0.20 * n_tape
        + 0.20 * n_delta
        + 0.15 * n_abs
        + 0.15 * n_opt
        + 0.05 * n_rvol
    )


def _direction(score: float) -> str:
    """score > 0.15 → bullish, < -0.15 → bearish, else neutral."""
    if score > 0.15:
        return "bullish"
    if score < -0.15:
        return "bearish"
    return "neutral"


def _readiness(score: float, rvol: Optional[float]) -> str:
    """
    green: score strong and rvol > 1.2
    yellow: score moderate
    red: else
    """
    strong = abs(score) > 0.25
    moderate = 0.1 <= abs(score) <= 0.25
    rvol_ok = (rvol or 0) > 1.2
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
        book_imbalance_1 = _compute_book_imbalance(data, 1)
        book_imbalance_3 = _compute_book_imbalance(data, 3)
        book_imbalance_5 = _compute_book_imbalance(data, 5)

        # Top of book (quote.bidSize/askSize — always from REST)
        top_book_pressure = _compute_top_book_pressure(data)

        # REST fallback: when streamer has no depth, use top-of-book only
        # Store in same field so frontend renders without changes. Streamer takes precedence.
        if book_imbalance_5 is None and top_book_pressure is not None:
            book_imbalance_5 = top_book_pressure
            log.debug("Book Imb: REST proxy (top of book only)")

        # Use 5-level for scoring when available
        book_for_score = book_imbalance_5 or book_imbalance_3 or book_imbalance_1
        spread = _compute_spread(data)

        # Tape metrics
        tape_pressure_30s = _compute_tape_pressure(data, 30.0)
        tape_pressure_2m = _compute_tape_pressure(data, 120.0)
        tape_pressure_5m = _compute_tape_pressure(data, 300.0)
        tape_for_score = tape_pressure_2m or tape_pressure_30s or tape_pressure_5m

        # Cumulative delta
        cum_delta_proxy = _compute_cum_delta_proxy(data)
        cum_delta_slope = _compute_cum_delta_slope(data)

        # Absorption
        absorption_score, replenishment_score, absorption_direction = _compute_absorption(data)

        # Options flow
        options_flow_score, options_flow_direction, call_put_flow_ratio, delta_weighted_options_flow = (
            _compute_options_flow(data)
        )

        # Volume context
        rvol = _compute_rvol(data)

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
        order_flow_readiness = _readiness(order_flow_score, rvol)

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
            of_delta_arrow = order_flow_field_arrow(
                1.0 if (cum_delta_proxy or 0) > 0 else (-1.0 if (cum_delta_proxy or 0) < 0 else 0.0)
            )
            of_opt_arrow = order_flow_field_arrow(options_flow_score)
            of_opt_label = order_flow_opt_label(options_flow_score)
        except ImportError:
            of_verdict = "FLOW NEUTRAL"
            of_verdict_color = "gray"
            of_arrow = "→"
            of_agreement = "weak | conflicted"
            of_score_arrow = of_book_arrow = of_delta_arrow = of_opt_arrow = "→"
            of_score_label = of_book_label = of_opt_label = "neutral"

        return {
            "book_imbalance_1": book_imbalance_1,
            "book_imbalance_3": book_imbalance_3,
            "book_imbalance_5": book_imbalance_5,
            "top_book_pressure": top_book_pressure,
            "spread": spread,
            "tape_pressure_30s": tape_pressure_30s,
            "tape_pressure_2m": tape_pressure_2m,
            "tape_pressure_5m": tape_pressure_5m,
            "cum_delta_proxy": cum_delta_proxy,
            "cum_delta_slope": cum_delta_slope,
            "absorption_score": absorption_score,
            "replenishment_score": replenishment_score,
            "absorption_direction": absorption_direction,
            "options_flow_score": options_flow_score,
            "options_flow_direction": options_flow_direction,
            "call_put_flow_ratio": call_put_flow_ratio,
            "delta_weighted_options_flow": delta_weighted_options_flow,
            "rvol": rvol,
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
            "spread": None,
            "tape_pressure_30s": None,
            "tape_pressure_2m": None,
            "tape_pressure_5m": None,
            "cum_delta_proxy": None,
            "cum_delta_slope": None,
            "absorption_score": None,
            "replenishment_score": None,
            "absorption_direction": None,
            "options_flow_score": None,
            "options_flow_direction": None,
            "call_put_flow_ratio": None,
            "delta_weighted_options_flow": None,
            "rvol": None,
            "institutional_flow_proxy_score": None,
            "order_flow_score": 0.0,
            "order_flow_direction": "neutral",
            "order_flow_regime": "neutral",
            "order_flow_readiness": "red",
            "order_flow_verdict": "FLOW NEUTRAL",
            "order_flow_verdict_color": "gray",
            "order_flow_arrow": "→",
            "order_flow_agreement": "weak | conflicted",
            "order_flow_score_arrow": "→",
            "order_flow_score_label": "neutral",
            "order_flow_book_arrow": "→",
            "order_flow_book_label": "balanced",
            "order_flow_delta_arrow": "→",
            "order_flow_opt_arrow": "→",
            "order_flow_opt_label": "neutral",
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
                "TICK": "Up",
                "BOOK_TIME": 999000,
            },
            {
                "LAST_PRICE": 150.1,
                "LAST_SIZE": 75,
                "TRADE_TIME_MILLIS": 950000,
                "TICK": "Up",
            },
            {
                "LAST_PRICE": 149.95,
                "LAST_SIZE": 50,
                "TRADE_TIME_MILLIS": 900000,
                "TICK": "Down",
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
