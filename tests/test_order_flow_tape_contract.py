from __future__ import annotations

import order_flow_engine as ofe


def test_tape_prints_preserve_missing_size_instead_of_zero():
    prints = ofe._iter_tape_prints([
        {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000, "TICK": "Up"}
    ])

    assert prints == [{"price": 500.0, "size": None, "time_millis": 1_000, "tick": "Up"}]


def test_cum_delta_proxy_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000, "TICK": "Up"},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000, "TICK": "Up"},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) == 10


def test_cum_delta_proxy_returns_none_when_all_print_sizes_missing():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000, "TICK": "Up"},
            {"LAST_PRICE": 499.9, "TRADE_TIME_MILLIS": 2_000, "TICK": "Down"},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) is None


def test_tape_pressure_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000, "TICK": "Down"},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000, "TICK": "Up"},
        ]
    }

    assert ofe._compute_tape_pressure(data, window_sec=60.0) == 1.0


def test_absorption_skips_missing_print_size():
    data = {
        "content": [
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 100}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 100}]},
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000, "TICK": "Up"},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000, "TICK": "Up"},
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 120}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 110}]},
        ]
    }

    absorption, _, _ = ofe._compute_absorption(data)

    assert absorption is not None
    assert round(absorption, 6) == round(10 / 0.11, 6)
