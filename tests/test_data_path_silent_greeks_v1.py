"""Schwab -> the levels. A missing daemon heartbeat keeps the last streamed volume, not live."""

from __future__ import annotations

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
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
    """The daemon named the contract, Schwab sent a volume, then the heartbeat is gone: the
    levels still show that volume and the cell is not live."""
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    with lmp._lock:
        lmp._feed["held"] = {}
    try:
        _daemon(held=[_A], socket_open=True, at=_T)
        _streamed(_A, {"TOTAL_VOLUME": 999999}, _T - 60.0)
        server._publish_levels(TK, _CONTRACTS, _T - 120.0, chain_spot=(_SPOT, _T), now=_AT)
        lmp.record_feed_down()
        server._publish_levels(TK, _CONTRACTS, _T - 120.0, chain_spot=(_SPOT, _T), now=_AT)
        cached = _cached()
        strike = round(_CONTRACTS[0]["strikePrice"], 2)
        row = next(r for r in cached["_per_strike"]["all"] if r[0] == strike)
        states = [
            col[side]["state"]
            for cell in cached["_gamma_surface"]["cells"]
            for col, pair in zip(cell.get("stream") or [], cell.get("contracts") or [])
            for side in ("call", "put")
            if col and pair.get(side) == _A
        ]
        assert row[2] >= 999999
        assert cached["_gamma_surface"]["stream_overlay_contracts"] >= 1
        assert states and "live" not in states
        assert lmp.feed_live_for(_A, "LEVELONE_OPTIONS", _T) is False
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
        with lmp._lock:
            lmp._feed["held"] = {}
        ofs._price_rows.pop(TK, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(TK, None)
