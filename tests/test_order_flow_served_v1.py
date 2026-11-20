"""Order flow computes nothing in the page (P1-3, PR C).

The book heatmap's default window, each
cell's dominant side and the colour scale's top are served. Book rows are real TSLA NASDAQ_BOOK
messages (tests/fixtures/real_tsla_book_rows.json).
"""

import json
from pathlib import Path

import pytest

from app.options.order_flow.history import (
    DISPLAY_TAIL_SHARE,
    RecentBooks,
    book_heatmap_for_ticker,
)
from app.options.order_flow.state import read_book

_FX = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_tsla_book_rows.json").read_text(
        encoding="utf-8"
    )
)


def _books(rows) -> RecentBooks:
    """Return a fresh store fed each captured (ts_recv, venue, book message).

    Fed as the console's intake does: each message read by the one reader (State's read_book), a
    message with no book not recorded.
    """
    books = RecentBooks()
    for _ts, svc, nat in rows:
        book = read_book(nat, svc)
        if book is not None:
            books.record("TSLA", svc, book)
    return books


@pytest.fixture
def heat():
    d = book_heatmap_for_ticker("TSLA", "NASDAQ_BOOK", minutes=240, books=_books(_FX["rows"]))
    assert d["available"] is True and len(d["cells"]) > 50
    return d


def _sizes(c):
    return [v for v in (c["bid"], c["ask"]) if v is not None]


def test_each_cell_carries_its_dominant_side_and_the_scale_top(heat):
    """A side Schwab sent no level for at a price is absent (None), never 0.

    The cell's side is the one Schwab sent, or the larger of the two.
    """
    one_sided = 0
    for c in heat["cells"]:
        b, a = c["bid"], c["ask"]
        assert _sizes(c), c
        one_sided += b is None or a is None
        want = (
            "BID"
            if a is None
            else "ASK"
            if b is None
            else "BID"
            if b > a
            else "ASK"
            if a > b
            else "EVEN"
        )
        assert c["side"] == want
    assert one_sided, "real TSLA books: a price carries a bid or an ask, rarely both"
    assert heat["max_size"] == max(v for c in heat["cells"] for v in _sizes(c))


def test_the_default_window_drops_the_thin_tails(heat):
    totals = {}
    for c in heat["cells"]:
        totals[c["price"]] = totals.get(c["price"], 0.0) + sum(_sizes(c))
    whole, cum, inside = sum(totals.values()), 0.0, []
    for px in sorted(totals):
        cum += totals[px]
        if DISPLAY_TAIL_SHARE <= cum / whole <= 1 - DISPLAY_TAIL_SHARE:
            inside.append(px)
    assert heat["display_lo"] == inside[0] and heat["display_hi"] == inside[-1]
    assert min(totals) <= heat["display_lo"] < heat["display_hi"] <= max(totals)


def test_a_book_at_one_price_is_served_its_one_price_with_no_width_of_ours():
    """Every size at one price: the window's top is its bottom, that price.

    INDUCED: real TSLA NASDAQ_BOOK messages cut to their best bid alone (Schwab has not yet sent
    a book with one level on one side); the 17 CFR 242.612 tick is $0.005 for some stocks, so a
    minimum width of ours would put a price on the axis that no book held.
    """
    rows = [
        (ts, svc, {**nat, "BIDS": nat["BIDS"][:1], "ASKS": []})
        for ts, svc, nat in _FX["rows"][:50]
        if nat["BIDS"]
    ]
    price = rows[0][2]["BIDS"][0]["BID_PRICE"]
    rows = [r for r in rows if r[2]["BIDS"][0]["BID_PRICE"] == price]
    d = book_heatmap_for_ticker("TSLA", "NASDAQ_BOOK", minutes=240, books=_books(rows))
    assert {c["price"] for c in d["cells"]} == {price}
    assert (d["display_lo"], d["display_hi"]) == (price, price)


def test_the_window_ends_at_the_newest_book_with_levels_not_the_empty_after_close_snapshots():
    """After the close Schwab keeps sending empty book snapshots.

    Measured 2026-09-27: SPY's latest NASDAQ_BOOK message is {"key": "SPY", "BOOK_TIME": ...,
    "BIDS": [], "ASKS": []}. Anchoring the window on those left the heatmap blank all weekend.
    """
    # the newest book with levels, at Schwab's own BOOK_TIME (the window's time base)
    last = max(nat["BOOK_TIME"] for _, svc, nat in _FX["rows"] if svc == "NASDAQ_BOOK") / 1000
    empties = [
        (
            last + 3600 * h,
            "NASDAQ_BOOK",
            {"key": "TSLA", "BOOK_TIME": int((last + 3600 * h) * 1000), "BIDS": [], "ASKS": []},
        )
        for h in range(1, 40)
    ]
    d = book_heatmap_for_ticker(
        "TSLA", "NASDAQ_BOOK", minutes=60, books=_books(_FX["rows"] + empties)
    )
    assert d["available"] is True and d["cells"]
    assert d["until_ts"] == last


#: the heatmap the browser tests draw (tests/e2e/console-order-flow-heatmap.spec.js)
_DRAWN = Path(__file__).resolve().parent / "e2e" / "fixtures" / "book_heatmap_payload.json"


def write_heatmap_e2e_fixture() -> None:
    """Regeneration utility (never called by a test): the producer's answer, as the socket sends.

    python -c "import tests.conftest, tests.test_order_flow_served_v1 as t
    t.write_heatmap_e2e_fixture()"
    """
    d = book_heatmap_for_ticker("TSLA", "NASDAQ_BOOK", minutes=240, books=_books(_FX["rows"]))
    _DRAWN.write_bytes((json.dumps(d, indent=2) + "\n").encode("utf-8"))  # as Prettier writes


def test_the_heatmap_the_browser_draws_is_the_producers_own(heat):
    """The browser test's payload is the producer's answer on the real TSLA books, kept equal.

    Its times are Schwab's BOOK_TIME of the first and the newest book with levels.
    """
    assert json.loads(_DRAWN.read_text(encoding="utf-8")) == json.loads(json.dumps(heat)), (
        "drifted from the producer; regenerate with write_heatmap_e2e_fixture()"
    )
    timed = [nat["BOOK_TIME"] / 1000 for _, svc, nat in _FX["rows"] if svc == "NASDAQ_BOOK"]
    assert (heat["since_ts"], heat["until_ts"]) == (min(timed), max(timed))
    # each bucket's start as the screen shows it, the first at the window's start
    assert len(heat["bucket_ct"]) == heat["n_buckets"]
    assert heat["bucket_ct"][0] == heat["since_ct"] == "Fri 09/25 06:55 PM CT"
    # each bucket's start served as its time and its marks on the chart's time axis
    assert heat["bucket_ts"][0] == heat["since_ts"]
    assert len(heat["bucket_ts"]) == len(heat["bucket_ticks"]) == heat["n_buckets"]
    assert heat["bucket_ticks"][0] == ["2026", "Sep", "Sep 25", "18:55"]
