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
from calc.liquidity_models import ZONE_DISPLAY
from push import levels as push_levels
from push import liquidity as push_liquidity
from state import price_level_store
from tests.feed_live_helper import daemon_status
from tests.liquidity_friday import FRIDAY, TK, friday_bars


def test_a_ticker_with_no_levels_published_gets_no_zones_and_the_reason():
    """Before the bar writer publishes a ticker's levels, the panel says so and draws no zone."""
    body = push_liquidity.liquidity_snapshot("ZZNOLV", FRIDAY)
    assert (body["available"], body["zones"]) == (False, [])
    assert body["reason"] == push_levels.NO_PRICE_LEVELS_REASON
    assert "no_zones_text" not in body  # the reason is what the list says


def test_levels_published_with_none_in_them_are_answered_with_the_lists_words():
    """A ticker with no bar and no daily candle held, its levels published as a start does.

    Every family of them is absent, so no level makes a zone: the answer is the available one
    with an empty list, and it carries the words the map's zone list draws for that (the page
    holds no such sentence). Stand-in: ticker ZZNONE, which Schwab has sent nothing for.
    """
    tk = "ZZNONE"
    try:
        srv._publish_missing_price_levels([tk], FRIDAY)  # as the levels loop does at a start
        body = push_liquidity.liquidity_snapshot(tk, FRIDAY)
    finally:
        for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del price_level_store._MATERIALIZED_SNAPSHOTS[key]
        price_level_store._HOLD_COUNTS.pop(tk, None)
    assert "available" not in body and body["zones"] == []
    assert body["no_zones_text"] == "no zones for this session yet"


@pytest.mark.usefixtures("published")
def test_missing_spot_produces_honest_null_distance_through_the_real_zone_path():
    """The real zones of the real levels: with no spot, each zone's distance is absent.

    Not a crash, not a fabricated distance, never VWAP standing in for the spot.
    """
    body = push_liquidity.liquidity_snapshot(TK, FRIDAY)
    assert body["zones"]
    assert body["no_zones_text"] is None  # a list with a zone has no words for none
    lows = [z["zone_low"] for z in body["zones"]]
    assert lows == sorted(lows), "with no spot the zones are listed by price, lowest first"
    for z in body["zones"]:
        assert "distance_to_spot" not in z, "the order is served, not a distance no page reads"
        assert "tradeable_score" not in z, "a score no page reads is not served"
        # the pages named every zone that was not support_liquidity "Resistance": each zone's name
        # and side are served from its type
        assert (z["zone_label"], z["zone_side"]) in set(ZONE_DISPLAY.values())


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
    body = push_liquidity.liquidity_snapshot(TK, FRIDAY)
    distances = [
        push_liquidity._distance_to_spot(z["zone_low"], z["zone_high"], last) for z in body["zones"]
    ]
    assert distances and distances == sorted(distances)
    z = body["zones"][0]
    first = [s["label"] for s in z["source_levels"]]
    side = (
        "Resistance"
        if z["zone_low"] > last
        else "Support"
        if z["zone_high"] < last
        else "Pivot / value"
    )
    assert z["zone_label"] == side and "SPOT_LIVE" not in first  # typed by side; not a level
