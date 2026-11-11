"""Schwab -> the chain ladder. The spot on the ladder carries Schwab's trade time."""

from __future__ import annotations

import live_market_plane as lmp
import server as srv
import time_et
from option_contract import read_chain
from tests.real_chains import CRWD


def test_the_chain_spot_carries_schwabs_trade_time():
    """The ladder's spot is the daemon's last price, and the time on it is its trade time.

    The time on it is that price's trade time. A feed that is down does not remove either.
    CRWD's real chain, published by the one producer (_publish_levels) as captured.
    """
    tk = "ZZCHAIN"
    exp = CRWD.chain[0]["expirationDate"][:10]
    # delivered with no price held: levels with no surface, as _publish_levels writes them
    srv._publish_levels(
        tk, read_chain(CRWD.chain), CRWD.now.timestamp(), chain_spot=(None, None), now=CRWD.now
    )
    lmp.record_from_level_one_equity(
        tk,
        {"LAST_PRICE": 601.23, "TRADE_TIME_MILLIS": 1790380799830},
        received_ts=1790380799.83,
    )
    try:
        body = srv.chain(tk, time_et.now(), {"expiry": exp})
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
    assert body["spot"] == 601.23
    # Schwab's trade time is served once, as the text the page shows: no second, raw copy
    assert "spot_as_of_ts_utc" not in body
    assert body["spot_time_ct"] == "Fri 09/25 06:59 PM CT"
    # levels with no surface: this expiry's net GEX is unknown, not an empty list
    assert body["net_gex_by_strike"] is None
