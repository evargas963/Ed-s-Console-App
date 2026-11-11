"""The recent books and imbalance readout values, and the option tape's rows.

The recent books (the book heatmap) and the imbalance readout's one-second values (the Liquidity
card), in the console's memory: fed by the console's intake as the daemon pushes each record
(app.options.order_flow.streaming), never read from the database (docs/DATA_FLOW.md §2 D6).
The options tape is drawn from the live state's prints (state.push_level_one keeps each once).
The database keeps the whole history.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from typing import Any

from app.options.order_flow.engine import OF_LEAN_KEPT_SEC, Book
from instrument_identity import ticker_storage_key
from l1_trade_observation import canonical_tape_prints
from option_contract import OptionContract

log = logging.getLogger(__name__)

#: how long a venue's books are kept (the heatmap route's longest window)
BOOKS_KEPT_SEC = 240 * 60


def quoted(trade: float, top: dict | None, streamed: dict | None) -> dict[str, Any]:
    """Return what the live state held as a print at `trade` was received, kept with the print.

    Its top of book (`top`), its streamed volume, volatility and delta (`streamed`), and
    `landed`: only where the trade landed against that bid and ask (no aggressor side).
    """
    bid, ask = _held(top, "bid"), _held(top, "ask")
    landed = "unknown"
    if bid is not None and ask is not None:
        if trade <= bid:
            landed = "at_bid" if trade == bid else "outside_spread_low"
        elif trade >= ask:
            landed = "at_ask" if trade == ask else "outside_spread_high"
        else:
            landed = "inside_spread"
    return {
        "bid": bid,
        "bid_size": _held(top, "bid_size"),
        "ask": ask,
        "ask_size": _held(top, "ask_size"),
        "volume": _held(streamed, "total_volume"),
        "iv": _held(streamed, "volatility"),
        "delta": _held(streamed, "delta"),
        "landed": landed,
    }


def recent_prints(contract: str, content: list, limit: int) -> list[dict[str, Any]]:
    """Return the newest `limit` prints of `contract` as the tape names them, newest first.

    `content` is the live state's for the contract (state.get_content_for_symbol): each print it
    kept, a genuinely new (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE), with what it held then.
    `trade_time_ms` is Schwab's TRADE_TIME_MILLIS as sent (None: the message carried none);
    `ts_recv`, when the message arrived, orders prints of several contracts and is not shown.
    The contract's terms are not here: the tape shows them from its chain record (tape_row).
    """
    sym = ticker_storage_key(contract)
    return [
        {
            "ts_recv": p["server_received_ts"],
            "trade_time_ms": p["time_millis"],
            "symbol": sym,
            "bid": p["bid"],
            "bid_size": p["bid_size"],
            "ask": p["ask"],
            "ask_size": p["ask_size"],
            "trade": p["price"],
            "size": p["size"],
            "volume": p["volume"],
            "iv": p["iv"],
            "delta": p["delta"],
            "classification": p["landed"],
        }
        for p in canonical_tape_prints(content)[::-1][: max(0, int(limit))]
    ]


def tape_row(printed: dict[str, Any], contract: OptionContract) -> dict[str, Any]:
    """Return one kept print as the Options Flow tape shows it, with its contract's terms.

    Expiry, side, strike and open interest are the chain record's (option_contract.read_contract,
    the one reader of them); premium = trade x size x that record's multiplier, unknown without
    a size or a multiplier. Its time is Schwab's trade time; the receive time is not served.
    """
    size, mult = printed["size"], contract.multiplier
    return {
        **{k: v for k, v in printed.items() if k != "ts_recv"},
        "expiry": contract.expiry,
        "type": contract.side,
        "strike": contract.strike,
        "oi": contract.open_interest,
        "premium": None if size is None or mult is None else printed["trade"] * size * mult,
    }


def _held(record: dict | None, name: str) -> Any:
    """Return `record`'s value of `name`; None when the state holds no record or no such value."""
    return None if record is None else record.get(name)


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

    The newest in that second, each as (Schwab's BOOK_TIME in seconds, bid levels, ask levels):
    a book is placed at the time Schwab gives it, not when it arrived. A book with no level
    (after the close Schwab keeps sending empty ones) is not kept, so the window ends at the
    last real one. A book with no BOOK_TIME, or one older than the newest kept (neither seen on
    NYSE_BOOK or NASDAQ_BOOK), has no place on this time axis: it is logged and not kept.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._books: dict[tuple[str, str], deque] = {}

    def record(self, ticker: str, venue: str, book: Book) -> None:
        sym = ticker_storage_key(ticker)
        if not sym:
            return
        bids, asks = tuple(book.pairs("BIDS")), tuple(book.pairs("ASKS"))
        if not bids and not asks:
            return
        with self._lock:
            held = self._books.setdefault((sym, venue), deque())
            if book.book_time_ms is None or (held and book.book_time_ms / 1000.0 < held[-1][0]):
                log.warning(
                    "%s %s book not placed on the heatmap: BOOK_TIME %s, newest kept %s",
                    sym,
                    venue,
                    book.book_time_ms,
                    held[-1][0] if held else None,
                )
                return
            kept = (book.book_time_ms / 1000.0, bids, asks)
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


#: the recent books and imbalance values, fed by the console's intake
BOOKS = RecentBooks()
LEAN = RecentLean()


def book_heatmap_for_ticker(
    ticker: str, venue: str, *, minutes: float = 60.0, books: RecentBooks = BOOKS
) -> dict[str, Any]:
    """Return the book-depth heatmap for one Schwab book of a ticker, `venue`.

    `venue` is NYSE_BOOK or NASDAQ_BOOK; the two are never merged. Its recent books binned into
    a time x price grid, a cell the LAST observed size at that price within the bucket -- never
    a sum (a book is a full snapshot, so an unchanged resting level comes again with every other
    change). Every time is Schwab's BOOK_TIME (seconds): the window ends at the newest book's,
    never the wall clock, so outside market hours the last real session shows with its own
    time. No interpolated cell.
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
    for ts_recv, bids, asks in rows:
        bucket = min(n_buckets - 1, int((ts_recv - t0) / bucket_sec))
        for levels, side in ((bids, "bid"), (asks, "ask")):
            for px, vol in levels:
                # a side Schwab sent no level for at this price stays absent, never 0
                cells.setdefault((bucket, px), {"bid": None, "ask": None})[side] = vol

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
        "n_buckets": n_buckets,
        "bucket_sec": bucket_sec,
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
