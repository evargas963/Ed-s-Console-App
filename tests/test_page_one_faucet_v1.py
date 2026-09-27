"""Page-side one faucet (2026-09-27): every value on the console page has one server producer.

One spot on every screen: each route that serves `spot` serves the live price at response time
(resolve_spot, the rule the header's price row uses); a value computed at another price names that
price `priced_at_spot`. Strike Detail's Net GEX is the heatmap's own cell, and OI/volume cell
totals are served, not summed in the browser.

Real data only: Schwab's CRWD chain as captured 2026-09-02 (tests/fixtures), run through the real
producer (compute_terrain -> project_gamma_surface), assembled the way _terrain_refresh_one does.
The one stand-in is the live price: no stream runs in a test, so resolve_spot returns a second
price, LIVE, to tell the live price apart from the capture's own."""
import json
import time
from pathlib import Path

import pytest

import server
from terrain_engine import compute_terrain

_REAL = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                   .read_text(encoding="utf-8"))
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
TK = "CRWD"
EXPIRY = _REAL["expiry"]                   # 2026-09-18
PUBLISHED = float(_REAL["spot"])           # Schwab's price at the capture
LIVE = PUBLISHED + 1.0                     # stand-in for the stream's price


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    return pin_clock(2026, 9, 2, 10, 5)    # the chain's own capture time


@pytest.fixture
def held(monkeypatch):
    snap = compute_terrain(TK, _CONTRACTS, PUBLISHED)
    surface = server.project_gamma_surface(_CONTRACTS, snap.books)
    surface.update(spot=PUBLISHED, spot_source="chain", spot_as_of_ts_utc=time.time())
    payload = snap.to_dict()
    payload.update({"computed_ts_utc": time.time(), "_per_strike": snap.per_strike,
                    "_vanna_rows": server._vanna_rows(snap), "_charm_rows": server._charm_rows(snap),
                    "_chain": _CONTRACTS, "_chain_fetched_ts": time.time(), "_gamma_surface": surface})
    monkeypatch.setattr(server, "terrain_cache_get", lambda tk: payload)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (LIVE, "live_quote", time.time()))
    monkeypatch.setattr(server, "_price_stored_chain_when_closed", lambda tk: None)
    monkeypatch.setattr(server, "last_capture_per_day", lambda *a, **k: [])
    monkeypatch.setattr(server, "_gamma_surface_contracts_with_stream_overlay",
                        lambda t, cts, newer_than_ts=None: (cts, 0, None))
    return payload


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker=TK, expiry=EXPIRY),
    lambda: server.get_options_gamma_surface(ticker=TK),
    lambda: server.get_terrain_strikes(ticker=TK),
    lambda: server.get_vanna_by_strike(ticker=TK),
    lambda: server.get_charm_by_strike(ticker=TK),
], ids=["chain", "gamma-surface", "terrain-strikes", "vanna", "charm"])
def test_every_route_serves_the_live_spot_and_names_the_computed_one(held, route):
    body = json.loads(route().body)
    assert body["spot"] == LIVE, "served the price the payload was computed at, not the live one"
    assert body["priced_at_spot"] == PUBLISHED


def test_strike_side_sums_split_at_the_live_spot(held):
    rows = held["_per_strike"]["all"]
    below = [r for r in rows if r[0] < LIVE]
    above = [r for r in rows if r[0] > LIVE]
    assert below and above, "the real chain has strikes on both sides of the live price"
    sums = json.loads(server.get_terrain_strikes(ticker=TK).body)["today_side_sums"]
    assert sums["spot_basis"] == LIVE
    assert sums["gex_below"] == pytest.approx(sum(r[1] for r in below), abs=0.1)
    assert sums["gex_above"] == pytest.approx(sum(r[1] for r in above), abs=0.1)


def test_chain_serves_this_expirys_net_gex_from_the_heatmaps_own_column(held):
    """Strike Detail's Net row: this expiry's column of the published surface, verbatim."""
    surf = held["_gamma_surface"]
    col = [e["expiry"] for e in surf["expirations"]].index(EXPIRY)
    expected = [[c["strike"], c["gex"][col]] for c in surf["cells"] if c["gex"][col] is not None]
    assert expected, "the real chain yields net GEX cells for its expiry"
    body = json.loads(server.get_chain(ticker=TK, expiry=EXPIRY).body)
    assert body["net_gex_by_strike"] == expected


