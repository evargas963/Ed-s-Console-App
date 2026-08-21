from __future__ import annotations

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


def test_absorption_skips_missing_print_size():
    data = {
        "content": [
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 100}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 100}]},
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
            {"BIDS": [{"BID_PRICE": 499.9, "TOTAL_VOLUME": 120}], "ASKS": [{"ASK_PRICE": 500.1, "TOTAL_VOLUME": 110}]},
        ]
    }

    absorption, _, _ = ofe._compute_absorption(data)

    assert absorption is not None
    assert round(absorption, 6) == round(10 / 0.11, 6)


def test_absorption_label_is_truthful_density_not_admitted():
    """Mission TRUTH_V1 lock (Section C): the label must match the measurement. `_compute_absorption`
    computes a volume/price-range DENSITY, not level-based absorption, and has no validity evidence
    (a second producer feeds the model). This test fails if a future edit silently re-inflates the
    docstring back to an unqualified 'absorption detected at a level' claim."""
    doc = (ofe._compute_absorption.__doc__ or "")
    up = doc.upper()
    # states what it actually is, and that it is not admitted / is a proxy
    assert "DENSITY" in up, "docstring must state the metric is a volume/price-range density"
    assert "PROXY" in up
    assert "NOT_ADMITTED" in up
    # the specific overstated claim that this remediation removed must not return verbatim
    assert "large size at a level that doesn't move price" not in doc.lower()

    # and the mechanical identity still holds: absorption == total_sized_volume / (range + eps)
    data = {"content": [
        {"BIDS": [{"BID_PRICE": 9.9, "TOTAL_VOLUME": 100}], "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 100}]},
        {"LAST_PRICE": 10.00, "LAST_SIZE": 4, "TRADE_TIME_MILLIS": 1_000},
        {"LAST_PRICE": 10.20, "LAST_SIZE": 6, "TRADE_TIME_MILLIS": 2_000},
        {"BIDS": [{"BID_PRICE": 9.9, "TOTAL_VOLUME": 120}], "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 110}]},
    ]}
    absorption, replenishment, direction = ofe._compute_absorption(data)
    assert round(absorption, 6) == round(10 / (0.20 + ofe.OF_ABSORPTION_PRICE_EPS), 6)
    # replenishment is the 2-snapshot depth-change midpoint: ((120-100)+(110-100))/2 = 15
    assert replenishment == 15.0
    assert direction == "bid"  # bid depth grew more than ask
