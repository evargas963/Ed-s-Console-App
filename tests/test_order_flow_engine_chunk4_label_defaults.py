"""order_flow_engine chunk-4: retired composite emits None (RC-454)."""
from __future__ import annotations

from unittest.mock import patch

from math_exposure import order_flow_score_label
from order_flow_engine import OrderFlowEngine


def test_order_flow_score_label_exact_zero_is_none():
    assert order_flow_score_label(0.0) is None
    assert order_flow_score_label(0.05) == "neutral"


def test_compute_always_emits_none_for_retired_composite_family():
    with (
        patch(
            "order_flow_engine.compute_book_microstructure",
            return_value={
                "depth": {
                    "1": {"imbalance": 0.5},
                    "3": {"imbalance": 0.4},
                    "5": {"imbalance": 0.3},
                }
            },
        ),
        patch("order_flow_engine._compute_tape_pressure", return_value=0.4),
        patch("order_flow_engine._compute_cum_delta_proxy", return_value=0.2),
        patch("order_flow_engine._compute_absorption", return_value=(0.1, None, None)),
        patch("order_flow_engine._compute_options_flow", return_value=(0.2, None, None, None, None)),
        patch("order_flow_engine._compute_rvol", return_value=(1.5, None)),
    ):
        out = OrderFlowEngine().compute({"quote": {}})
    assert out["order_flow_score"] is None
    assert out["order_flow_direction"] is None
    assert out["order_flow_regime"] is None
    assert out["order_flow_verdict"] is None
    assert out["book_imbalance_5"] == 0.3
