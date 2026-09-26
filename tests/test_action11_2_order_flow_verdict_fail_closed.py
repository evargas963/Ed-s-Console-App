"""Order-flow engine: an empty result carries no verdict and no direction."""

from __future__ import annotations

from app.options.order_flow.engine import OrderFlowEngine


def test_order_flow_engine_empty_result_no_flow_neutral():
    eng = OrderFlowEngine()
    out = eng._empty_result()
    assert out["order_flow_verdict"] is None
    assert out["order_flow_direction"] is None
    assert out["order_flow_agreement"] == "unavailable"
