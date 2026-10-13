"""The recent option trade prints (the options tape) and the recent books (the book heatmap), in
the console's memory: fed by the console's intake as the daemon pushes each record
(app.options.order_flow.streaming), never read from the database (docs/DATA_FLOW.md §2 D6).
The database keeps the whole history."""
from __future__ import annotations

import threading
from collections import deque
from typing import Any

from instrument_identity import ticker_storage_key
from l1_trade_observation import is_adjacent_restatement, vendor_triple
from numeric_contract import schwab_count, schwab_number

#: the newest prints kept per contract (the tape route serves up to 500)
TAPE_KEPT = 500
#: how long a venue's books are kept (the heatmap route's longest window)
BOOKS_KEPT_SEC = 240 * 60
class RecentTape:
    """Per option contract: its newest TAPE_KEPT trade prints, read from its record
    (option_ledger) each time it changes. A print is a LEVELONE_OPTIONS message that carried a
    trade time (the record's `tradeTimeInLong` and `streamTime` stamped by the same posting), its
    price and size the record's (Streamer API §1.1, Change: a field not sent is unchanged), and a
    genuinely NEW (trade time, last price, last size) triple, never a repeat of the same trade with
    an unrelated field changed (l1_trade_observation's rule)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prints: dict[str, deque] = {}
        self._last: dict[str, tuple] = {}

    def record(self, contract: str, fields: dict, times: dict, ts_recv: float) -> bool:
        """Take the record's trade when it is a new print; returns whether it was."""
        sym = ticker_storage_key(contract)
        price = schwab_number(fields.get("last"))
        stamp = times.get("streamTime")
        if not sym or price is None or stamp is None or times.get("tradeTimeInLong") != stamp:
            return False
        size = schwab_count(fields.get("lastSize"))
        p = {"price": price, "size": int(size) if size is not None else None,
             "time_millis": fields.get("tradeTimeInLong")}
        key = vendor_triple(p["time_millis"], p["price"], p["size"])
        with self._lock:
            if is_adjacent_restatement(self._last.get(sym), key):
                return False
            self._last[sym] = key
            self._prints.setdefault(sym, deque(maxlen=TAPE_KEPT)).append(
                _print_row(sym, fields, p, float(ts_recv)))
        return True

    def forget(self, contract: str) -> None:
        """Drop the contract's prints, when the console stops streaming it."""
        sym = ticker_storage_key(contract)
        with self._lock:
            self._prints.pop(sym, None)
            self._last.pop(sym, None)

    def rows(self, contract: str, limit: int) -> "list[dict[str, Any]]":
        """The contract's newest `limit` prints, newest first."""
        sym = ticker_storage_key(contract)
        with self._lock:
            held = list(self._prints[sym]) if sym in self._prints else []
        return held[::-1][:max(0, int(limit))]


def _print_row(sym: str, item: dict, p: dict, ts_recv: float) -> "dict[str, Any]":
    """One trade print in the Options Flow tape's schema, from the contract's record (`item`):
    Schwab's values as sent; premium = trade x size x Schwab's multiplier; `classification` only
    where the trade landed against the record's bid and ask (no aggressor side)."""
    strike = schwab_number(item.get("strikePrice"))
    side = item.get("putCall") if item.get("putCall") in ("CALL", "PUT") else None
    expiry = str(item["expirationDate"])[:10] if item.get("expirationDate") else None
    mult = schwab_number(item.get("multiplier"))
    trade, size = p["price"], p["size"]
    premium = (trade * size * mult
               if (trade is not None and size is not None and mult is not None) else None)
    bid, ask = schwab_number(item.get("bid")), schwab_number(item.get("ask"))
    classification = "unknown"
    if trade is not None and bid is not None and ask is not None:
        if trade <= bid:
            classification = "at_bid" if trade == bid else "outside_spread_low"
        elif trade >= ask:
            classification = "at_ask" if trade == ask else "outside_spread_high"
        else:
            classification = "inside_spread"
    return {
        "ts_recv": ts_recv, "symbol": sym, "underlying": item.get("ticker"),
        "expiry": expiry, "type": side, "strike": strike,
        "bid": bid, "bid_size": schwab_count(item.get("bidSize")),
        "ask": ask, "ask_size": schwab_count(item.get("askSize")),
        "trade": trade, "size": size, "premium": premium,
        "volume": schwab_count(item.get("totalVolume")), "oi": schwab_count(item.get("openInterest")),
        "iv": schwab_number(item.get("volatility")), "delta": schwab_number(item.get("delta")),
        "multiplier": mult, "classification": classification,
    }


#: The default price window drops this share of displayed size at each end: one thin resting order
#: far from the touch would otherwise stretch the axis. Carried unchanged from the page
#: (2026-09-27); its origin is not recorded -- NOT_PROVEN.
DISPLAY_TAIL_SHARE = 0.01


def _display_window(cells: list[dict]) -> tuple[float, float]:
    """(lo, hi): the price window holding all but DISPLAY_TAIL_SHARE of displayed size at each end."""
    totals: dict[float, float] = {}
    for c in cells:
        totals[c["price"]] = totals.get(c["price"], 0.0) + sum(v for v in (c["bid"], c["ask"]) if v is not None)
    prices = sorted(totals)
    whole = sum(totals.values())
    if not whole:
        return prices[0], max(prices[-1], prices[0] + 0.01)
    lo = hi = None
    cum = 0.0
    for px in prices:
        cum += totals[px]
        if lo is None and cum / whole >= DISPLAY_TAIL_SHARE:
            lo = px
        if cum / whole <= 1 - DISPLAY_TAIL_SHARE:
            hi = px
    lo = prices[0] if lo is None else lo
    hi = prices[-1] if hi is None or hi <= lo else hi
    return lo, max(hi, lo + 0.01)


