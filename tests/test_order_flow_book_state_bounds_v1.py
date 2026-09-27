"""The order-flow book store is bounded per contract and keeps contracts apart (real QQQ/TSLA
option books, tests/fixtures/real_options_stream_history_samples.json)."""
from __future__ import annotations

import json
from pathlib import Path

from app.options.order_flow.live_payload import options_live_payload
from app.options.order_flow.state import MAX_BOOK_SNAPSHOTS, OrderFlowState

FIXTURE = Path(__file__).parent / "fixtures" / "real_options_stream_history_samples.json"


def _samples() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]


def test_canonical_book_state_is_bounded_and_contract_isolated():
    samples = _samples()
    first, second = samples[0], samples[1]
    first_book = next(e for e in first["events"] if e["kind"] == "book")["content"]
    second_book = next(e for e in second["events"] if e["kind"] == "book")["content"]
    state = OrderFlowState()

    base_time = int(first_book["BOOK_TIME"])
    for i in range(MAX_BOOK_SNAPSHOTS + 5):
        state.push_book(first["symbol"], dict(first_book, BOOK_TIME=base_time + i))
    state.push_book(second["symbol"], second_book)

    first_content = state.get_content_for_symbol(first["symbol"])
    second_content = state.get_content_for_symbol(second["symbol"])
    first_books = [row for row in first_content if "BIDS" in row]
    assert len(first_books) == MAX_BOOK_SNAPSHOTS
    assert first_books[0]["BOOK_TIME"] == base_time + 5
    assert first_books[-1]["BOOK_TIME"] == base_time + MAX_BOOK_SNAPSHOTS + 4
    assert all(row.get("BOOK_TIME") != second_book["BOOK_TIME"] for row in first_books)
    assert len([row for row in second_content if "BIDS" in row]) == 1
    assert options_live_payload("MISSING")["status"] == "no_book"


