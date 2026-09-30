"""The zones and the value context (liquidity_value_engine.build_zones / value_context) and the
route that serves them, on SPY's real 1-minute bars of 2026-09-24 and 2026-09-25
(tests/fixtures/real_spy_1m_bars_2026_09_24_25.json) and TSLA's real Schwab quote
(tests/fixtures/real_equity_book.json)."""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import liquidity_value_engine as lve
import live_market_plane as lmp
import server as srv
from liquidity_models import PlaybookConfig, ZoneType
from liquidity_value_engine import _bars_to_list, build_price_level_snapshot, build_zones, value_context
from tests.feed_live_helper import SESSION_NOW, feed_live_during, publish_daemon_rows

_FX = Path(__file__).resolve().parent / "fixtures"
BARS = json.loads((_FX / "real_spy_1m_bars_2026_09_24_25.json").read_text(encoding="utf-8"))["bars"]
FRIDAY = date(2026, 9, 25)
#: stand-in (named) for the live price: the close of the fixture's last bar
LAST = BARS[-1]["close"]


@pytest.fixture
def snap():
    return build_price_level_snapshot("SPY", FRIDAY, _bars_to_list(BARS), bar_source="price_bars_1m", generation=1)


def _zones(snap, spot, extra=()):
    return build_zones(snap, PlaybookConfig(max_zone_width=srv.ZONE_MAX_WIDTH_DOLLARS), spot=spot,
                       extra_levels=list(extra))


def _tags(z):
    return {s["label"] for s in z.source_levels}


def test_a_zone_is_support_below_the_price_and_resistance_above_it(snap):
    """2026-09-30 audit: a zone's side came from what its levels are called, so the prior-day
    high's zone read Resistance with the price above it. SPY closed 2026-09-25 at 771.30, above
    its prior-day high (768.95): that zone is below the price and is support."""
    assert snap.price("PDH") < LAST < snap.price("TODAY_VAH")
    by_type = {z.zone_type: z for z in _zones(snap, LAST)}
    pdh_zone = next(z for z in _zones(snap, LAST) if "PDH" in _tags(z))
    assert pdh_zone.zone_high < LAST and pdh_zone.zone_type is ZoneType.SUPPORT_LIQUIDITY
    assert _tags(by_type[ZoneType.RESISTANCE_LIQUIDITY]) == {"TODAY_VAH"}
    for z in _zones(snap, LAST):
        if z.zone_type is ZoneType.SUPPORT_LIQUIDITY:
            assert z.zone_high < LAST
        if z.zone_type is ZoneType.RESISTANCE_LIQUIDITY:
            assert z.zone_low > LAST
    # the zone the price is inside has no side
    inside = [z for z in _zones(snap, LAST) if z.zone_low <= LAST <= z.zone_high]
    assert [z.zone_type for z in inside] == [ZoneType.STRUCTURE]
    # nearest the price first
    assert _zones(snap, LAST)[0] is inside[0] or _zones(snap, LAST)[0].zone_low <= LAST <= _zones(snap, LAST)[0].zone_high


def test_with_no_live_price_no_zone_has_a_side(snap):
    zones = _zones(snap, None)
    assert zones and {z.zone_type for z in zones} <= {ZoneType.STRUCTURE, ZoneType.PIVOT_VALUE}
    assert [z.zone_high for z in zones] == sorted((z.zone_high for z in zones), reverse=True)


def test_the_live_price_is_never_a_level(snap):
    """2026-09-30 audit: the live price was clustered in as a level, so it made (or joined) a zone
    around itself and the price always read as inside a zone. A price between two zones is
    between them, and the zones are the same zones at any price."""
    between = 766.5                                  # stand-in (named): between PD_VAL 765.59 and PD_POC 767.59
    assert not any(z.zone_low <= between <= z.zone_high for z in _zones(snap, between))
    spans = {(z.zone_low, z.zone_high) for z in _zones(snap, None)}
    assert {(z.zone_low, z.zone_high) for z in _zones(snap, between)} == spans
    assert {(z.zone_low, z.zone_high) for z in _zones(snap, LAST)} == spans
    assert not any("SPOT" in t for z in _zones(snap, LAST) for t in _tags(z))


