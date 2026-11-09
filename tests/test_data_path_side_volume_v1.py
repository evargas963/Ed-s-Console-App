"""Schwab -> the strikes payload. Volume below and above spot keeps every digit."""

from __future__ import annotations

import json

import live_market_plane as lmp
import server as srv
import time_et
from math_exposure_core import (
    compute_exposures_by_strike,
    net_gex_dollars_at_strike,
    strike_total_volume,
)
from option_contract import read_chain
from tests.feed_live_helper import daemon_status
from tests.real_chains import NFLX, SPY_0DTE


def _published(tk: str, chain: list, spot: float, now) -> dict:
    """The strikes route's answer on `chain` as the levels producer (_publish_levels) publishes
    it, at `spot`, with the live price at `spot`.
    """
    srv._publish_levels(tk, read_chain(chain), now.timestamp(), chain_spot=(spot, 1.0), now=now)
    lmp.record_feed_heartbeat(
        daemon_status(time_et.now(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
    )
    lmp.record_from_level_one_equity(
        tk, {"LAST_PRICE": spot, "TRADE_TIME_MILLIS": 1000}, received_ts=1.0
    )
    try:
        resp = srv.get_terrain_strikes(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
        lmp.record_feed_down()
    return json.loads(bytes(resp.body))


def test_volume_below_and_above_spot_keeps_every_digit():
    """NFLX's whole book: the strikes below spot and the strikes above it are summed as Schwab
    sent them, every contract's volume, against the payload's own spot; cutting the total to a
    whole number happens on the screen, not in the sum.
    """
    book = compute_exposures_by_strike(read_chain(NFLX.chain), spot=NFLX.spot, now=NFLX.now)[0]
    sums = _published(NFLX.ticker, NFLX.chain, NFLX.spot, NFLX.now)["today_side_sums"]
    volume = {k: strike_total_volume(b) for k, b in book.items()}
    assert sums["vol_below"] == sum(v for k, v in volume.items() if k < NFLX.spot)
    assert sums["vol_above"] == sum(v for k, v in volume.items() if k > NFLX.spot)
    assert sums["spot_basis"] == NFLX.spot


def test_a_strike_of_gex_not_known_leaves_its_side_gex_unknown_and_its_volume_in():
    """NFLX's whole book: Schwab's -999 on strikes below the price leaves their GEX not known, so
    GEX below has no total, and their volume, which Schwab sent, stays in the volume below.
    """
    book = compute_exposures_by_strike(read_chain(NFLX.chain), spot=NFLX.spot, now=NFLX.now)[0]
    below = {k: b for k, b in book.items() if k < NFLX.spot}
    assert any(net_gex_dollars_at_strike(b) is None for b in below.values())
    sums = _published(NFLX.ticker, NFLX.chain, NFLX.spot, NFLX.now)["today_side_sums"]
    assert sums["gex_below"] is None
    assert sums["gex_above"] is not None
    assert sums["vol_below"] == sum(strike_total_volume(b) for b in below.values())


def test_a_volume_not_known_leaves_its_side_with_no_total():
    """Induced test condition: NFLX's strike above the price with totalVolume removed, none being
    captured unreported.
    """
    above = min(c["strikePrice"] for c in NFLX.chain if c["strikePrice"] > NFLX.spot)
    chain = [
        {k: v for k, v in c.items() if k != "totalVolume" or c["strikePrice"] != above}
        for c in NFLX.chain
    ]
    body = _published(NFLX.ticker, chain, NFLX.spot, NFLX.now)
    assert body["today_side_sums"]["vol_above"] is None
    assert body["migration"]["all"]["volume_total"] is None


def test_a_side_with_no_strike_has_no_total():
    """SPY's 0DTE chain priced at its 787.5169 print, above every strike: nothing is above the
    price, so no total, not a 0. Induced test condition: the print and chain are of other days.
    """
    sums = _published("SPY", SPY_0DTE.chain, 787.5169, SPY_0DTE.now)["today_side_sums"]
    assert sums["gex_above"] is None and sums["vol_above"] is None
    assert sums["gex_below"] is not None and sums["vol_below"] is not None
