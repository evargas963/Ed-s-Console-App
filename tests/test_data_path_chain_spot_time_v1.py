"""Schwab -> the chain ladder. The spot on the ladder carries Schwab's trade time."""

from __future__ import annotations

import json

import live_market_plane as lmp
import server as srv
from option_contract import read_chain
from tests.real_chains import CRWD


def test_the_chain_spot_carries_schwabs_trade_time():
    """The ladder's spot is the daemon's last price, and the time on it is that price's trade
    time. A feed that is down does not remove either. CRWD's real chain, published by the one
    producer (_publish_levels) at its capture."""
    tk = "ZZCHAIN"
    exp = CRWD.chain[0]["expirationDate"][:10]
    srv._publish_levels(
        tk,
        read_chain(CRWD.chain),
        CRWD.now.timestamp(),
        chain_spot=(CRWD.spot, CRWD.now.timestamp()),
        now=CRWD.now,
    )
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
