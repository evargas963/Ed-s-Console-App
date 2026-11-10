"""app.options.order_flow.history.book_heatmap_for_ticker: one venue's books as a time x price grid.

It bins one venue's recent NASDAQ_BOOK or NYSE_BOOK books (history.RecentBooks, fed by the
console's intake) into a time x price grid -- the time-dimensioned counterpart a single live
snapshot cannot show. No interpolation: every cell traces to a real book's own native
BID_PRICE/ASK_PRICE/TOTAL_VOLUME.

The books are Schwab's own SPY messages of 2026-11-02, 10:00:00 to 10:02:30 ET, both venues in
the order received (tests/fixtures/real_spy_books_2026_11_02.json): 141 NYSE_BOOK messages in
139 seconds, 149.85 s from first to last, so a column of the 90 is 1.665 s and some hold two
books.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
from app.options.order_flow import state
from app.options.order_flow import streaming as S
from app.options.order_flow.engine import read_book
from app.options.order_flow.history import RecentBooks, book_heatmap_for_ticker
from stream_spine import book_msg

_FX = Path(__file__).resolve().parent / "fixtures"
SYM = "SPY"
NYSE = "NYSE_BOOK"


def _sent(venue: str) -> list[tuple[float, str, dict]]:
    """Return Schwab's SPY book messages of `venue` as (ts_recv, venue, message), oldest first."""
    rows = json.loads((_FX / "real_spy_books_2026_11_02.json").read_text(encoding="utf-8"))["rows"]
    return [(ts_recv, service, sent) for ts_recv, service, sent in rows if service == venue]


def _books(rows: list[tuple[float, str, dict]]) -> RecentBooks:
    """Feed a fresh store each (ts_recv, venue, book message) as the console's intake does.

    The message is read by the one reader (engine.read_book) first.
    """
    books = RecentBooks()
    for ts_recv, service, content in rows:
        books.record(SYM, service, read_book(content, service), ts_recv)
    return books


def _sizes(sent: dict, side: str) -> dict:
    """Return Schwab's own levels of one side of a book message: price -> TOTAL_VOLUME."""
    price = {"BIDS": "BID_PRICE", "ASKS": "ASK_PRICE"}[side]
    return {level[price]: level["TOTAL_VOLUME"] for level in sent[side]}


def _shown(d: dict, side: str) -> dict:
    """Return the sizes the grid shows on one side: (column, price) -> size."""
    return {(c["t"], c["price"]): c[side] for c in d["cells"] if c[side] is not None}


def test_repeated_unchanged_levels_do_not_inflate_the_cell():
    """NASDAQ_BOOK/NYSE_BOOK messages are full-book snapshots, not deltas.

    An UNCHANGED level sent again within one column must still read as its size, never as the
    sum. The cell holds the LAST observed size in the column, not a sum across every
    retransmission of the same resting size. Schwab's 6th and 7th NYSE books share column 3 and
    both hold 840 bid at 759.60; its 12th and 13th share column 7 and both hold 1,480 at 760.39.
    """
    sent = _sent(NYSE)
    for older, newer, price, size in ((5, 6, 759.6, 840), (11, 12, 760.39, 1480)):
        assert (
            _sizes(sent[older][2], "BIDS")[price] == _sizes(sent[newer][2], "BIDS")[price] == size
        )
    d = book_heatmap_for_ticker(SYM, NYSE, minutes=60, books=_books(sent))
    assert d["available"] is True
    assert d["rows_scanned"] == 139 and d["bucket_sec"] == (sent[-1][0] - sent[0][0]) / 90
    bids = _shown(d, "bid")
    assert bids[(3, 759.6)] == 840  # not 1680
    assert bids[(7, 760.39)] == 1480  # not 2960


def test_books_within_one_second_keep_only_the_newest():
    """One book per second, the newest in that second.

    Schwab's 69th and 70th NYSE books came 0.81 s apart in one second; the 70th is the one kept.
    """
    older, newer = _sent(NYSE)[68:70]
    assert int(older[0]) == int(newer[0]) and older[2]["BIDS"] != newer[2]["BIDS"]
    d = book_heatmap_for_ticker(SYM, NYSE, minutes=60, books=_books([older, newer]))
    assert d["rows_scanned"] == 1 and d["until_ts"] == newer[0]
    assert {p: v for (_, p), v in _shown(d, "bid").items()} == _sizes(newer[2], "BIDS")
    assert {p: v for (_, p), v in _shown(d, "ask").items()} == _sizes(newer[2], "ASKS")


def test_a_changed_level_in_the_same_bucket_reads_as_its_latest_observed_size():
    """Schwab's 3rd and 4th NYSE books are 1.09 s apart, in column 1.

    The bid at 760.05 went from 720 to 40 and the ask at 760.80 from 960 to 160.
    """
    sent = _sent(NYSE)
    older, newer = sent[2][2], sent[3][2]
    assert (_sizes(older, "BIDS")[760.05], _sizes(newer, "BIDS")[760.05]) == (720, 40)
    assert (_sizes(older, "ASKS")[760.8], _sizes(newer, "ASKS")[760.8]) == (960, 160)
    d = book_heatmap_for_ticker(SYM, NYSE, minutes=60, books=_books(sent))
    assert d["available"] is True
    assert d["rows_scanned"] == 139
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    # a side Schwab sent no level for at a price is absent, never a 0 size (operator 2026-10-01:
    # "we use what schwab gives us and we display it")
    assert (
        (1, 760.05) in cells
        and cells[(1, 760.05)]["bid"] == 40
        and cells[(1, 760.05)]["ask"] is None
    )
    assert (
        (1, 760.8) in cells and cells[(1, 760.8)]["ask"] == 160 and cells[(1, 760.8)]["bid"] is None
    )


