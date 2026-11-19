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
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from calc.order_flow import OF_LEAN_KEPT_SEC, Book
from instrument_identity import ticker_storage_key
from numeric_contract import (
    count_text,
    dollars_text,
    fixed_text,
    iv_text,
    price_text,
    strike_text,
)
from option_contract import OptionContract, StreamedGreeks, StreamedTop
from time_et import ct_clock, ct_label, ct_ticks

log = logging.getLogger(__name__)

#: how long a venue's books are kept (the heatmap route's longest window)
BOOKS_KEPT_SEC = 240 * 60

#: one side of a kept book: each level's (price, TOTAL_VOLUME), as Schwab sent them
Side = tuple[tuple[float, float], ...]
#: a kept book: (Schwab's BOOK_TIME in seconds, bid levels, ask levels)
KeptBook = tuple[float, Side, Side]


class Cell(TypedDict):
    """One cell of the book heatmap: its time bucket, price, each side's size, the side shown."""

    t: int
    price: float
    bid: float | None
    ask: float | None
    #: each side's size as the screen shows it (numeric_contract.count_text)
    bid_text: str | None
    ask_text: str | None
    side: str


class Quoted(TypedDict):
    """What the live state held as a print was received (quoted): top of book, streamed values."""

    bid: Any
    bid_size: Any
    ask: Any
    ask_size: Any
    volume: Any
    iv: Any
    delta: Any
    landed: str


class Printed(TypedDict):
    """A print's own fields: Schwab's trade time, the trade and what the state held then."""

    trade_time_ms: int | None
    symbol: str
    bid: Any
    bid_size: Any
    ask: Any
    ask_size: Any
    trade: float
    size: Any
    volume: Any
    iv: Any
    delta: Any
    classification: str


class TapePrint(Printed):
    """One kept print as the tape names it (recent_prints), with when it was received."""

    ts_recv: float


class TapeRow(Printed):
    """One print as the Options Flow tape shows it (tape_row): its time in CT, its terms."""

    trade_time_ct: str | None
    expiry: str | None
    type: str | None
    strike: float | None
    oi: Any
    premium: float | None
    strike_text: str | None
    bid_text: str | None
    ask_text: str | None
    trade_text: str | None
    delta_text: str | None
    premium_text: str | None
    bid_size_text: str | None
    ask_size_text: str | None
    size_text: str | None
    volume_text: str | None
    oi_text: str | None
    iv_text: str | None


class NoHeatmap(TypedDict):
    """The heatmap's answer when there is no book to draw: why."""

    ticker: str
    available: Literal[False]
    reason: str


class BookHeatmap(TypedDict):
    """The heatmap of one venue's recent books (book_heatmap_for_ticker)."""

    ticker: str
    venue: str
    available: Literal[True]
    since_ts: float
    until_ts: float
    since_ct: str
    until_ct: str
    n_buckets: int
    bucket_sec: float
    #: each time bucket's start, by the cells' `t`: its time, as the screen shows it, and as the
    #: chart's time axis marks it (time_et.ct_ticks)
    bucket_ts: list[float]
    bucket_ct: list[str]
    bucket_ticks: list[list[str]]
    display_lo: float
    display_hi: float
    max_size: float
    rows_scanned: int
    cells: list[Cell]
    method: str


def quoted(trade: float, top: StreamedTop, streamed: StreamedGreeks) -> Quoted:
    """Return what the live state held as a print at `trade` was received, kept with the print.

    Its top of book (`top`), its streamed volume, volatility and delta (`streamed`), and
    `landed`: only where the trade landed against that bid and ask (no aggressor side).
    """
    bid, ask = top.bid, top.ask
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
        "bid_size": top.bid_size,
        "ask": ask,
        "ask_size": top.ask_size,
        "volume": streamed.total_volume.value,
        "iv": streamed.volatility.value,
        "delta": streamed.delta.value,
        "landed": landed,
    }


