"""The liquidity panel with and without a live spot: its zones and their distance to it.

Real data through the real producer: Schwab's SPY 1-minute bars of Thursday 2026-10-01 and
Friday 10-02 as the capture daemon recorded them (each minute's newest receipt), the levels
published as the bar writer publishes them, valued on Friday 2026-10-02 at 15:00 ET. Stand-in:
ticker ZZLIQ carries the SPY bars.
"""

from __future__ import annotations

import pytest

import live_market_plane as lmp
import server as srv
from liquidity_models import ZONE_DISPLAY, SnapshotType, ZoneType
from tests.feed_live_helper import daemon_status
from tests.liquidity_friday import FRIDAY, TK, friday_bars


def test_a_ticker_with_no_levels_published_gets_no_zones_and_the_reason():
    """Before the bar writer publishes a ticker's levels, the panel says so and draws no zone."""
    body = srv.liquidity_snapshot("ZZNOLV", FRIDAY)
    assert (body["available"], body["zones"]) == (False, [])
    assert body["reason"] == srv.NO_PRICE_LEVELS_REASON


@pytest.mark.usefixtures("published")
def test_missing_spot_produces_honest_null_distance_through_the_real_zone_path():
    """The real zones of the real levels: with no spot, each zone's distance is absent.

    Not a crash, not a fabricated distance, never VWAP standing in for the spot.
    """
    body = srv.liquidity_snapshot(TK, FRIDAY)
    assert body["zones"]
    lows = [z["zone_low"] for z in body["zones"]]
    assert lows == sorted(lows), "with no spot the zones are listed by price, lowest first"
    for z in body["zones"]:
        assert z["distance_to_spot"] is None
        assert "tradeable_score" not in z, "a score no page reads is not served"
        # the pages named every zone that was not support_liquidity "Resistance": each zone's name
        # and side are served from its type
        assert (z["zone_label"], z["zone_side"]) == ZONE_DISPLAY[ZoneType(z["zone_type"])]


@pytest.mark.usefixtures("published")
def test_with_a_live_spot_the_zones_are_measured_from_schwabs_last_price():
    """The positive control: with Schwab's LAST_PRICE the zones are listed nearest it first.

    Through the daemon's price row to the console (resolve_spot, the one spot authority).
    Stand-in: the last bar's close as the LAST_PRICE Schwab sent.
    """
    last, at = friday_bars()[-1]["close"], FRIDAY.timestamp()
    lmp.record_feed_heartbeat(
        daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [TK]})
    )
    lmp.record_from_level_one_equity(TK, {"LAST_PRICE": last}, received_ts=at)
    body = srv.liquidity_snapshot(TK, FRIDAY)
    distances = [z["distance_to_spot"] for z in body["zones"]]
    assert distances and distances == sorted(distances)
    assert distances[0] == 0.0 and "SPOT_LIVE" in body["zones"][0]["source_tags"]
    assert body["snapshot_type"] == SnapshotType.LIVE.value