def test_each_venue_shows_only_its_own_book():
    first = {venue: _sent(venue)[0] for venue in (NYSE, "NASDAQ_BOOK")}
    assert first[NYSE][2]["BIDS"] != first["NASDAQ_BOOK"][2]["BIDS"]
    books = _books(list(first.values()))
    for venue, (_, _, sent) in first.items():
        d = book_heatmap_for_ticker(SYM, venue, minutes=60, books=books)
        assert d["venue"] == venue and d["rows_scanned"] == 1
        assert (_shown(d, "bid"), _shown(d, "ask")) == (
            {(0, p): v for p, v in _sizes(sent, "BIDS").items()},
            {(0, p): v for p, v in _sizes(sent, "ASKS").items()},
        )


def test_window_anchors_to_the_datas_own_latest_row_never_wallclock_now():
    """A real prior session (all books far in the past) must still render honestly outside RTH.

    The window is [latest_captured_ts - minutes*60, latest_captured_ts], never
    [now - minutes*60, now], or every weekend/after-hours request would show an empty grid
    despite real data existing a few hours earlier. These books are of 2026-11-02.
    """
    sent = _sent(NYSE)
    d = book_heatmap_for_ticker(SYM, NYSE, minutes=5, books=_books(sent))
    assert d["available"] is True
    assert d["latest_captured_ts"] == sent[-1][0] == d["until_ts"]
    assert d["since_ts"] == sent[0][0]


def test_rows_outside_the_minutes_window_are_excluded():
    """The last minute of the 150 s holds 55 of the 139 seconds' books.

    744.50 is a price only the books before it hold, 759.14 one only its books hold.
    """
    books = _books(_sent(NYSE))
    whole = book_heatmap_for_ticker(SYM, NYSE, minutes=60, books=books)
    assert whole["rows_scanned"] == 139
    d = book_heatmap_for_ticker(SYM, NYSE, minutes=1, books=books)
    assert d["available"] is True and d["rows_scanned"] == 55
    prices = {c["price"] for c in d["cells"]}
    assert 744.5 not in prices and 744.5 in {c["price"] for c in whole["cells"]}
    assert 759.14 in prices and d["since_ts"] >= d["until_ts"] - 60


def test_no_book_at_all_fails_closed_with_a_plain_reason():
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=RecentBooks())
    assert d["available"] is False
    assert d["reason"] == "no NASDAQ_BOOK book with a price level since the console started"


def test_books_with_every_level_array_empty_fail_closed_not_a_fabricated_grid():
    """Induced: Schwab's first NASDAQ book with both of its level arrays emptied.

    No captured book is empty on both sides.
    """
    ts_recv, venue, sent = _sent("NASDAQ_BOOK")[0]
    books = _books([(ts_recv, venue, dict(sent, BIDS=[], ASKS=[]))])
    d = book_heatmap_for_ticker(SYM, "NASDAQ_BOOK", minutes=60, books=books)
    assert d["available"] is False
    assert d["reason"] == "no NASDAQ_BOOK book with a price level since the console started"


def test_an_options_book_never_leaks_into_the_underlyings_heatmap():
    """An OPTIONS_BOOK message describes a contract's own book, not the underlying's.

    Through the console's intake it never reaches the venue books the heatmap bins. The message
    is Schwab's own for TSLA 260831C00367500 (real_options_stream_history_samples.json).
    """
    contract = next(
        c
        for c in json.loads(
            (_FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8")
        )["contracts"]
        if c["symbol"] == "TSLA  260831C00367500"
    )
    sent = next(e for e in contract["events"] if e["kind"] == "book")
    S._ingest_pushed(
        f"book.{contract['symbol']}",
        book_msg(
            symbol=contract["symbol"],
            service="OPTIONS_BOOK",
            content=sent["content"],
            src=sent["source"],
            ts_recv=sent["ts_recv"],
        ),
    )
    try:
        for venue in ("NASDAQ_BOOK", "NYSE_BOOK", "OPTIONS_BOOK"):
            assert book_heatmap_for_ticker(contract["symbol"], venue)["available"] is False
    finally:
        state.clear_symbol(contract["symbol"])


def test_a_window_outside_the_books_kept_is_refused_never_replaced():
    """The panel answers any window above 0 up to the books the console keeps (240 minutes).

    A longer one, 0 or less, or one that is not a number, is refused, never answered for a
    window the page did not ask.
    """

    for minutes in (0.5, 15, 60, 120, 240):
        assert "available" in server.bookmap(SYM, {"venue": "NASDAQ_BOOK", "minutes": minutes})
    for minutes in (241, 0, -60, "abc"):
        with pytest.raises(ValueError) as refused:
            server.bookmap(SYM, {"venue": "NASDAQ_BOOK", "minutes": minutes})
        assert repr(minutes) in str(refused.value), "the refusal names the window asked"
