"""RC-456: engine batch geometry is not absorption or replenishment."""
from __future__ import annotations

import pytest

from order_flow_engine import OrderFlowEngine, _compute_book_tape_batch_geometry


def test_retired_absorption_keys_are_none_and_geometry_is_emitted():
    data = {
        "content": [
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 50}],
                "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 40}],
            },
            {"LAST_PRICE": 10.0, "LAST_SIZE": 8, "TRADE_TIME_MILLIS": 1},
            {"LAST_PRICE": 10.2, "LAST_SIZE": 2, "TRADE_TIME_MILLIS": 2},
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 80}],
                "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 30}],
            },
        ]
    }
    out = OrderFlowEngine().compute(data)
    assert out["absorption_score"] is None
    assert out["replenishment_score"] is None
    assert out["absorption_direction"] is None
    assert out["book_displayed_bid_delta"] == 30.0
    assert out["book_displayed_ask_delta"] == -10.0
    assert out["tape_print_size_sum"] == 10.0
    assert out["tape_print_price_range"] == pytest.approx(0.2)


def test_no_magic_ratio_when_price_does_not_move():
    data = {
        "content": [
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 10}],
                "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 10}],
            },
            {"LAST_PRICE": 10.05, "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1},
            {"LAST_PRICE": 10.05, "LAST_SIZE": 50, "TRADE_TIME_MILLIS": 2},
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 10}],
                "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 10}],
            },
        ]
    }
    geom = _compute_book_tape_batch_geometry(data)
    assert geom["tape_print_size_sum"] == 150.0
    assert geom["tape_print_price_range"] == 0.0
    assert geom["book_displayed_bid_delta"] == 0.0


def test_single_book_snapshot_has_no_depth_delta():
    data = {
        "content": [
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 10}],
                "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 10}],
            },
            {"LAST_PRICE": 10.0, "LAST_SIZE": 5, "TRADE_TIME_MILLIS": 1},
        ]
    }
    geom = _compute_book_tape_batch_geometry(data)
    assert geom["book_displayed_bid_delta"] is None
    assert geom["book_displayed_ask_delta"] is None
    assert geom["tape_print_size_sum"] == 5.0
    assert geom["tape_print_price_range"] is None
