"""Action 11.2: order-flow verdict path fail-closed when chain inputs absent."""

from __future__ import annotations

from dataclasses import fields

from market_state import MarketState
from math_exposure import (
    compute_order_flow_verdict,
    order_flow_book_label,
    order_flow_opt_label,
    _book_direction,
)
from order_flow_engine import OrderFlowEngine


def test_compute_order_flow_verdict_all_none_is_unavailable():
    out = compute_order_flow_verdict(None, None, None, None)
    assert out["verdict"] is None
    assert out["verdict_color"] is None
    assert out["arrow"] is None
    assert out["agreement"] == "unavailable"


def test_compute_order_flow_verdict_with_score_only_not_flow_neutral_default():
    out = compute_order_flow_verdict(0.5, None, None, None)
    assert out["verdict"] is not None
    assert out["verdict"] != ""


def test_order_flow_engine_empty_result_no_flow_neutral():
    eng = OrderFlowEngine()
    out = eng._empty_result()
    assert out["order_flow_verdict"] is None
    assert out["order_flow_direction"] is None
    assert out["order_flow_agreement"] == "unavailable"


def test_market_state_order_flow_verdict_defaults_none():
    ms = MarketState()
    assert ms.order_flow_verdict is None
    assert ms.order_flow_verdict_color is None
    assert ms.order_flow_direction is None
    assert ms.order_flow_score_label is None


def test_book_and_opt_label_helpers_return_none_on_bad_coercion():
    assert _book_direction("not-a-number") is None
    assert order_flow_book_label("bad") is None
    assert order_flow_opt_label("bad") is None


def test_market_state_unpopulated_verdict_fields_none():
    f = {fld.name: fld for fld in fields(MarketState)}
    for name in (
        "order_flow_verdict",
        "order_flow_verdict_color",
        "order_flow_arrow",
        "order_flow_agreement",
        "order_flow_score_label",
        "order_flow_book_label",
        "order_flow_opt_label",
    ):
        assert f[name].default is None
