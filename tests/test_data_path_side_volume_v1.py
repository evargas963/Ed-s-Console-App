"""Schwab -> the strikes payload. Volume below and above spot keeps every digit."""
from __future__ import annotations

import json
import time

import live_market_plane as lmp
import server as srv
from app.options.order_flow import streaming as ofs


def test_volume_below_and_above_spot_keeps_every_digit():
    """The strikes below spot and the strikes above it are summed as Schwab sent them. Cutting
    the total to a whole number happens on the screen, not in the sum."""
    tk = "ZZSIDE"
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_per_strike": {"all": [[95.0, 10.0, 10.4], [105.0, -4.0, 3.2]],
                            "near": [], "far": []},
            "spot": 100.0, "computed_ts_utc": 1.0,
        }
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [tk]}})
    ofs._price_rows[tk] = {"ticker": tk, "spot": 100.0, "trade_ts": 1.0}
    try:
        resp = srv.get_terrain_strikes(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp.record_feed_down()
    sums = json.loads(bytes(resp.body))["today_side_sums"]
    assert sums["vol_below"] == 10.4
    assert sums["vol_above"] == 3.2
    assert sums["spot_basis"] == 100.0
