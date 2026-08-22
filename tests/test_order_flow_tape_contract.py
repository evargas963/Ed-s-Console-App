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


def test_tape_and_cum_delta_are_classified_reconstructed_l1_tick():
    engine = ofe.OrderFlowEngine()
    out = engine.compute({
        "content": [
            {"LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    })
    assert out["tape_pressure_classification"] == "PROXY_RECONSTRUCTED_L1_TICK"
    assert out["cum_delta_classification"] == "PROXY_RECONSTRUCTED_L1_TICK"
    assert out["tape_identity_convention"] == "L1_OBSERVATION_RESTATEMENT"
    assert out["tape_native_event_id"] is False
    assert "unique trade identifier" in out["tape_limitations"].lower()
    assert out["institutional_flow_proxy_score"] is None
    assert not hasattr(ofe, "OF_CUM_DELTA_NORM_DIVISOR")


def test_tape_pressure_window_is_relative_to_latest_print():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 120_000},
        ]
    }
    # Window from the LATEST stamp (120s), not the first item. The 100-lot print is
    # out of a 30s window and only seeds prev_price; pressure is the uptick 10-lot.
    assert ofe._compute_tape_pressure(data, window_sec=30.0) == 1.0


def test_identical_l1_restatement_does_not_double_count_cum_delta():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    }
    assert ofe._compute_cum_delta_proxy(data) == 10


def test_same_ms_distinct_size_is_kept_as_batch():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 4, "TRADE_TIME_MILLIS": 1_000},
        ]
    }
    assert ofe._compute_cum_delta_proxy(data) == 4


def test_server_source_does_not_inject_rest_into_cum_delta_proxy():
    from pathlib import Path
    src = Path("server.py").read_text(encoding="utf-8")
    assert "ms.cum_delta_proxy = _rest_cum_delta" not in src


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
