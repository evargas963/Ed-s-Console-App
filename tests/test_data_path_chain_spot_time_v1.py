"""Schwab -> the chain ladder. The spot on the ladder carries Schwab's trade time."""

from __future__ import annotations

import json

import live_market_plane as lmp
import server as srv
from option_contract import read_chain


def test_the_chain_spot_carries_schwabs_trade_time():
    """The ladder's spot is the daemon's last price, and the time on it is that price's trade
    time. A feed that is down does not remove either."""
    tk = "ZZCHAIN"
    exp = "2026-09-11"
    symbol = "SPY   260911C00601000"
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": tk,
            "spot": 600.0,
            "expiries": [exp],
            "_chain": read_chain(
                [
                    {
                        "symbol": symbol,
                        "putCall": "CALL",
                        "strikePrice": 601.0,
                        "expirationDate": exp,
                    }
                ]
            ),
            "_contract_symbols": frozenset([symbol]),
            "_chain_fetched_ts": 1.0,
            "_gamma_surface": None,  # levels with no surface, as _publish_levels writes them
        }
    lmp.record_from_level_one_equity(
        tk,
        {"LAST_PRICE": 601.23, "TRADE_TIME_MILLIS": 1790380799830},
        received_ts=1790380799.83,
    )
    try:
        body = json.loads(bytes(srv.get_chain(ticker=tk, expiry=exp).body))
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
    assert body["spot"] == 601.23
    assert body["spot_as_of_ts_utc"] == 1790380799.83
    assert body["spot_time_ct"] == "Fri 09/25 06:59 PM CT"
    # levels with no surface: this expiry's net GEX is unknown, not an empty list
    assert body["net_gex_by_strike"] is None
