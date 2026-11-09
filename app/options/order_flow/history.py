"""The recent option prints, books and imbalance readout values, in the console's memory.

The recent option trade prints (the options tape), the recent books (the book heatmap) and the
imbalance readout's one-second values (the Liquidity card), in the console's memory: fed by the
console's intake as the daemon pushes each record (app.options.order_flow.streaming), never read
from the database (docs/DATA_FLOW.md §2 D6).
The database keeps the whole history.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any

from app.options.order_flow.engine import OF_LEAN_KEPT_SEC, Book
from instrument_identity import ticker_storage_key
from l1_trade_observation import extract_vendor_print, is_adjacent_restatement, vendor_triple
from numeric_contract import schwab_count, schwab_number

#: the newest prints kept per contract (the tape route serves up to 500)
TAPE_KEPT = 500
#: how long a venue's books are kept (the heatmap route's longest window)
BOOKS_KEPT_SEC = 240 * 60
#: the contract details Schwab sends once and then only when they change: carried forward
_CONTEXT = (
    "STRIKE_TYPE",
    "CONTRACT_TYPE",
    "EXPIRATION_YEAR",
    "EXPIRATION_MONTH",
    "EXPIRATION_DAY",
    "MULTIPLIER",
    "UNDERLYING",
)


class RecentTape:
    """Per option contract: its newest TAPE_KEPT trade prints.

    A print is a genuinely NEW
    (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) triple, never a repeat of the same trade sent again
    with an unrelated field (l1_trade_observation's rule, the live tape's); the contract's details
    are carried forward from the newest message that sent them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prints: dict[str, deque] = {}
        self._context: dict[str, dict] = {}
        self._last: dict[str, tuple] = {}

    def record(
        self, contract: str, item: dict, ts_recv: float, top: dict | None, streamed: dict | None
    ) -> None:
        """Record one LEVELONE_OPTIONS record of `contract` as the live state took it.

        It carries its top of book
        (`top`, state.option_top) and its streamed Greeks and volume (`streamed`,
        state.get_stream_greeks), each read once by the state; the print and the contract's
        details are read here.
        """
        sym = ticker_storage_key(contract)
        if not sym or not isinstance(item, dict):
            return
        with self._lock:
            context = self._context.setdefault(sym, {})
            context.update({k: item[k] for k in _CONTEXT if item.get(k) is not None})
            p = extract_vendor_print(item)
            if p is None:
                return
            key = vendor_triple(p["time_millis"], p["price"], p["size"])
            if is_adjacent_restatement(self._last.get(sym), key):
                return
            self._last[sym] = key
            self._prints.setdefault(sym, deque(maxlen=TAPE_KEPT)).append(
                _print_row(sym, item, p, dict(context), float(ts_recv), top, streamed)
            )

    def forget(self, contract: str) -> None:
        """Drop the contract's prints, when the console stops streaming it."""
        sym = ticker_storage_key(contract)
        with self._lock:
            self._prints.pop(sym, None)
            self._context.pop(sym, None)
            self._last.pop(sym, None)

    def rows(self, contract: str, limit: int) -> list[dict[str, Any]]:
        """Return the contract's newest `limit` prints, newest first."""
        sym = ticker_storage_key(contract)
        with self._lock:
            held = list(self._prints[sym]) if sym in self._prints else []
        return held[::-1][: max(0, int(limit))]

    def put_call(self, contract: str) -> str | None:
        """Return the contract's side (CALL / PUT) as Schwab's CONTRACT_TYPE last sent it.

        None until sent.
        """
        sym = ticker_storage_key(contract)
        with self._lock:
            return (
                put_call_side(self._context[sym].get("CONTRACT_TYPE"))
                if sym in self._context
                else None
            )


