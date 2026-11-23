"""Schwab -> the chain ladder. The price beside it is the price row's, with its trade time."""

from __future__ import annotations

import live_market_plane as lmp
import live_price_rows
import server as srv
import time_et
from option_contract import read_chain
from push import chain as push_chain
from state import level_store
from tests.real_chains import CRWD


def test_the_chain_spot_carries_schwabs_trade_time():
    """The price the chain's head shows is the daemon's price row, with that price's trade time.

    One producer: the price row alone carries the price and its trade time, which the page draws
    on the chain's head; the chain serves no copy of either. A feed that is down does not remove
    either. CRWD's real chain, published by the one producer (_publish_levels) as captured.
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
        now = time_et.now()
        body = push_chain.chain(tk, now, {"expiry": exp})
        row = live_price_rows.price_row(tk, now)
    finally:
        with level_store._lock:
            level_store._levels.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
    # Schwab's last trade and its time are the price row's, as the texts the page shows
    assert (row["spot_disp"], row["trade_time_ct"]) == ("601.23", "Fri 09/25 06:59 PM CT")
    copies = {"spot", "spot_text", "spot_time_ct", "spot_strike", "spot_as_of_ts_utc"}
    assert not copies & set(body), copies & set(body)
    # levels with no surface: this expiry's net GEX is unknown, not an empty list
    assert body["ladder"] and all(r["net_gex"] is None for r in body["ladder"])
