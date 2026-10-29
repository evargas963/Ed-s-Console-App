"""Schwab -> the levels. A closed socket keeps the last streamed volume, marked not live."""

from __future__ import annotations

from datetime import datetime

import app.options.order_flow.state as ofls
import server
from tests.test_one_levels_producer_v1 import (
    TK,
    _A,
    _CONTRACTS,
    _SPOT,
    _T,
    _cached,
    _daemon,
    _streamed,
)
from time_et import ET


def test_a_streamed_value_whose_feed_is_down_in_session_still_prices_the_levels():
    """Schwab's socket closed, the daemon still holding the contract: at 11:00 ET the last
    spot and the last streamed volume stand, and the cell is not live. At 22:00 ET the values
    as of the close stand."""
    strike = round(_CONTRACTS[0]["strikePrice"], 2)

    def states(surface):
        return [
            col[side]["state"]
            for cell in surface["cells"]
            for col, pair in zip(cell.get("stream") or [], cell.get("contracts") or [])
            for side in ("call", "put")
            if col and pair.get(side) == _A
        ]

    out = {}
    for at in (datetime(2026, 10, 7, 11, 0, tzinfo=ET), datetime(2026, 10, 7, 22, 0, tzinfo=ET)):
        ofls.clear_all_live_state()
        _daemon(held=[_A], socket_open=False, at=at.timestamp())
        _streamed(_A, {"TOTAL_VOLUME": 999999}, at.timestamp() - 60.0)
        server._publish_levels(
            TK, _CONTRACTS, at.timestamp() - 120.0, chain_spot=(_SPOT, _T), now=at
        )
        out[at.hour] = _cached()
    rth, closed = out[11], out[22]
    rth_row = next(r for r in rth["_per_strike"]["all"] if r[0] == strike)
    closed_row = next(r for r in closed["_per_strike"]["all"] if r[0] == strike)
    assert rth["spot"] == _SPOT and rth["spot_source"] == server.SPOT_SOURCE_PLANE
    assert rth_row[2] >= 999999 and closed_row[2] >= 999999
    assert rth["_gamma_surface"]["stream_overlay_contracts"] >= 1
    rth_states = states(rth["_gamma_surface"])
    assert rth_states and "live" not in rth_states
    assert closed["spot"] == _SPOT
