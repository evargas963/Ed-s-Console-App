"""ONE UI-ready options/order-flow product payload.

Consumes ``OrderFlowEngine.compute`` (the live book + tape authority) and does
not re-walk the book. Tape/CVD fields are PROXY reconstructions — Schwab L1
has no native aggressor.
"""
from __future__ import annotations

from typing import Any

from l1_trade_observation import NATIVE_AGGRESSOR_AVAILABLE, TAPE_CLASSIFICATION
from order_flow_engine import OrderFlowEngine
from order_flow_live_state import get_content_for_symbol


_FLOW_KEYS = (
    "tape_pressure_30s",
    "tape_pressure_2m",
    "tape_pressure_5m",
    "cum_delta_proxy",
    "cum_delta_slope",
    "top_book_pressure",
)


def options_live_payload(contract: str, *, content: list | None = None) -> dict[str, Any]:
    """Book microstructure + labeled PROXY flow for one option contract."""
    items = content if content is not None else get_content_for_symbol(contract)
    of = OrderFlowEngine().compute({"content": items or []}, ticker=contract)
    book = dict(of.get("book_microstructure") or {})
    flow = {k: of.get(k) for k in _FLOW_KEYS}
    flow["classification"] = {
        "tape_pressure_30s": "PROXY",
        "tape_pressure_2m": "PROXY",
        "tape_pressure_5m": "PROXY",
        "cum_delta_proxy": "PROXY",
        "cum_delta_slope": "PROXY",
        "top_book_pressure": "DERIVED",
    }
    flow["tape_classification"] = TAPE_CLASSIFICATION
    flow["native_aggressor_available"] = NATIVE_AGGRESSOR_AVAILABLE
    book["flow"] = flow
    return book