def _print_row(
    sym: str,
    item: dict,
    p: dict,
    context: dict,
    ts_recv: float,
    top: dict | None,
    streamed: dict | None,
) -> dict[str, Any]:
    """Return one trade print in the Options Flow tape's schema.

    Schwab's values as sent; premium =
    trade x size x Schwab's multiplier; `classification` only where the trade landed against
    the same record's bid and ask (no aggressor side).
    """
    strike = schwab_number(context.get("STRIKE_TYPE"))
    side = put_call_side(context.get("CONTRACT_TYPE"))
    y, m, d = (
        context.get("EXPIRATION_YEAR"),
        context.get("EXPIRATION_MONTH"),
        context.get("EXPIRATION_DAY"),
    )
    expiry = f"{y:04d}-{m:02d}-{d:02d}" if (y and m and d) else None
    mult = schwab_number(context.get("MULTIPLIER"))
    trade, size = p["price"], p["size"]
    premium = (
        trade * size * mult
        if (trade is not None and size is not None and mult is not None)
        else None
    )
    bid, ask = _held(top, "bid"), _held(top, "ask")
    classification = "unknown"
    if trade is not None and bid is not None and ask is not None:
        if trade <= bid:
            classification = "at_bid" if trade == bid else "outside_spread_low"
        elif trade >= ask:
            classification = "at_ask" if trade == ask else "outside_spread_high"
        else:
            classification = "inside_spread"
    return {
        "ts_recv": ts_recv,
        "symbol": sym,
        "underlying": context.get("UNDERLYING"),
        "expiry": expiry,
        "type": side,
        "strike": strike,
        "bid": bid,
        "bid_size": _held(top, "bid_size"),
        "ask": ask,
        "ask_size": _held(top, "ask_size"),
        "trade": trade,
        "size": size,
        "premium": premium,
        "volume": _held(streamed, "total_volume"),
        "oi": schwab_count(item.get("OPEN_INTEREST")),
        "iv": _held(streamed, "volatility"),
        "delta": _held(streamed, "delta"),
        "multiplier": mult,
        "classification": classification,
    }


def _held(record: dict | None, name: str) -> Any:
    """Return `record`'s value of `name`; None when the state holds no record or no such value."""
    return None if record is None else record.get(name)


def put_call_side(contract_type) -> str | None:
    """Schwab's LEVELONE_OPTIONS CONTRACT_TYPE ('C' / 'P'), as CALL / PUT; None when not sent."""
    return {"C": "CALL", "P": "PUT"}.get(contract_type)


#: The default price window drops this share of displayed size at each end: one thin resting order
#: far from the touch would otherwise stretch the axis. It sets the default view only: every cell
#: is served, and the chart rescales past it.
DISPLAY_TAIL_SHARE = 0.01


def _display_window(cells: list[dict]) -> tuple[float, float]:
    """Return (lo, hi), the price window of displayed size, trimmed at each end.

    It holds all but DISPLAY_TAIL_SHARE of displayed size at each end.
    """
    totals: dict[float, float] = {}
    for c in cells:
        totals[c["price"]] = totals.get(c["price"], 0.0) + sum(
            v for v in (c["bid"], c["ask"]) if v is not None
        )
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


class RecentBooks:
    """Per (ticker, venue): its books for BOOKS_KEPT_SEC, one per second.

    The newest in that second, each as (receive time, bid levels, ask levels). A book with no
    level (after the close Schwab keeps sending empty ones) is not kept, so the window ends at
    the last real one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._books: dict[tuple[str, str], deque] = {}

    def record(self, ticker: str, venue: str, book: Book, ts_recv: float) -> None:
        sym = ticker_storage_key(ticker)
        if not sym:
            return
        bids, asks = tuple(book.pairs("BIDS")), tuple(book.pairs("ASKS"))
        if not bids and not asks:
            return
        kept = (float(ts_recv), bids, asks)
        with self._lock:
            held = self._books.setdefault((sym, venue), deque())
            if held and int(held[-1][0]) == int(kept[0]):
                held[-1] = kept
            else:
                held.append(kept)
            while held[0][0] < kept[0] - BOOKS_KEPT_SEC:
                held.popleft()

    def forget(self, ticker: str) -> None:
        """Drop the ticker's books on every venue, when the console stops streaming them."""
        sym = ticker_storage_key(ticker)
        with self._lock:
            for key in [k for k in self._books if k[0] == sym]:
                del self._books[key]

    def window(self, ticker: str, venue: str, minutes: float) -> list[tuple]:
        """Return the books of the `minutes` ending at the newest one, oldest first."""
        key = (ticker_storage_key(ticker), venue)
        with self._lock:
            held = list(self._books[key]) if key in self._books else []
        return [b for b in held if b[0] >= held[-1][0] - minutes * 60.0] if held else []


