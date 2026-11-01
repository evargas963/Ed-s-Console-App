"""Schwab -> the strikes payload. Volume below and above spot keeps every digit."""

from __future__ import annotations

import json
import time

import live_market_plane as lmp
import server as srv
from app.options.order_flow import streaming as ofs
from math_exposure_core import (
    compute_exposures_by_strike,
    net_gex_dollars_at_strike,
    strike_total_volume,
)
from terrain_engine import compute_terrain
from tests.real_chains import NFLX, SPY_0DTE


def test_volume_below_and_above_spot_keeps_every_digit():
    """The strikes below spot and the strikes above it are summed as Schwab sent them. Cutting
    the total to a whole number happens on the screen, not in the sum."""
    tk = "ZZSIDE"
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_per_strike": {"all": [[95.0, 10.0, 10.4], [105.0, -4.0, 3.2]], "near": [], "far": []},
            "spot": 100.0,
            "computed_ts_utc": 1.0,
        }
    lmp.record_feed_heartbeat(
        {"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}}
    )
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


def _published(tk: str, chain: list, spot: float, now) -> dict:
    """The strikes route's answer on `chain` as the levels producer publishes it, at `spot`."""
    snap = compute_terrain(tk, chain, spot, now=now)
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_per_strike": snap.per_strike,
            "spot": spot,
            "computed_ts_utc": 1.0,
        }
    lmp.record_feed_heartbeat(
        {"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}}
    )
    ofs._price_rows[tk] = {"ticker": tk, "spot": spot, "trade_ts": 1.0}
    try:
        resp = srv.get_terrain_strikes(ticker=tk)
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp.record_feed_down()
    return json.loads(bytes(resp.body))


def test_a_strike_of_gex_not_known_leaves_its_side_gex_unknown_and_its_volume_in():
    """NFLX's whole book: Schwab's -999 on strikes below the price leaves their GEX not known, so
    GEX below has no total, and their volume, which Schwab sent, stays in the volume below."""
    book = compute_exposures_by_strike(NFLX.chain, spot=NFLX.spot, now=NFLX.now)[0]
    below = {k: b for k, b in book.items() if k < NFLX.spot}
    assert any(net_gex_dollars_at_strike(b) is None for b in below.values())
    sums = _published(NFLX.ticker, NFLX.chain, NFLX.spot, NFLX.now)["today_side_sums"]
    assert sums["gex_below"] is None
    assert sums["gex_above"] is not None
    assert sums["vol_below"] == sum(strike_total_volume(b) for b in below.values())


def test_a_volume_not_known_leaves_its_side_with_no_total():
    """Induced test condition: NFLX's strike above the price with totalVolume removed, none being
    captured unreported."""
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
    price, so no total, not a 0. Induced test condition: the print and chain are of other days."""
    sums = _published("SPY", SPY_0DTE.chain, 787.5169, SPY_0DTE.now)["today_side_sums"]
    assert sums["gex_above"] is None and sums["vol_above"] is None
    assert sums["gex_below"] is not None and sums["vol_below"] is not None
