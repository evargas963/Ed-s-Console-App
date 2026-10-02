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
    "cum_delta_window",
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


def options_live_payload(contract: str, now: float) -> dict[str, Any]:
    """Book microstructure + labeled PROXY flow for one option contract at `now`."""
    items = get_content_for_symbol(contract)
    # the contract's top of book: absent with the outage reason when its feed is down in an open
    # session, the values as of the close while Closed (docs/DATA_FLOW.md §2 D5); whether the
    # book feed delivers now is book_live
    top_outage = lmp.outage(contract, "LEVELONE_OPTIONS", now)
    of = OrderFlowEngine().compute({"content": items,
                                    "top": option_top(contract) if top_outage is None else None,
                                    "book_live": lmp.feed_live_for(contract, "OPTIONS_BOOK")},
                                   now=now, ticker=contract)
    book = dict(of["book_microstructure"])
    book["flow"] = flow_block(of)
    book["top_outage"] = top_outage
    return book
