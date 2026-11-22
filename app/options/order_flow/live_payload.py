"""ONE UI-ready options/order-flow product payload.

One option contract's book microstructure (calc.order_flow.compute_book_microstructure) and its
tape flow (OrderFlowEngine.compute), each from its one producer; nothing here re-walks the book.
Tape/CVD fields are PROXY reconstructions — Schwab L1 has no native aggressor.
"""

from __future__ import annotations

import live_market_plane as lmp
from app.options.order_flow.state import newest_book, option_top, prints
from calc.l1_trade_observation import TAPE_NOTE
from calc.order_flow import (
    BookMicrostructure,
    EngineFlow,
    FlowInput,
    OrderFlowEngine,
    compute_book_microstructure,
)


class FlowBlock(EngineFlow):
    """The labeled tape flow of one symbol (flow_block).

    The engine's flow numbers, then each number's kind (PROXY: estimated from the tape; DERIVED:
    computed from Schwab's sizes) and the note that says what the estimate is.
    """

    classification: dict[str, str]
    estimate_note: str


class ContractFlow(BookMicrostructure):
    """One option contract's book and flow (options_live_payload).

    The engine's microstructure of its OPTIONS_BOOK, then its flow block and the page's words
    for the state of its top of book.
    """

    flow: FlowBlock
    top_outage: str | None
    top_feed_label: str


def flow_block(of: EngineFlow) -> FlowBlock:
    """Return the labeled PROXY tape flow of one OrderFlowEngine.compute result.

    Every flow number the engine computed, each with its text, and the window the cumulative
    delta sums; then each number's kind and what the estimate is.
    """
    return {
        **of,
        "classification": {
            "tape_pressure_30s": "PROXY",
            "tape_pressure_2m": "PROXY",
            "tape_pressure_5m": "PROXY",
            "cum_delta_proxy": "PROXY",
            "cum_delta_slope": "PROXY",
            "top_book_pressure": "DERIVED",
        },
        "estimate_note": TAPE_NOTE,
    }


def options_live_payload(contract: str, now: float) -> ContractFlow:
    """Book microstructure + labeled PROXY flow for one option contract at `now`."""
    # the contract's top of book stands when it is not live; top_outage says why and
    # top_feed_label is the page's word for it. book_live is whether the book feed delivers now
    # (docs/DATA_FLOW.md §2 D5).
    # QUOTE_TIME_MILLIS stays on the top; the book ages from that clock.
    top = option_top(contract)
    quote_ms = top.quote_time_ms
    top_label, top_outage = lmp.live_state(contract, "LEVELONE_OPTIONS", now)
    data = FlowInput(
        book=newest_book(contract, "OPTIONS_BOOK"),
        top=top,
        prints=prints(contract),
        book_live=lmp.feed_live_for(contract, "OPTIONS_BOOK", now),
        exchange_quote_ts=quote_ms / 1000.0 if quote_ms is not None else None,
    )
    return {
        **compute_book_microstructure(data, now_ts=now),
        "flow": flow_block(OrderFlowEngine().compute(data, now=now)),
        "top_outage": top_outage,
        "top_feed_label": top_label,
    }
