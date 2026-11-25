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
    assert body["location_said"] is None  # where the price sits is not known: no sentence
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
    first = [s["id"] for s in z["source_levels"]]
    side = (
        "Resistance"
        if z["zone_low"] > last
        else "Support"
        if z["zone_high"] < last
        else "Price inside zone"
    )
    assert z["zone_label"] == side and "SPOT_LIVE" not in first  # typed by side; not a level


def _at_price(price: float) -> dict:
    """Return the panel with `price` as the LAST_PRICE Schwab sent at 15:00 ET (INDUCED)."""
    at = FRIDAY.timestamp()
    lmp.record_feed_heartbeat(
        daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [TK]})
    )
    lmp.record_from_level_one_equity(TK, {"LAST_PRICE": price}, received_ts=at)
    return push_liquidity.liquidity_snapshot(TK, FRIDAY)


def _near(z: dict, side: str, edge: float) -> str:
    return f"{z['zone_label']} zone {side} at {edge:.2f} (levels in zone {z['confluence_score']})"


@pytest.mark.usefixtures("published")
def test_where_the_price_sits_among_the_zones_is_one_sentence():
    """INDUCED: the price put inside a zone, below every zone, above every zone and in a gap.

    The real Friday zones, the sentence worked out from their numbers: inside one, its name, its
    range and how many levels it holds; outside, the nearest zone on each side that has one,
    each with its near edge.
    """
    zones = sorted(_at_price(friday_bars()[-1]["close"])["zones"], key=lambda z: z["zone_low"])
    low, high = zones[0], zones[-1]
    body = _at_price((low["zone_low"] + low["zone_high"]) / 2)
    z = next(z for z in body["zones"] if z["zone_low"] == low["zone_low"])
    assert body["location_said"] == (
        f"Price inside zone ({low['zone_low']:.2f}–{low['zone_high']:.2f}, levels in zone "
        f"{z['confluence_score']})"
    )
    body = _at_price(low["zone_low"] - 1.0)
    z = next(z for z in body["zones"] if z["zone_low"] == low["zone_low"])
    assert body["location_said"] == "Between zones — " + _near(z, "above", low["zone_low"])
    body = _at_price(high["zone_high"] + 1.0)
    z = next(z for z in body["zones"] if z["zone_low"] == high["zone_low"])
    assert body["location_said"] == "Between zones — " + _near(z, "below", high["zone_high"])
    gaps = [(a, b) for a, b in zip(zones, zones[1:]) if a["zone_high"] < b["zone_low"]]
    assert gaps, "the Friday zones leave a gap between two of them"
    a, b = gaps[0]
    body = _at_price((a["zone_high"] + b["zone_low"]) / 2)
    za = next(z for z in body["zones"] if z["zone_low"] == b["zone_low"])
    zb = next(z for z in body["zones"] if z["zone_low"] == a["zone_low"])
    assert body["location_said"] == (
        "Between zones — "
        + _near(za, "above", b["zone_low"])
        + ", "
        + _near(zb, "below", a["zone_high"])
    )
