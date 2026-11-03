"""The order-flow book store holds each symbol's newest book from each Schwab service, and keeps
symbols apart (real QQQ/TSLA option books, tests/fixtures/real_options_stream_history_samples.json;
SPY's NYSE_BOOK and NASDAQ_BOOK of 2026-11-02, tests/fixtures/real_spy_books_2026_11_02.json)."""

from __future__ import annotations

import json
from pathlib import Path

from app.options.order_flow.live_payload import options_live_payload
from app.options.order_flow.state import OrderFlowState

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "real_options_stream_history_samples.json"


def _samples() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]


def test_each_contract_keeps_its_newest_book_apart():
    samples = _samples()
    first, second = samples[0], samples[1]
    first_book = next(e for e in first["events"] if e["kind"] == "book")["content"]
    second_book = next(e for e in second["events"] if e["kind"] == "book")["content"]
    state = OrderFlowState()

    base_time = int(first_book["BOOK_TIME"])
    for i in range(25):
        state.push_book(first["symbol"], dict(first_book, BOOK_TIME=base_time + i), "OPTIONS_BOOK")
    state.push_book(second["symbol"], second_book, "OPTIONS_BOOK")

    first_content = state.get_content_for_symbol(first["symbol"])
    second_content = state.get_content_for_symbol(second["symbol"])
    first_books = [row for row in first_content if "BIDS" in row]
    # one book per service: the newest, never a backlog
    assert [row["BOOK_TIME"] for row in first_books] == [base_time + 24]
    assert all(row.get("BOOK_TIME") != second_book["BOOK_TIME"] for row in first_books)
    assert len([row for row in second_content if "BIDS" in row]) == 1
    assert options_live_payload("MISSING", float(base_time) / 1000)["status"] == "no_book"


def test_a_quiet_books_newest_stands_however_many_the_other_service_sends():
    """Schwab sends a book only when it changes. SPY's NYSE_BOOK as sent at 10:00:00 ET on
    2026-11-02, then every NASDAQ_BOOK Schwab sent in the next 150 s (more than the 20 books the
    store used to keep per symbol): NYSE_BOOK's book still stands, the newest of each service."""
    rows = json.loads((FIXTURES / "real_spy_books_2026_11_02.json").read_text("utf-8"))["rows"]
    nyse = next(c for _ts, svc, c in rows if svc == "NYSE_BOOK")
    nasdaq = [c for _ts, svc, c in rows if svc == "NASDAQ_BOOK"]
    assert len(nasdaq) > 20
    state = OrderFlowState()
    state.push_book("SPY", nyse, "NYSE_BOOK")
    for c in nasdaq:
        state.push_book("SPY", c, "NASDAQ_BOOK")
    assert state.newest_book("SPY", "NYSE_BOOK")["BOOK_TIME"] == nyse["BOOK_TIME"]
    assert state.newest_book("SPY", "NASDAQ_BOOK")["BOOK_TIME"] == nasdaq[-1]["BOOK_TIME"]
    assert [b["BOOK_TIME"] for b in state.get_content_for_symbol("SPY", "NYSE_BOOK")] == [
        nyse["BOOK_TIME"]
    ]