def test_oi_and_volume_cells_carry_the_served_total(held):
    """The OI/Volume heatmap colours by the cell's served total: Schwab's call OI + put OI at the
    strike, read straight from the chain; the browser adds nothing."""
    surf = held["_gamma_surface"]
    col = [e["expiry"] for e in surf["expirations"]].index(EXPIRY)
    checked = 0
    for c in surf["cells"]:
        legs = {ct["putCall"]: ct for ct in _CONTRACTS if ct["strikePrice"] == c["strike"]}
        if set(legs) != {"CALL", "PUT"}:
            continue
        # Schwab's values as sent: a reported 0 (strike 38.75's put OI) is a real zero
        assert c["oi"][col]["total"] == legs["CALL"]["openInterest"] + legs["PUT"]["openInterest"]
        assert c["volume"][col]["total"] == legs["CALL"]["totalVolume"] + legs["PUT"]["totalVolume"]
        checked += 1
    assert checked > 50


def test_every_alert_carries_the_time_it_was_observed(held, monkeypatch):
    """The Trade Desk stamped alerts with the browser's clock; each now carries its own time."""
    wall = held["call_wall"]
    near = wall * (1 - server.LEVEL_NEAR_SPOT_FRACTION / 2)   # inside the one near-spot rule
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (near, server.SPOT_SOURCE_PLANE, 1_788_000_000.0))
    monkeypatch.setattr(server._lpr, "live_spot", lambda tk: near)   # stand-in: the live price
    cross_ts = time.time() - 5
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda ticker, n=10: [
        {"ts_utc": cross_ts, "direction": "up", "level_name": "gamma_flip"}])
    alerts = json.loads(server.get_alerts(ticker=TK).body)["alerts"]
    (at_wall,) = [a for a in alerts if a["text"].startswith(f"At Call wall {wall:.2f}")]
    assert at_wall["text"].endswith("above spot)") and at_wall["ts_utc"] == 1_788_000_000.0
    assert alerts[-1]["ts_utc"] == cross_ts


def test_no_near_level_alert_without_a_live_price(held, monkeypatch):
    """Rule 5: on a closed market the price is a stored capture's -- a past observation -- and
    raises no near-level alert, with the reason served (2026-09-27: Friday's levels against
    Friday's last price fired as current alerts on Sunday)."""
    wall = held["call_wall"]
    near = wall * (1 - server.LEVEL_NEAR_SPOT_FRACTION / 2)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (near, server.SPOT_SOURCE_CAPTURE, 1_788_000_000.0))
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda ticker, n=10: [])
    body = json.loads(server.get_alerts(ticker=TK).body)
    assert body["alerts"] == [] and body["withheld"].startswith("no live price")


def test_a_book_with_no_age_is_not_reported_fresh():
    """LIVE badges read book_stale: an unknown book age is unknown (None), never False (fresh)."""
    from app.options.order_flow.engine import compute_book_microstructure
    out = compute_book_microstructure({"content": {}}, now_ts=1_800_000_000.0)
    assert out["ages"]["book_age_sec"] is None and out["ages"]["book_stale"] is None


def test_days_to_expiry_are_schwabs_as_sent(held):
    """The expiry dropdown's DTE: Schwab's daysToExpiration from the chain, not the browser's
    clock (it counted days in UTC, a day off after 7 PM Central)."""
    body = json.loads(server.get_expiries(ticker=TK).body)
    assert body["expiries"] == [EXPIRY]
    assert body["dte"] == {EXPIRY: _CONTRACTS[0]["daysToExpiration"]}


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker=TK, expiry=EXPIRY),
    lambda: server.get_options_gamma_surface(ticker=TK),
    lambda: server.get_terrain_strikes(ticker=TK),
], ids=["chain", "gamma-surface", "terrain-strikes"])
def test_the_spot_row_is_served(held, route):
    """The row every panel marks as spot: the listed strike nearest the live price, served (it
    was worked out in six places in the page)."""
    body = json.loads(route().body)
    strikes = sorted({float(c["strikePrice"]) for c in _CONTRACTS})
    assert body["spot_strike"] == min(strikes, key=lambda k: abs(k - LIVE))


def test_put_call_ratios_over_every_expiry_are_served(held):
    """With no expiry selected the Put/Call rows show the whole book, served (the page used to
    pick the first expiry in its list, an expired one on 2026-09-27)."""
    assert held["pcr_all"] is not None
    assert held["pcr_all"] == held["pcr_by_expiry"][EXPIRY]      # one expiry: the same book


