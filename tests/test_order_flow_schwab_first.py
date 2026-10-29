"""Order flow reads streamed Schwab fields only: top-of-book pressure from BID_SIZE / ASK_SIZE."""

from __future__ import annotations

from app.options.order_flow.engine import _compute_top_book_pressure


def test_rest_quote_blocks_never_stand_in_for_streamed_l1():
    """2026-09-24: REST quote / extended / regular / chain-underlying and the book's top level
    no longer stand in for a missing streamed BID/ASK/MARK/size."""
    rest = {"quote": {"bidPrice": 1.0, "askPrice": 1.1, "mark": 1.05, "bidSize": 5, "askSize": 5},
            "extended": {"bidPrice": 1.0, "askPrice": 1.1, "mark": 1.05},
            "regular": {"mark": 1.05}, "underlying": {"bid": 1.0, "ask": 1.1},
            "content": [{"BIDS": [{"BID_PRICE": 1.0, "TOTAL_VOLUME": 5}],
                         "ASKS": [{"ASK_PRICE": 1.1, "TOTAL_VOLUME": 5}]}]}
    assert _compute_top_book_pressure(rest) is None


def test_top_book_pressure_streaming_uses_bid_ask_size_leaves_only():
    assert _compute_top_book_pressure({"top": {"bid_size": 120, "ask_size": 80}}) == (120 - 80) / 200


def test_top_book_pressure_ignores_non_canonical_streaming_bid_ask_size_keys():
    """Streaming CSV leaves are BID_SIZE/ASK_SIZE — not REST quote.bidSize/askSize."""
    assert _compute_top_book_pressure({"content": [{"bidSize": 100, "askSize": 50}]}) is None
