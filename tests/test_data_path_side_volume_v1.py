"""Schwab -> the strikes payload. A volume Schwab did not send."""

from __future__ import annotations

import live_market_plane as lmp
import server as srv
import time_et
from option_contract import read_chain
from push import strikes as push_strikes
from state import level_store
from tests.feed_live_helper import daemon_status
from tests.real_chains import NFLX


def _published(tk: str, chain: list, spot: float, now) -> dict:
    """Return the strikes route's answer on `chain` as the levels producer publishes it.

    The levels producer is _publish_levels; it publishes at `spot`, with the live price at
    `spot`.
    """
    srv._publish_levels(tk, read_chain(chain), now.timestamp(), chain_spot=(spot, 1.0), now=now)
    lmp.record_feed_heartbeat(
        daemon_status(time_et.now(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
    )
    lmp.record_from_level_one_equity(
        tk, {"LAST_PRICE": spot, "TRADE_TIME_MILLIS": 1000}, received_ts=1.0
    )
    try:
        body = push_strikes.strikes(
            tk, time_et.now(), {"scope": "auto", "centre": None, "shift": 0}
        )
    finally:
        with level_store._lock:
            level_store._levels.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
        lmp.record_feed_down()
    return body


def test_a_volume_not_known_leaves_the_volume_total_unknown():
    """Induced test condition: NFLX's strike above the price with totalVolume removed.

    None is captured unreported.
    """
    above = min(c["strikePrice"] for c in NFLX.chain if c["strikePrice"] > NFLX.spot)
    chain = [
        {k: v for k, v in c.items() if k != "totalVolume" or c["strikePrice"] != above}
        for c in NFLX.chain
    ]
    body = _published(NFLX.ticker, chain, NFLX.spot, NFLX.now)
    assert body["migration"]["all"]["volume_total"] is None