def test_levels_are_served_in_ladder_order_with_distance_and_near_spot(monkeypatch):
    """The levels panel and the Trade Desk used to sort levels, measure distance to spot and apply
    the 0.15% near-spot rule in the page. Real SPY 1-minute bars (2026-09-24 and 25)."""
    from datetime import datetime as _dt
    import time_et as te
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))
    spot = fx["bars"][-1]["close"]                               # the session's last real close
    monkeypatch.setattr(server, "_liquidity_live_1m_overlay_bars", lambda t: fx["bars"])
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (spot, "live_quote", time.time()))
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 25, 16, 5, tzinfo=te.ET))
    body = json.loads(server.get_levels(ticker="SPY").body)
    lv = body["levels"]
    priced = [r for r in lv if r["price"] is not None]
    assert len(priced) > 5
    assert [r["price"] for r in priced] == sorted((r["price"] for r in priced), reverse=True)
    for r in priced:
        assert r["distance"] == pytest.approx(r["price"] - spot)
        assert r["near_spot"] == (abs(r["price"] - spot) / spot < server.LEVEL_NEAR_SPOT_FRACTION)
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))]


def test_heatmap_column_state_cell_age_and_front_expiry_are_served(held, monkeypatch):
    """Column streaming status and a cell's age come from the server's own stream states; the
    front column is the nearest unexpired expiry."""
    surf = held["_gamma_surface"]
    calls = [c for c in _CONTRACTS if c["putCall"] == "CALL"]
    live_sym, stale_sym = calls[0]["symbol"], calls[1]["symbol"]
    now = time.time()
    streamed = {live_sym: {"quote_ts": now - 2}, stale_sym: {"quote_ts": now - 90}}
    monkeypatch.setattr(server, "_leg_stream_ts_recv", lambda g: g.get("quote_ts") if g else None)
    server._stamp_gamma_surface_cell_stream_state(surf, streamed, {live_sym}, {}, {live_sym, stale_sym})
    assert surf["stream_by_expiry"][EXPIRY] == "partial"          # one live leg in the column
    ages = [c["stream"][0]["age_sec"] for c in surf["cells"] if c["stream"][0] and c["stream"][0]["age_sec"] is not None]
    assert ages and max(ages) == pytest.approx(90, abs=1)
    body = json.loads(server.get_options_gamma_surface(ticker=TK).body)
    assert body["front_expiry"] == EXPIRY


def test_chain_flags_are_served(held):
    """ADJUSTED DELIVERABLE and duplicate contracts: served flags, not page rules."""
    body = json.loads(server.get_chain(ticker=TK, expiry=EXPIRY).body)
    plain = [c["symbol"] for c in _CONTRACTS if len(c.get("optionDeliverablesList") or []) == 1]
    assert plain and not set(plain) & set(body["adjusted_deliverable_symbols"])
    assert body["has_duplicate_contracts"] is False


def test_the_largest_gex_strike_is_served(held):
    rows = held["_per_strike"]["all"]
    body = json.loads(server.get_terrain_strikes(ticker=TK).body)
    assert body["max_abs_strike"] == max(rows, key=lambda r: abs(r[1]))[0]


def test_on_a_closed_market_the_last_trade_is_a_labelled_past_observation(monkeypatch):
    """Sunday 2026-09-27: the daemon streamed SPY's last trade (Friday 18:59:59 CT) on a live
    feed, and the page called it LIVE and raised near-level alerts from it. Replayed here as the
    daemon captured it (stream_quotes_raw): outside the session it is not live; the row serves
    it as the closed market's last trade with its time, and alerts are withheld."""
    import live_market_plane as lmp
    import live_price_rows
    from tests.feed_live_helper import mark_feed_live
    monkeypatch.setattr(lmp, "is_capturable_session", lambda: False)
    monkeypatch.setattr(live_price_rows, "is_capturable_session", lambda: False)
    mark_feed_live("SPY")
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=time.time())
    row = live_price_rows.price_row("SPY")
    assert (row["spot"], row["spot_state"]) == (None, "closed")
    assert row["closed_last"] == {"spot_disp": "772.04", "as_of": "Fri 09/25 06:59 PM CT"}
    assert server.resolve_spot("SPY")[0] is None
    assert server.current_spot_state(server.SPOT_SOURCE_PLANE, "SPY") == "stale"
