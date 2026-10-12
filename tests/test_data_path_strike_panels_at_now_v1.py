"""The per-strike panels, Schwab to the screen, at the time asked: a captured chain published by the
levels producer, and every per-strike panel's answer (GEX by strike, the chart's DEX and OI, vanna,
charm) at that time is windowed around the price, whatever the wall clock says (AGENTS.md: a
function that depends on the clock takes `now`).

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET (tests/real_chains.py
CRWD). The daemon's status and CRWD's price row are as the console holds them at that instant.
"""
from __future__ import annotations

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from tests.real_chains import CRWD


def test_every_per_strike_panel_answers_at_the_time_asked_around_the_price():
    tk, at = CRWD.ticker, CRWD.now.timestamp()
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    lmp.record_feed_heartbeat({"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}})
    ofs._price_rows[tk] = {"ticker": tk, "spot": CRWD.spot, "trade_ts": at}
    try:
        server._publish_levels(tk, captures=[{"contracts": CRWD.chain, "ts_utc": at, "spot": CRWD.spot,
                                              "et_date": CRWD.now.date().isoformat(),
                                              "basis": server.CAPTURE_BASIS}], now=CRWD.now)
        strikes = server.terrain_strikes_payload(tk, "auto", None, 0, at)
        assert strikes["spot"] == CRWD.spot and strikes["spot_strike"] is not None
        assert all(v["note"] is None for v in strikes["views"].values() if v["centre"] is not None)
        for key in server.STRIKE_BAR_METHODS:
            bars = server.strike_bar_payload(tk, key, "auto", None, 0, at)
            assert bars["available"] and bars["spot"] == CRWD.spot and bars["view"]["note"] is None, key
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp.record_feed_down()