def test_a_zone_of_value_levels_only_is_a_pivot_on_either_side(snap):
    """A point of control, the prior close or max pain bounds nothing: its zone is a pivot below
    the price and above it. Stand-ins (named): a prior close and a max pain far from every
    session level."""
    extra = [(750.0, "PDC"), (790.0, "MAX_PAIN")]
    alone = {frozenset(_tags(z)): z.zone_type for z in _zones(snap, LAST, extra)}
    assert alone[frozenset({"PDC"})] is ZoneType.PIVOT_VALUE
    assert alone[frozenset({"MAX_PAIN"})] is ZoneType.PIVOT_VALUE
    # a call wall is a bound: resistance above the price, support once the price is above it
    wall = [(790.0, "GAMMA_CALL_WALL")]
    assert {frozenset(_tags(z)): z.zone_type for z in _zones(snap, LAST, wall)}[
        frozenset({"GAMMA_CALL_WALL"})] is ZoneType.RESISTANCE_LIQUIDITY
    assert {frozenset(_tags(z)): z.zone_type for z in _zones(snap, 800.0, wall)}[
        frozenset({"GAMMA_CALL_WALL"})] is ZoneType.SUPPORT_LIQUIDITY


def test_the_vwap_is_placed_against_the_value_area_not_the_point_of_control(snap):
    """2026-09-30 audit: "above / below value" compared the VWAP with the point of control
    +/-0.1%. On 2026-09-25 SPY's VWAP (769.98) sat inside its value area (769.17 to 772.22) and
    0.13% under its POC (770.98): it read "below value". It is at value."""
    vwap, poc = snap.price("VWAP"), snap.price("TODAY_POC")
    assert snap.price("TODAY_VAL") < vwap < snap.price("TODAY_VAH") and vwap < poc * 0.999
    ctx = value_context(snap)
    assert (ctx.vwap_relation, ctx.vwap_relation_reason) == ("at_value", None)
    assert (ctx.value_state, ctx.value_state_reason) == ("shifted_higher", None)   # POC 770.98 vs 767.59


def test_a_missing_input_leaves_the_value_context_absent_with_its_reason():
    """A missing point of control read "unchanged" and a missing VWAP "at value". Schwab's $SPX
    bars carry no volume (real bars 2026-09-25/28): no VWAP, no value area, no point of control."""
    spx = json.loads((_FX / "real_spx_1m_bars_2026_09_25_28.json").read_text(encoding="utf-8"))["bars"]
    s = build_price_level_snapshot("$SPX", date(2026, 9, 28), _bars_to_list(spx), bar_source="price_bars_1m")
    ctx = value_context(s)
    assert (ctx.value_state, ctx.value_state_reason) == (None, "no point of control today")
    assert (ctx.vwap_relation, ctx.vwap_relation_reason) == (None, "no session VWAP")
    assert {"family": "prior_day_value_area",
            "reason": "the prior session's (2026-09-25) bars carry no volume for a volume profile"} in s.families_absent


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def spy_published(monkeypatch, pin_clock):
    """SPY's price levels published from its real bars, the way the bar writer publishes them, at
    Friday 2026-09-25 16:30 ET; no option levels."""
    pin_clock(2026, 9, 25, 16, 30)
    monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda tk: BARS)
    monkeypatch.setattr(srv, "_terrain_cache", {})
    srv._publish_price_levels("SPY")


def test_the_route_places_the_price_among_the_zones_and_names_what_it_lacks(monkeypatch, spy_published):
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (766.5, "streaming_plane", 1.0))   # stand-in, between zones
    body = srv.get_liquidity_snapshot(ticker="SPY")
    zones = body["zones"]
    loc = body["spot_location"]
    assert loc["inside"] is None
    assert zones[loc["below"]]["zone_high"] == 765.59 and zones[loc["above"]]["zone_low"] == 767.59
    assert (zones[loc["below"]]["zone_label"], zones[loc["below"]]["zone_side"]) == ("Support", "support")
    assert (zones[loc["above"]]["zone_label"], zones[loc["above"]]["zone_side"]) == ("Resistance", "resistance")
    assert body["summary"] == {"value_state": "shifted_higher", "value_state_reason": None,
                               "vwap_relation": "at_value", "vwap_relation_reason": None}
    assert {a["input"] for a in body["absent"]} == {"option levels", "PDC"}
    # the zones are as of the end of the newest bar (15:59 ET -> 16:00 ET = 3:00 PM CT)
    assert body["levels_as_of"] == "Fri 09/25 03:00 PM CT"
    # every zone level is the /api/levels value under the same id
    served = {lv["id"]: lv["price"] for lv in json.loads(srv.get_levels(ticker="SPY").body)["levels"]}
    for z in zones:
        for s in z["source_levels"]:
            assert round(served[s["label"]], 4) == s["value"]


