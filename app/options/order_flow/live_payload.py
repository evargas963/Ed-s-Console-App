"""ONE UI-ready options/order-flow product payload.

Consumes ``OrderFlowEngine.compute`` (the live book + tape authority) and does
not re-walk the book. Tape/CVD fields are PROXY reconstructions — Schwab L1
has no native aggressor.
"""

from __future__ import annotations

from typing import Any

import live_market_plane as lmp
from app.options.order_flow.state import get_content_for_symbol, option_top
from calc.l1_trade_observation import TAPE_NOTE
from calc.order_flow import OrderFlowEngine


def flow_block(of: dict[str, Any]) -> dict[str, Any]:
    """Return the labeled PROXY tape flow out of one OrderFlowEngine.compute result.

    Every flow number the engine computed, each with its text, and the window the cumulative
    delta sums: the result but its book. It is the same block for an option contract and an
    equity (Trade Desk Order Flow card).
    """
    flow = {k: v for k, v in of.items() if k != "book_microstructure"}
    flow["classification"] = {
        "tape_pressure_30s": "PROXY",
        "tape_pressure_2m": "PROXY",
        "tape_pressure_5m": "PROXY",
        "cum_delta_proxy": "PROXY",
        "cum_delta_slope": "PROXY",
        "top_book_pressure": "DERIVED",
    }
    flow["estimate_note"] = TAPE_NOTE
    return flow


def options_live_payload(contract: str, now: float) -> dict[str, Any]:
    """Book microstructure + labeled PROXY flow for one option contract at `now`."""
    items = get_content_for_symbol(contract)
    # the contract's top of book stands when it is not live; top_outage says why and
    # top_feed_label is the page's word for it. book_live is whether the book feed delivers now
    # (docs/DATA_FLOW.md §2 D5).
    # QUOTE_TIME_MILLIS stays on the top; the book ages from that clock.
    top = option_top(contract)
    quote_ms = top.get("quote_time_ms") if isinstance(top, dict) else None
    top_label, top_outage = lmp.live_state(contract, "LEVELONE_OPTIONS", now)
    of = OrderFlowEngine().compute(
        {
            "content": items,
            "top": top,
            "book_live": lmp.feed_live_for(contract, "OPTIONS_BOOK", now),
            "exchange_quote_ts": quote_ms / 1000.0 if quote_ms is not None else None,
        },
        now=now,
    )
    book = dict(of["book_microstructure"])
    book["flow"] = flow_block(of)
    book["top_outage"], book["top_feed_label"] = top_outage, top_label
    return book
