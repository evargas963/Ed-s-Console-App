"""ONE UI-ready options/order-flow product payload.

Consumes ``OrderFlowEngine.compute`` (the live book + tape authority) and does
not re-walk the book. Tape/CVD fields are PROXY reconstructions — Schwab L1
has no native aggressor.
"""
from __future__ import annotations

from typing import Any

from l1_trade_observation import NATIVE_AGGRESSOR_AVAILABLE, TAPE_CLASSIFICATION
from app.options.order_flow.engine import OrderFlowEngine
import live_market_plane as lmp
from app.options.order_flow.state import get_content_for_symbol, option_top


_FLOW_KEYS = (
    "tape_pressure_30s",
    "tape_pressure_2m",
    "tape_pressure_5m",
    "cum_delta_proxy",
    "cum_delta_slope",
    "top_book_pressure",
)


def flow_block(of: dict[str, Any]) -> dict[str, Any]:
    """The labeled PROXY tape flow out of one OrderFlowEngine.compute result -- the same block
    for an option contract and an equity (Trade Desk Order Flow card)."""
    flow = {k: of.get(k) for k in _FLOW_KEYS}
    p5 = flow.get("tape_pressure_5m")
    # net traded side over 5 minutes, by the pressure's sign (tick rule, PROXY)
    flow["tape_side_5m"] = None if p5 is None else "BUY" if p5 > 0 else "SELL" if p5 < 0 else "EVEN"
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
    return flow


def options_live_payload(contract: str) -> dict[str, Any]:
    """Book microstructure + labeled PROXY flow for one option contract."""
    items = get_content_for_symbol(contract)
    top = option_top(contract) if lmp.feed_live_for(contract) else None
    of = OrderFlowEngine().compute({"content": items or [], "top": top}, ticker=contract)
    book = dict(of.get("book_microstructure") or {})
    book["flow"] = flow_block(of)
    return book
