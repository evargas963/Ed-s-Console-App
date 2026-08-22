"""order_flow_engine chunk-2: primitive book/tape paths; composite RETIRED (RC-454)."""
from __future__ import annotations

from unittest.mock import patch

from order_flow_engine import OrderFlowEngine


def _fake_micro(values: dict[int, float | None]) -> dict:
    return {
        "depth": {
            "1": {"imbalance": values.get(1)},
            "3": {"imbalance": values.get(3)},
            "5": {"imbalance": values.get(5)},
        }
    }


def test_book_imbalance_primitives_preserve_zero_at_depth_5():
    with patch(
        "order_flow_engine.compute_book_microstructure",
        return_value=_fake_micro({5: 0.0, 3: 0.5, 1: None}),
    ):
        out = OrderFlowEngine().compute({"quote": {}})
    assert out["book_imbalance_5"] == 0.0
    assert out["book_imbalance_3"] == 0.5
    assert out["order_flow_score"] is None


def test_book_imbalance_primitives_when_depth_5_missing():
    with patch(
        "order_flow_engine.compute_book_microstructure",
        return_value=_fake_micro({5: None, 3: 0.5, 1: -0.2}),
    ):
        out = OrderFlowEngine().compute({"quote": {}})
    assert out["book_imbalance_5"] is None
    assert out["book_imbalance_3"] == 0.5
    assert out["book_imbalance_1"] == -0.2
    assert out["order_flow_score"] is None


def test_tape_primitive_preserves_zero_at_2m_window():
    def _tape(_data, window_sec):
        return {120.0: 0.0, 30.0: 0.5, 300.0: None}.get(window_sec)

    with (
        patch(
            "order_flow_engine.compute_book_microstructure",
            return_value=_fake_micro({5: None, 3: None, 1: None}),
        ),
        patch("order_flow_engine._compute_tape_pressure", side_effect=_tape),
    ):
        out = OrderFlowEngine().compute({"quote": {}})
    assert out["tape_pressure_2m"] == 0.0
    assert out["tape_pressure_30s"] == 0.5
    assert out["order_flow_score"] is None


def test_compute_does_not_reconstruct_composite_from_depth_5_zero():
    data = {"content": [{"BIDS": [{"BID_PRICE": 100.0, "TOTAL_VOLUME": 100.0}],
                         "ASKS": [{"ASK_PRICE": 100.05, "TOTAL_VOLUME": 100.0}]}]}
    out = OrderFlowEngine().compute(data)
    assert out["order_flow_score"] is None
    assert out["order_flow_verdict"] is None


def test_no_l2_book_fails_closed_and_never_substitutes_top_of_book_into_book_imbalance_5():
    """Regression lock for the removed REST fallback."""
    data = {"content": [{"BID_PRICE": 100.0, "ASK_PRICE": 100.02,
                         "BID_SIZE": 800, "ASK_SIZE": 200}]}
    out = OrderFlowEngine().compute(data)

    assert out["book_imbalance_1"] is None
    assert out["book_imbalance_3"] is None
    assert out["book_imbalance_5"] is None
    assert out["top_book_pressure"] is not None
    assert abs(out["top_book_pressure"] - 0.6) < 1e-9
    assert out["top_book_pressure_source"] == "schwab_stream"
    assert out["book_imbalance_5"] != out["top_book_pressure"]
    assert out["order_flow_score"] is None
