"""The `contract` panel: the Flow view's one option contract, its book, tape and stream state.

Read from State: the contract's book and prints (the order-flow state), its chain record
(state.level_store) and whether the daemon streams it.
"""

from __future__ import annotations

from typing import Any

from app.options.order_flow.live_payload import ContractFlow, options_live_payload
from app.options.order_flow.streaming import (
    StreamingPlane,
    get_option_contract_streaming_diagnostics,
)
from instrument_identity import ticker_storage_key
from numeric_contract import strike_text
from push.book import BookTimes, book_times
from state import level_store
from state.level_store import published_levels


class ContractPanel(ContractFlow, BookTimes):
    """The `contract` panel (options_microstructure).

    The contract's book and flow, then the contract asked, its side, strike and expiry from its
    chain record (None while no chain the console holds lists it), whether the daemon streams
    it and is receiving it, and the two clocks as the screen shows them (BookTimes).
    """

    contract: str
    put_call: str | None
    strike_text: str | None
    expiry: str | None
    streaming_plane: StreamingPlane


def contract_asked(params: dict[str, Any]) -> str:
    """Return the option contract a panel's `params` name; none named raises.

    `contract` is a chain answer's own "symbol" (OSI, e.g. "SPY   260820C00767000"), served as the
    console holds it for that literal string (options_microstructure).
    """
    symbol = params.get("contract")
    if type(symbol) is not str or not symbol.strip():
        raise ValueError("contract is required")
    return symbol.strip()


def options_microstructure(c: str, now: float) -> ContractPanel:
    """Return the Flow panel's payload for contract `c` at `now`, judged by the one live rule."""
    live = options_live_payload(ticker_storage_key(c), now)
    # the side, strike and expiry of the contract's chain record, the header's; None while no
    # chain the console holds lists it
    tk = level_store.listing_ticker(c)
    listing = None if tk is None else published_levels(tk)
    record = None if listing is None else listing.contracts[c]
    return {
        **live,
        "contract": c,
        "put_call": None if record is None else record.side,
        "strike_text": None if record is None else strike_text(record.strike),
        "expiry": None if record is None else record.expiry,
        # whether the daemon streams this contract (the option rule) and is receiving it
        "streaming_plane": get_option_contract_streaming_diagnostics(c, now),
        **book_times(live["provenance"], live["ages"]),
    }
