"""Schwab -> the levels. A missing daemon heartbeat keeps the last streamed volume, not live."""

from __future__ import annotations

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import server
from option_contract import read_chain
from state import level_store
from tests.feed_live_helper import mark_feed_down, repriced
from tests.test_one_levels_producer_v1 import (
    _A,
    _AT,
    _CONTRACTS,
    _SPOT,
    _T,
    TK,
    _cached,
    _daemon,
    _streamed,
)


def test_a_missing_heartbeat_keeps_the_last_streamed_volume_on_the_levels():
    """The daemon named the contract, Schwab sent a volume, then the heartbeat is gone.

    The levels still show that volume and the cell is not live.
    """
    ofls.clear_all_live_state()
    with lmp._lock:
        lmp._beats.clear()
    try:
        _daemon(held=[_A], socket_open=True, at=_T)
        # INDUCED: a volume CRWD's chain does not carry, so the levels show it only from the stream
        _streamed(_A, {"TOTAL_VOLUME": 999999}, _T - 60.0)
        records = read_chain(_CONTRACTS)
        server._publish_levels(TK, records, _T - 120.0, chain_spot=(_SPOT, _T), now=_AT)
        mark_feed_down()
        server._publish_levels(TK, records, _T - 120.0, chain_spot=(_SPOT, _T), now=_AT)
        cached = _cached()
        strike = round(_CONTRACTS[0]["strikePrice"], 2)
        row = next(r for r in cached.snap.per_strike["gex"] if r[0] == strike)
        states = [
            col[side]["state"]
            for cell in cached.gamma_surface["cells"]
            for col, pair in zip(cell["stream"], cell["contracts"], strict=True)
            for side in ("call", "put")
            if col and pair.get(side) == _A
        ]
        assert row[2] >= 999999
        assert repriced(cached) == [_A]
        assert states and "live" not in states
        assert lmp.feed_live_for(_A, "LEVELONE_OPTIONS", _T) is False
    finally:
        ofls.clear_all_live_state()
        with lmp._lock:
            lmp._beats.clear()
        lmp._by_ticker.pop(TK, None)
        lmp._fields_by_ticker.pop(TK, None)
        with level_store._lock:
            level_store._levels.pop(TK, None)
