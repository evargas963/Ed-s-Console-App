"""Action 11.2: retired order-flow verdict stays fail-closed (RC-454)."""
from __future__ import annotations

from dataclasses import fields

from market_state import MarketState
from math_exposure import (
    order_flow_book_label,
    order_flow_opt_label,
    _book_direction,
)
from order_flow_engine import OrderFlowEngine
import math_exposure as me


def test_compute_order_flow_verdict_is_deleted():
    assert not hasattr(me, "compute_order_flow_verdict")


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