def _levels(item: dict, leaf: str, price_key: str) -> "tuple[tuple[float, int], ...]":
    """One side of a Schwab book as (price, size) pairs; a single level can arrive as one bare
    object rather than a list. A level without a number for both is not a level."""
    levels = item.get(leaf)
    if not isinstance(levels, list):
        levels = [levels] if levels else []
    out = []
    for lvl in levels:
        if isinstance(lvl, dict):
            px, vol = schwab_number(lvl.get(price_key)), schwab_count(lvl.get("TOTAL_VOLUME"))
            if px is not None and vol is not None:
                out.append((px, vol))
    return tuple(out)


class RecentBooks:
    """Per (ticker, venue): its books for BOOKS_KEPT_SEC, one per second (the newest in that
    second), each as (receive time, bid levels, ask levels). A book with no level (after the
    close Schwab keeps sending empty ones) is not kept, so the window ends at the last real one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._books: dict[tuple[str, str], deque] = {}

    def record(self, ticker: str, venue: str, item: dict, ts_recv: float) -> None:
        sym = ticker_storage_key(ticker)
        if not sym or not isinstance(item, dict):
            return
        bids, asks = _levels(item, "BIDS", "BID_PRICE"), _levels(item, "ASKS", "ASK_PRICE")
        if not bids and not asks:
            return
        book = (float(ts_recv), bids, asks)
        with self._lock:
            held = self._books.setdefault((sym, venue), deque())
            if held and int(held[-1][0]) == int(book[0]):
                held[-1] = book
            else:
                held.append(book)
            while held[0][0] < book[0] - BOOKS_KEPT_SEC:
                held.popleft()

    def forget(self, ticker: str) -> None:
        """Drop the ticker's books on every venue, when the console stops streaming them."""
        sym = ticker_storage_key(ticker)
        with self._lock:
            for key in [k for k in self._books if k[0] == sym]:
                del self._books[key]

    def window(self, ticker: str, venue: str, minutes: float) -> "list[tuple]":
        """The books of the `minutes` ending at the newest one, oldest first."""
        key = (ticker_storage_key(ticker), venue)
        with self._lock:
            held = list(self._books[key]) if key in self._books else []
        return [b for b in held if b[0] >= held[-1][0] - max(1.0, float(minutes)) * 60.0] if held else []


#: the recent prints and books, fed by the console's intake
TAPE = RecentTape()
BOOKS = RecentBooks()


def book_heatmap_for_ticker(ticker: str, venue: str, *, minutes: float = 60.0,
                            books: RecentBooks = BOOKS) -> dict[str, Any]:
    """Book-depth heatmap for one Schwab book of a ticker, `venue` (NYSE_BOOK or NASDAQ_BOOK; the
    two are never merged): its recent books binned into a time x price grid, a cell the LAST
    observed size at that price within the bucket -- never a sum (a book is a full snapshot, so
    an unchanged resting level comes again with every other change). The window ends at the
    newest book, never the wall clock, so outside market hours the last real session shows with
    its own time. No interpolated cell."""
    sym = ticker_storage_key(ticker)
    if not sym:
        return {"ticker": ticker, "available": False, "reason": "empty ticker"}
    rows = books.window(sym, venue, minutes)
    if not rows:
        return {"ticker": sym, "available": False,
                "reason": f"no {venue} book with a price level since the console started"}

    t0 = rows[0][0]
    span = rows[-1][0] - t0   # binning floors at 1s below; no invented span
    n_buckets = 90
    bucket_sec = max(1.0, span / n_buckets)

    cells: dict[tuple[int, float], dict[str, float]] = {}
    prices_seen: set[float] = set()
    for ts_recv, bids, asks in rows:
        bucket = min(n_buckets - 1, int((ts_recv - t0) / bucket_sec))
        for levels, side in ((bids, "bid"), (asks, "ask")):
            for px, vol in levels:
                # a side Schwab sent no level for at this price stays absent, never 0
                cells.setdefault((bucket, px), {"bid": None, "ask": None})[side] = vol
                prices_seen.add(px)

    def _dominant(bid, ask) -> str:
        """The displayed side at this price and bucket (the cell's colour): the one Schwab sent,
        or the larger of the two."""
        if ask is None:
            return "BID"
        if bid is None:
            return "ASK"
        return "BID" if bid > ask else "ASK" if ask > bid else "EVEN"

    cell_list = sorted(
        ({"t": k[0], "price": k[1], "bid": v["bid"], "ask": v["ask"], "side": _dominant(v["bid"], v["ask"])}
         for k, v in cells.items()),
        key=lambda c: (c["t"], c["price"]),
    )
    display_lo, display_hi = _display_window(cell_list)
    return {
        "ticker": sym, "venue": venue, "available": True,
        "since_ts": t0, "until_ts": rows[-1][0], "latest_captured_ts": rows[-1][0],
        "n_buckets": n_buckets, "bucket_sec": bucket_sec,
        "price_min": min(prices_seen), "price_max": max(prices_seen),
        # the default price window, and the largest displayed size (the colour scale's top)
        "display_lo": display_lo, "display_hi": display_hi,
        "max_size": max(v for c in cell_list for v in (c["bid"], c["ask"]) if v is not None),
        "rows_scanned": len(rows),
        "cells": cell_list,
        "method": ("the venue's books in the console's memory, one per second, in the window "
                   "ending at the newest, binned into n_buckets time columns x Schwab's BID_PRICE/"
                   "ASK_PRICE rows; cell value = the LAST observed TOTAL_VOLUME at that price within "
                   "the bucket -- never summed across repeated observations of the same resting size."),
    }
