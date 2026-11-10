"""Schwab -> the strikes payload. A side's GEX total, and a volume Schwab did not send."""

from __future__ import annotations

import live_market_plane as lmp
import server as srv
import time_et
from math_exposure_core import compute_exposures_by_strike, net_gex_dollars_at_strike
from option_contract import read_chain
from tests.feed_live_helper import daemon_status
from tests.real_chains import NFLX, SPY_0DTE


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
        body = srv.strikes(tk, time_et.now(), {"scope": "auto", "centre": None, "shift": 0})
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
        lmp.record_feed_down()
    return body


def test_a_strike_of_gex_not_known_leaves_its_side_gex_unknown():
    """NFLX's whole book: Schwab's -999 on strikes below the price leaves their GEX not known.

    So GEX below has no total, and GEX above is the sum of its strikes.
    """
    book = compute_exposures_by_strike(read_chain(NFLX.chain), spot=NFLX.spot, now=NFLX.now)[0]
    below = {k: b for k, b in book.items() if k < NFLX.spot}
    assert any(net_gex_dollars_at_strike(b) is None for b in below.values())
    sums = _published(NFLX.ticker, NFLX.chain, NFLX.spot, NFLX.now)["today_side_sums"]
    assert sums["gex_below"] is None
    assert sums["gex_above"] is not None
    assert sums["gex_above"] == sum(
        net_gex_dollars_at_strike(b) for k, b in book.items() if k > NFLX.spot
    )


def test_a_volume_not_known_leaves_the_volume_total_unknown():
    """Induced test condition: NFLX's strike above the price with totalVolume removed.

    None is captured unreported. The strike's GEX, which Schwab sent, stays in its side.
    """
    above = min(c["strikePrice"] for c in NFLX.chain if c["strikePrice"] > NFLX.spot)
    chain = [
        {k: v for k, v in c.items() if k != "totalVolume" or c["strikePrice"] != above}
        for c in NFLX.chain
    ]
    body = _published(NFLX.ticker, chain, NFLX.spot, NFLX.now)
    assert body["today_side_sums"]["gex_above"] is not None
    assert body["migration"]["all"]["volume_total"] is None


def test_a_side_with_no_strike_has_no_total():
    """SPY's 0DTE chain priced at its 787.5169 print, above every strike.

    Nothing is above the price, so no total, not a 0. Induced test condition: the print and
    chain are of other days.
    """
    sums = _published("SPY", SPY_0DTE.chain, 787.5169, SPY_0DTE.now)["today_side_sums"]
    assert sums["gex_above"] is None
    assert sums["gex_below"] is not None