class RecentLean:
    """Per ticker: the imbalance readout of both books and their composite, one per second.

    The readout is engine.book_readout's, computed once as each book arrives, one per second
    (the newest in that second), as (receive time, readout): the Liquidity card's newest
    readout, and its smoothing, zone hold and lean series. Kept for engine.OF_LEAN_KEPT_SEC
    before the newest, and the one before that, which still stands then. Owner: the console's
    intake (streaming._ingest_pushed); while it receives no book, the last readout stands and the
    live rule marks it not live. It is per ticker over both venues, where RecentBooks is per
    venue.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # every ticker's series, empty until its first readout
        self._points: defaultdict[str, deque] = defaultdict(deque)

    def record(self, ticker: str, ts_recv: float, readout: dict) -> None:
        sym = ticker_storage_key(ticker)
        if not sym:
            return
        point = (float(ts_recv), readout)
        with self._lock:
            held = self._points[sym]
            if held and int(held[-1][0]) == int(point[0]):
                held[-1] = point
            else:
                held.append(point)
            while len(held) > 1 and held[1][0] <= point[0] - OF_LEAN_KEPT_SEC:
                held.popleft()

    def forget(self, ticker: str) -> None:
        with self._lock:
            self._points.pop(ticker_storage_key(ticker), None)

    def points(self, ticker: str) -> list[tuple[float, dict]]:
        """Return the ticker's kept values, oldest first."""
        with self._lock:
            return list(self._points[ticker_storage_key(ticker)])


#: the recent prints, books and imbalance values, fed by the console's intake
TAPE = RecentTape()
BOOKS = RecentBooks()
LEAN = RecentLean()


def book_heatmap_for_ticker(
    ticker: str, venue: str, *, minutes: float = 60.0, books: RecentBooks = BOOKS
) -> dict[str, Any]:
    """Return the book-depth heatmap for one Schwab book of a ticker, `venue`.

    `venue` is NYSE_BOOK or NASDAQ_BOOK; the two are never merged. Its recent books binned into
    a time x price grid, a cell the LAST observed size at that price within the bucket -- never
    a sum (a book is a full snapshot, so an unchanged resting level comes again with every other
    change). The window ends at the newest book, never the wall clock, so outside market hours
    the last real session shows with its own time. No interpolated cell.
    """
    sym = ticker_storage_key(ticker)
    if not sym:
        return {"ticker": ticker, "available": False, "reason": "empty ticker"}
    rows = books.window(sym, venue, minutes)
    if not rows:
        return {
            "ticker": sym,
            "available": False,
            "reason": f"no {venue} book with a price level since the console started",
        }

    t0 = rows[0][0]
    span = rows[-1][0] - t0  # binning floors at 1s below; no invented span
    n_buckets = 90
    bucket_sec = max(1.0, span / n_buckets)

    cells: dict[tuple[int, float], dict[str, float | None]] = {}
    prices_seen: set[float] = set()
    for ts_recv, bids, asks in rows:
        bucket = min(n_buckets - 1, int((ts_recv - t0) / bucket_sec))
        for levels, side in ((bids, "bid"), (asks, "ask")):
            for px, vol in levels:
                # a side Schwab sent no level for at this price stays absent, never 0
                cells.setdefault((bucket, px), {"bid": None, "ask": None})[side] = vol
                prices_seen.add(px)

    def _dominant(bid, ask) -> str:
        """Return the displayed side at this price and bucket (the cell's colour).

        The one Schwab sent, or the larger of the two.
        """
        if ask is None:
            return "BID"
        if bid is None:
            return "ASK"
        return "BID" if bid > ask else "ASK" if ask > bid else "EVEN"

    cell_list = sorted(
        (
            {
                "t": k[0],
                "price": k[1],
                "bid": v["bid"],
                "ask": v["ask"],
                "side": _dominant(v["bid"], v["ask"]),
            }
            for k, v in cells.items()
        ),
        key=lambda c: (c["t"], c["price"]),
    )
    display_lo, display_hi = _display_window(cell_list)
    return {
        "ticker": sym,
        "venue": venue,
        "available": True,
        "since_ts": t0,
        "until_ts": rows[-1][0],
        "latest_captured_ts": rows[-1][0],
        "n_buckets": n_buckets,
        "bucket_sec": bucket_sec,
        "price_min": min(prices_seen),
        "price_max": max(prices_seen),
        # the default price window, and the largest displayed size (the colour scale's top)
        "display_lo": display_lo,
        "display_hi": display_hi,
        "max_size": max(v for c in cell_list for v in (c["bid"], c["ask"]) if v is not None),
        "rows_scanned": len(rows),
        "cells": cell_list,
        "method": (
            "the venue's books in the console's memory, one per second, in the window "
            "ending at the newest, binned into n_buckets time columns x Schwab's BID_PRICE/"
            "ASK_PRICE rows; cell value = the LAST observed TOTAL_VOLUME at that price within "
            "the bucket -- never summed across repeated observations of the same resting size."
        ),
    }
