"""The order-flow state keeps what Schwab sent: a later message does not wipe a book.

Schwab resends a field only when it changes, so a value it sent must stand until it changes; the
state reads no clock, so no time of day can clear it. Real SPY NASDAQ_BOOK
(tests/fixtures/real_spy_nyse_nasdaq_books.json).
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls
from stream_spine import MessageBus
from tests.feed_live_helper import apply_record, on_the_bus

_BOOK = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json").read_text(
        encoding="utf-8"
    )
)["books"]["NASDAQ_BOOK"]["content"]


def test_a_book_sent_before_the_open_is_kept_through_the_open():
    st = ofls.OrderFlowState()
    st.push_book("SPY", _BOOK, "NASDAQ_BOOK")
    eq = "LEVELONE_EQUITIES"
    apply_record(st, eq, on_the_bus(MessageBus(), eq, {"key": "SPY", "LAST_PRICE": 660.0}, 1.0))
    assert st.newest_book("SPY", "NASDAQ_BOOK").bids
