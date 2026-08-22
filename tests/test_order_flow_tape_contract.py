from __future__ import annotations

import pytest

import order_flow_engine as ofe


def test_tape_prints_preserve_missing_size_instead_of_zero():
    prints = ofe._iter_tape_prints([
        {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000}
    ])

    assert prints == [{"price": 500.0, "size": None, "time_millis": 1_000}]


def test_cum_delta_proxy_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) == 10


def test_cum_delta_proxy_returns_none_when_all_print_sizes_missing():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 499.9, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) is None


def test_tape_pressure_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_tape_pressure(data, window_sec=60.0) == 1.0


def test_batch_geometry_skips_missing_print_size_and_does_not_ratio():
    data = {
        "content": [
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 100}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 100}]},
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 120}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 110}]},
        ]
    }

    geom = ofe._compute_book_tape_batch_geometry(data)
    assert geom["tape_print_size_sum"] == 10.0
    assert geom["tape_print_price_range"] == pytest.approx(0.1)
    assert geom["book_displayed_bid_delta"] == 20.0
    assert geom["book_displayed_ask_delta"] == 10.0
