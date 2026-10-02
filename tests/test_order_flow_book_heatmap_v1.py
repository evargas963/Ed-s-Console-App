"""app.options.order_flow.history.book_heatmap_for_ticker: bins one venue's recent NASDAQ_BOOK or
NYSE_BOOK books (history.RecentBooks, fed by the console's intake) into a time x price grid -- the
time-dimensioned counterpart a single live snapshot cannot show. No interpolation: every cell
traces to a real book's own native BID_PRICE/ASK_PRICE/TOTAL_VOLUME."""
from __future__ import annotations

from app.options.order_flow import streaming as S
from app.options.order_flow.history import RecentBooks, book_heatmap_for_ticker
from stream_spine import book_msg

SYM = "SPY"


def _books(rows: list[tuple[float, str, dict]]) -> RecentBooks:
    """A fresh store fed each (ts_recv, venue, book) as the console's intake does."""
    books = RecentBooks()
    for ts_recv, service, content in rows:
        books.record(SYM, service, content, ts_recv)
    return books


def _book(bid_price, bid_vol, ask_price, ask_vol, book_time_ms=0):
    return {
        "key": SYM, "BOOK_TIME": book_time_ms,
        "BIDS": [{"BID_PRICE": bid_price, "TOTAL_VOLUME": bid_vol, "NUM_BIDS": 1}] if bid_price is not None else [],
        "ASKS": [{"ASK_PRICE": ask_price, "TOTAL_VOLUME": ask_vol, "NUM_ASKS": 1}] if ask_price is not None else [],
    }


def test_repeated_unchanged_levels_do_not_inflate_the_cell():
    """NASDAQ_BOOK/NYSE_BOOK messages are full-book snapshots, not deltas -- an UNCHANGED
    100-share level re-transmitted in ten seconds of one bucket must still read as 100, never as
    1,000. The cell holds the LAST observed size in the bucket, not a sum across every
    retransmission of the same resting size. A book 900 s later sets the span (bucket = 10 s)."""
    books = _books([(1000.0 + s, "NASDAQ_BOOK", _book(100.00, 100, 100.05, 30)) for s in range(10)]
                   + [(1900.0, "NASDAQ_BOOK", _book(101.00, 1, 101.05, 1))])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)
    assert d["available"] is True
    assert d["rows_scanned"] == 11 and d["bucket_sec"] == 10.0
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert cells[(0, 100.00)]["bid"] == 100.0   # not 1000.0
    assert cells[(0, 100.05)]["ask"] == 30.0    # not 300.0


def test_books_within_one_second_keep_only_the_newest():
    """One book per second, the newest in that second: a book replaced 0.4 s later is the one
    kept."""
    books = _books([
        (1000.0, "NASDAQ_BOOK", _book(100.00, 50, 100.05, 30)),
        (1000.4, "NASDAQ_BOOK", _book(100.00, 20, 100.05, 10)),
    ])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)
    assert d["rows_scanned"] == 1 and d["until_ts"] == 1000.4
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert cells[(0, 100.00)]["bid"] == 20.0 and cells[(0, 100.05)]["ask"] == 10.0


def test_a_changed_level_in_the_same_bucket_reads_as_its_latest_observed_size():
    # Two books 3 s apart land in the SAME 10 s bucket (a book 900 s later sets the span).
    books = _books([
        (1000.0, "NASDAQ_BOOK", _book(100.00, 50, 100.05, 30)),
        (1003.0, "NASDAQ_BOOK", _book(100.00, 20, 100.05, 10)),  # same bucket, same price -> latest wins
        (1900.0, "NASDAQ_BOOK", _book(101.00, 1, 101.05, 1)),
    ])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)
    assert d["available"] is True
    assert d["rows_scanned"] == 3
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    # a side Schwab sent no level for at a price is absent, never a 0 size (operator 2026-10-01:
    # "we use what schwab gives us and we display it")
    assert (0, 100.00) in cells and cells[(0, 100.00)]["bid"] == 20.0 and cells[(0, 100.00)]["ask"] is None
    assert (0, 100.05) in cells and cells[(0, 100.05)]["ask"] == 10.0 and cells[(0, 100.05)]["bid"] is None


def test_each_venue_shows_only_its_own_book():
    books = _books([
        (1000.0, "NASDAQ_BOOK", _book(100.00, 50, 100.05, 30)),
        (1000.0, "NYSE_BOOK", _book(100.00, 25, 100.05, 15)),
    ])
    for venue, bid, ask in (("NASDAQ_BOOK", 50.0, 30.0), ("NYSE_BOOK", 25.0, 15.0)):
        d = book_heatmap_for_ticker(SYM, venue, minutes=60, books=books)
        assert d["venue"] == venue and d["rows_scanned"] == 1
        cells = {(c["t"], c["price"]): c for c in d["cells"]}
        assert (cells[(0, 100.00)]["bid"], cells[(0, 100.05)]["ask"]) == (bid, ask)


def test_window_anchors_to_the_datas_own_latest_row_never_wallclock_now():
    """A real prior session (all books far in the past) must still render honestly outside
    RTH -- the window is [latest_captured_ts - minutes*60, latest_captured_ts], never
    [now - minutes*60, now], or every weekend/after-hours request would show an empty grid
    despite real data existing a few hours earlier."""
    old_ts = 500_000.0   # far from any real wall-clock "now" in a test run
    books = _books([(old_ts, "NASDAQ_BOOK", _book(50.00, 10, 50.05, 10))])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=5, books=books)
    assert d["available"] is True
    assert d["latest_captured_ts"] == old_ts == d["until_ts"]
    assert d["since_ts"] <= old_ts


def test_rows_outside_the_minutes_window_are_excluded():
    books = _books([
        (99_000.0, "NASDAQ_BOOK", _book(50.00, 999, 50.05, 999)),    # kept, but outside a 5-min window
        (100_290.0, "NASDAQ_BOOK", _book(60.00, 10, 60.05, 10)),     # within 5 min of the latest book
        (100_300.0, "NASDAQ_BOOK", _book(60.10, 5, 60.15, 5)),       # latest book
    ])
    assert book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)["rows_scanned"] == 3
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=5, books=books)
    assert d["available"] is True and d["rows_scanned"] == 2
    prices = {c["price"] for c in d["cells"]}
    assert 50.00 not in prices and 50.05 not in prices
    assert 60.00 in prices and 60.10 in prices


def test_no_book_at_all_fails_closed_with_a_plain_reason():
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=RecentBooks())
    assert d["available"] is False
    assert d["reason"] == "no NASDAQ_BOOK book with a price level since the console started"


def test_books_with_every_level_array_empty_fail_closed_not_a_fabricated_grid():
    books = _books([(1000.0, "NASDAQ_BOOK", _book(None, None, None, None))])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)
    assert d["available"] is False
    assert d["reason"] == "no NASDAQ_BOOK book with a price level since the console started"


def test_an_options_book_never_leaks_into_the_underlyings_heatmap():
    """An OPTIONS_BOOK message describes a contract's own book, not the underlying's: through the
    console's intake it never reaches the venue books the heatmap bins. Stand-in ticker XLE,
    which no other test records."""
    S._ingest_pushed("book.XLE", book_msg(symbol="XLE", service="OPTIONS_BOOK",
                                           content=_book(1.00, 5000, 1.05, 5000), src="schwab_book",
                                           ts_recv=1000.0))
    for venue in ("NASDAQ_BOOK", "NYSE_BOOK", "OPTIONS_BOOK"):
        assert book_heatmap_for_ticker("XLE", venue, minutes=60)["available"] is False