def test_the_route_carries_the_option_levels_own_freshness(monkeypatch, spy_published):
    """Measured on the running app 2026-09-30 11:51 ET, 44 tickers: the zones named no time for
    the option levels in them; SNDK's were 84 minutes old, stale on /api/terrain, and the route
    said "live / fused". The zones carry the terrain's own verdict (terrain_staleness) for the
    option levels fused into them, beside the bars' time. Terrain: SPY's real chain
    (tests/fixtures/real_spy_0dte_chain.json); stand-ins: the terrain's age, and the refresh
    window being open or shut."""
    from terrain_engine import compute_terrain
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (766.5, "streaming_plane", 1.0))   # stand-in
    body = srv.get_liquidity_snapshot(ticker="SPY")
    assert body["option_levels"] is None and "option levels" in {a["input"] for a in body["absent"]}

    fx = json.loads((_FX / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))
    terrain = compute_terrain("SPY", fx["chain"], fx["spot"],      # priced at the chain's own time
                              now=datetime.fromtimestamp(fx["ts_utc"], ZoneInfo("America/New_York"))).to_dict()

    def published(age_sec, refreshing):
        monkeypatch.setattr(srv, "_is_loggable_session", lambda now: refreshing)
        monkeypatch.setattr(srv, "_terrain_cache", {"SPY": {**terrain, "computed_ts_utc": time.time() - age_sec,
                                                            "levels_source": "wide_chain_loop"}})
        return srv.get_liquidity_snapshot(ticker="SPY"), srv.terrain_cache_get("SPY", time.time())

    body, served = published(10, True)
    tags = {s["label"] for z in body["zones"] for s in z["source_levels"]}
    assert {"GAMMA_CALL_WALL", "GAMMA_PUT_WALL"} <= tags, "the option levels are in the zones"
    opt = body["option_levels"]
    assert opt["levels_stale"] is False and opt["levels_source"] == "wide_chain_loop"
    assert opt["levels_age_sec"] == pytest.approx(10, abs=5)
    assert body["levels_as_of"] == "Fri 09/25 03:00 PM CT", "the bars keep their own time"

    body, served = published(5045, True)
    opt = body["option_levels"]
    assert opt["levels_stale"] is True and opt["levels_stale_reason"].startswith("levels are 50")
    # the same verdict /api/terrain serves, field for field (the age moves with the clock)
    assert {k: v for k, v in opt.items() if k not in ("levels_age_sec", "levels_stale_reason")} == {
        k: v for k, v in served.items() if k.startswith("levels_") and k not in ("levels_age_sec", "levels_stale_reason")}

    body, _ = published(5045, False)                    # after the refresh window: a past observation
    opt = body["option_levels"]
    assert opt["levels_stale"] is False and opt["levels_market_closed"] is True and opt["levels_as_of"]


def test_the_route_with_no_live_price_gives_no_side_and_no_location(monkeypatch, spy_published):
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (None, "none", None))
    body = srv.get_liquidity_snapshot(ticker="SPY")
    assert body["spot_location"] is None
    assert {z["zone_side"] for z in body["zones"]} <= {None, "value"}
    assert {"input": "live price",
            "reason": "no live price: a zone has no side and the price has no location"} in body["absent"]


def test_the_prior_close_is_schwabs_close_price_on_both_routes(monkeypatch):
    """2026-09-30, all 43 board tickers: the chart's prior close was the close of the last stored
    15:59 bar, which differed from Schwab's CLOSE_PRICE for 39 of them ($SPX 7671.85 against
    7670.84). The prior close is Schwab's field, from the daemon's price row, on /api/levels and
    in the zones; absent with its reason when the quote is not live. Real TSLA quote."""
    fx = json.loads((_FX / "real_equity_book.json").read_text(encoding="utf-8"))
    tk, native = fx["ticker"], fx["quote"]["native"]
    monkeypatch.setattr(lmp, "_by_ticker", {})
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda t: [])
    feed_live_during(monkeypatch, tk)                   # at SESSION_NOW, the market in session
    lmp.record_from_level_one_equity(tk, native, received_ts=SESSION_NOW)
    publish_daemon_rows(tk)
    srv._publish_price_levels(tk)

    levels = json.loads(srv.get_levels(ticker=tk).body)
    pdc = next(lv for lv in levels["levels"] if lv["id"] == "PDC")
    assert pdc["price"] == native["CLOSE_PRICE"] == 377.94
    assert pdc["provenance"]["producer"] == srv.PRIOR_CLOSE_SOURCE and pdc["family"] == "prior_day"
    zones = srv.get_liquidity_snapshot(ticker=tk)["zones"]
    assert [s for z in zones for s in z["source_levels"]] == [{"label": "PDC", "value": 377.94}]

    # the daemon no longer holds the symbol: its quote is not live
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": []}}, SESSION_NOW)
    publish_daemon_rows(tk)
    levels = json.loads(srv.get_levels(ticker=tk).body)
    assert not [lv for lv in levels["levels"] if lv["id"] == "PDC"]
    assert {"family": "PDC", "reason": srv.PRIOR_CLOSE_ABSENT_REASON} in levels["families_absent"]