def recent_prints(contract: str, kept: Sequence[dict[str, Any]], limit: int) -> list[TapePrint]:
    """Return the newest `limit` prints of `contract` as the tape names them, newest first.

    `kept` is the live state's tape of the contract (state.prints), in receive order: each print
    it kept, a genuinely new (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE), with what it held then.
    `trade_time_ms` is Schwab's TRADE_TIME_MILLIS as sent (None: the message carried none);
    `ts_recv`, when the message arrived, is not shown; the tape orders prints by Schwab's trade
    time (server.tape).
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
        for p in kept[::-1][: max(0, int(limit))]
    ]


def tape_row(printed: TapePrint, contract: OptionContract) -> TapeRow:
    """Return one kept print as the Options Flow tape shows it, with its contract's terms.

    Expiry, side, strike and open interest are the chain record's (option_contract.read_contract,
    the one reader of them); premium = trade x size x that record's multiplier, unknown without
    a size or a multiplier. Its time is Schwab's trade time, and `trade_time_ct` that time as the
    screen shows it (time_et.ct_clock, None when Schwab sent none); the receive time is not served.
    """
    size, mult, ms = printed["size"], contract.multiplier, printed["trade_time_ms"]
    premium = None if size is None or mult is None else printed["trade"] * size * mult
    return {
        "trade_time_ms": ms,
        "trade_time_ct": None if ms is None else ct_clock(ms / 1000),
        "symbol": printed["symbol"],
        "bid": printed["bid"],
        "bid_size": printed["bid_size"],
        "ask": printed["ask"],
        "ask_size": printed["ask_size"],
        "trade": printed["trade"],
        "size": size,
        "volume": printed["volume"],
        "iv": printed["iv"],
        "delta": printed["delta"],
        "classification": printed["classification"],
        "expiry": contract.expiry,
        "type": contract.side,
        "strike": contract.strike,
        "oi": contract.open_interest,
        "premium": premium,
        # the strike, the prices, the premium, the sizes, the day's volume, open interest, IV and
        # delta as the screen shows them
        "strike_text": strike_text(contract.strike),
        "bid_text": price_text(printed["bid"]),
        "ask_text": price_text(printed["ask"]),
        "trade_text": price_text(printed["trade"]),
        "delta_text": fixed_text(printed["delta"], 3),
        "premium_text": dollars_text(premium),
        "bid_size_text": count_text(printed["bid_size"]),
        "ask_size_text": count_text(printed["ask_size"]),
        "size_text": count_text(size),
        "volume_text": count_text(printed["volume"]),
        "oi_text": count_text(contract.open_interest),
        "iv_text": iv_text(printed["iv"]),
    }


#: The default price window drops this share of displayed size at each end: one thin resting order
#: far from the touch would otherwise stretch the axis. It sets the default view only: every cell
#: is served, and the chart rescales past it.
DISPLAY_TAIL_SHARE = 0.01


def _display_window(cells: list[Cell]) -> tuple[float, float]:
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
        self._books: dict[tuple[str, str], deque[KeptBook]] = {}

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

    def window(self, ticker: str, venue: str, minutes: float) -> list[KeptBook]:
        """Return the books of the `minutes` ending at the newest one, oldest first."""
        key = (ticker_storage_key(ticker), venue)
        with self._lock:
            held = list(self._books[key]) if key in self._books else []
        return [b for b in held if b[0] >= held[-1][0] - minutes * 60.0] if held else []


class RecentLean:
    """Per ticker: the imbalance readout of both books and their composite, one per second.

    The readout is engine.book_readout's, computed once as each book arrives, one per second
    (the newest in that second), as (receive time, readout): the Liquidity card's newest
    readout, and its zone hold and lean series. Kept for engine.OF_LEAN_KEPT_SEC
    before the newest, and the one before that, which still stands then. Owner: the console's
    intake (streaming._ingest_pushed); while it receives no book, the last readout stands and the
    live rule marks it not live. It is per ticker over both venues, where RecentBooks is per
    venue.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # every ticker's series, empty until its first readout
        self._points: defaultdict[str, deque[tuple[float, dict[str, Any]]]] = defaultdict(deque)

    def record(self, ticker: str, ts_recv: float, readout: dict[str, Any]) -> None:
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

    def points(self, ticker: str) -> list[tuple[float, dict[str, Any]]]:
        """Return the ticker's kept values, oldest first."""
        with self._lock:
            return list(self._points[ticker_storage_key(ticker)])


#: the recent books and imbalance values, fed by the console's intake
BOOKS = RecentBooks()
LEAN = RecentLean()


def _dominant(bid: float | None, ask: float | None) -> str:
    """Return the displayed side at a price and bucket (the cell's colour).

    The one Schwab sent, or the larger of the two.
    """
    match bid, ask:
        case _, None:
            return "BID"
        case None, _:
            return "ASK"
        case _:
            return "BID" if bid > ask else "ASK" if ask > bid else "EVEN"


def _heatmap_cells(
    rows: list[KeptBook], t0: float, bucket_sec: float, n_buckets: int
) -> list[Cell]:
    """Return the books `rows` binned into time buckets x price, by bucket then price.

    A cell is the LAST observed size at that price within the bucket, each side as sent.
    """
    cells: dict[tuple[int, float], dict[str, float | None]] = {}
    for ts_recv, bids, asks in rows:
        bucket = min(n_buckets - 1, int((ts_recv - t0) / bucket_sec))
        for levels, side in ((bids, "bid"), (asks, "ask")):
            for px, vol in levels:
                # a side Schwab sent no level for at this price stays absent, never 0
                cells.setdefault((bucket, px), {"bid": None, "ask": None})[side] = vol
    return sorted(
        (
            {
                "t": k[0],
                "price": k[1],
                "bid": v["bid"],
                "ask": v["ask"],
                "bid_text": count_text(v["bid"]),
                "ask_text": count_text(v["ask"]),
                "side": _dominant(v["bid"], v["ask"]),
            }
            for k, v in cells.items()
        ),
        key=lambda c: (c["t"], c["price"]),
    )


def book_heatmap_for_ticker(
    ticker: str, venue: str, *, minutes: float = 60.0, books: RecentBooks = BOOKS
) -> BookHeatmap | NoHeatmap:
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
    cell_list = _heatmap_cells(rows, t0, bucket_sec, n_buckets)
    display_lo, display_hi = _display_window(cell_list)
    starts = [t0 + i * bucket_sec for i in range(n_buckets)]
    return {
        "ticker": sym,
        "venue": venue,
        "available": True,
        "since_ts": t0,
        "until_ts": rows[-1][0],
        # the window as the screen shows it
        "since_ct": ct_label(t0),
        "until_ct": ct_label(rows[-1][0]),
        "n_buckets": n_buckets,
        "bucket_sec": bucket_sec,
        "bucket_ts": starts,
        "bucket_ct": [ct_label(t) for t in starts],
        "bucket_ticks": [ct_ticks(t) for t in starts],
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
