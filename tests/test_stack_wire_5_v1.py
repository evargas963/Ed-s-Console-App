"""The order-flow state keeps what Schwab sent across the open: no time of day wipes it.

At 09:30 ET the state cleared every book, top-of-book field, tape print and streamed option
Greek; Schwab resends a field only when it changes, so a value it had sent stayed absent until
it changed. Real SPY NASDAQ_BOOK and NYSE_BOOK (tests/fixtures/real_spy_nyse_nasdaq_books.json);
the state reads no clock, so no time of day reaches it.
"""
from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls

_BOOKS = json.loads((Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json")
                    .read_text(encoding="utf-8"))["books"]
_BOOK = _BOOKS["NASDAQ_BOOK"]["content"]


def test_a_book_sent_before_the_open_is_kept_through_the_open():
    # the state reads no clock: a book taken before the open stands when the next message lands
    st = ofls.OrderFlowState()
    st.push_book("SPY", _BOOK, "NASDAQ_BOOK")
    # the first message after the open (the real SPY NYSE_BOOK) wipes nothing
    st.push_book("SPY", _BOOKS["NYSE_BOOK"]["content"], "NYSE_BOOK")
    assert any(i.get("BIDS") for i in st.get_content_for_symbol("SPY", "NASDAQ_BOOK"))
