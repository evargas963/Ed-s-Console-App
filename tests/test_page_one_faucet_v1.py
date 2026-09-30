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
    surface.update(spot=PUBLISHED, spot_source=server.SPOT_SOURCE_PLANE, spot_as_of_ts_utc=time.time())
    payload = snap.to_dict()
    payload.update({"computed_ts_utc": time.time(), "_per_strike": snap.per_strike,
                    "_vanna_rows": server._vanna_rows(snap), "_charm_rows": server._charm_rows(snap),
                    "_chain": _CONTRACTS, "_chain_fetched_ts": time.time(), "_gamma_surface": surface})
    monkeypatch.setattr(server, "terrain_cache_get", lambda tk, now: payload)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (LIVE, server.SPOT_SOURCE_PLANE, time.time()))
    monkeypatch.setattr(server, "_price_stored_chain_when_closed", lambda tk, now: None)
    monkeypatch.setattr(server, "last_capture_per_day", lambda *a, **k: [])
    monkeypatch.setattr(server, "_gamma_surface_contracts_with_stream_overlay",
                        lambda t, cts, now: (cts, 0, None))
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


def test_strike_side_sums_are_the_publications_split_at_its_own_price(held):
    """S-23: the route summed the rows again, at the live price, and left out every strike whose
    volume Schwab had not reported. The sums are the levels producer's, over every row, split at
    the price the rows were computed at (DATA_FLOW: everything computed from spot is computed in
    the one publication at that publication's price); the route carries them."""
    rows = held["_per_strike"]["all"]
    below = [r for r in rows if r[0] < PUBLISHED]
    above = [r for r in rows if r[0] > PUBLISHED]
    assert below and above, "the real chain has strikes on both sides of its price"
    sums = json.loads(server.get_terrain_strikes(ticker=TK).body)["today_side_sums"]
    assert sums == held["_per_strike"]["side_sums"]
    assert sums["spot_basis"] == PUBLISHED != LIVE
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


def test_no_proximity_alerts_are_served():
    """Operator 2026-09-29: proximity alerts are removed everywhere -- no alert route, no
    near-spot flag on the levels, no alert items in the Trade Desk queue."""
    from fastapi.testclient import TestClient
    assert TestClient(server.app).get("/api/alerts?ticker=SPY").status_code == 404
    assert not hasattr(server, "get_alerts") and not hasattr(server, "LEVEL_NEAR_SPOT_FRACTION")


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
    # the dropdown's label is served (the page reformatted the date itself)
    y, m, d = EXPIRY.split("-")
    assert body["labels"] == {EXPIRY: f"{m}/{d}/{y} · {_CONTRACTS[0]['daysToExpiration']:g}DTE"}


def test_with_no_published_levels_the_expiries_carry_the_levels_reason():
    body = json.loads(server.get_expiries(ticker="ZZNOLEVELS").body)
    assert body["expiries"] == [] and body["reason"] == server.terrain_staleness(None, "ZZNOLEVELS", time.time())["levels_stale_reason"]


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


def test_levels_are_served_in_ladder_order_with_distance(monkeypatch):
    """The levels panel and the Trade Desk used to sort levels, measure distance to spot and apply
    the 0.15% near-spot rule in the page. Real SPY 1-minute bars (2026-09-24 and 25)."""
    from datetime import datetime as _dt
    import time_et as te
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))
    spot = fx["bars"][-1]["close"]                               # the session's last real close
    monkeypatch.setattr(server, "_liquidity_1m_bars", lambda t: fx["bars"])
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (spot, server.SPOT_SOURCE_PLANE, time.time()))
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 25, 16, 5, tzinfo=te.ET))
    server._publish_price_levels("SPY")                          # as the bar writer does
    body = json.loads(server.get_levels(ticker="SPY").body)
    lv = body["levels"]
    priced = [r for r in lv if r["price"] is not None]
    assert len(priced) > 5
    assert [r["price"] for r in priced] == sorted((r["price"] for r in priced), reverse=True)
    for r in priced:
        assert r["distance"] == pytest.approx(r["price"] - spot)
        assert "near_spot" not in r          # no proximity flag (operator 2026-09-29)
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))]


def test_the_volume_profile_the_value_area_is_read_from_is_served(monkeypatch):
    """The Trade Desk reference draws the session's volume profile at the chart's left edge
    (2026-09-28). The profile was built for the value area and dropped; /api/levels serves that
    same profile: its POC/VAH/VAL are the served TODAY_ levels, its bins hold every RTH bar's
    volume, and each bin says whether it is inside the value area. Real SPY 1-minute bars."""
    from datetime import datetime as _dt
    import time_et as te
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))
    monkeypatch.setattr(server, "_liquidity_1m_bars", lambda t: fx["bars"])
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (fx["bars"][-1]["close"], server.SPOT_SOURCE_PLANE, time.time()))
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 25, 16, 5, tzinfo=te.ET))
    server._publish_price_levels("SPY")                          # as the bar writer does
    body = json.loads(server.get_levels(ticker="SPY").body)
    vp = body["volume_profile"]
    by_id = {r["id"]: r["price"] for r in body["levels"]}
    assert (vp["poc"], vp["vah"], vp["val"]) == (by_id["TODAY_POC"], by_id["TODAY_VAH"], by_id["TODAY_VAL"])
    prices = [b[0] for b in vp["bins"]]
    assert prices == sorted(prices) and len(prices) > 100
    assert all(b[2] == (vp["val"] <= b[0] <= vp["vah"]) for b in vp["bins"])
    at = [(_dt.fromtimestamp(b["timestamp"] / 1000, te.ET), b) for b in fx["bars"]]
    rth = [b for d, b in at if d.date().isoformat() == "2026-09-25" and te.session_label(d) == "RTH"]
    # every RTH bar's volume is in the profile; the 15:59 bar sent no volume, cannot be placed, and
    # is counted and served (operator 2026-09-29: accounted for, not silently dropped)
    assert sum(b[1] for b in vp["bins"]) == pytest.approx(sum(b["volume"] for b in rth if b["volume"] is not None), rel=1e-9)
    assert (vp["bars"], vp["bars_without_volume"]) == (len(rth), sum(1 for b in rth if b["volume"] is None)) == (390, 1)
    assert vp["basis"].startswith("Estimated volume by price")


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


def test_an_index_option_is_not_flagged_adjusted_only_schwabs_nonstandard_is(monkeypatch):
    """TICK-03 (2026-09-28 audit): the page's ADJUSTED DELIVERABLE flag was our own rule ("100
    shares of the underlying"), which compared Schwab's deliverable symbol "$SPX" with the ticker
    stripped of its "$" -- so every $SPX (29,436) and $VIX (1,520) contract read adjusted, while
    Schwab's own nonStandard flag was false on all 43 board tickers. The flag is Schwab's, as
    sent. Real $SPX contracts (tests/fixtures/real_spx_chain_contracts_2026_09_28.json): none
    flagged; the same contract with nonStandard true: flagged."""
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_spx_chain_contracts_2026_09_28.json")
                    .read_text(encoding="utf-8"))
    cts = [dict(c) for c in fx["contracts"]]
    cts[0]["nonStandard"] = True                      # stand-in: Schwab marking one contract
    payload = {"_chain": cts, "_chain_fetched_ts": time.time(), "computed_ts_utc": time.time()}
    monkeypatch.setattr(server, "terrain_cache_get", lambda tk, now: payload)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (fx["spot"], server.SPOT_SOURCE_PLANE, time.time()))
    monkeypatch.setattr(server, "_price_stored_chain_when_closed", lambda tk, now: None)
    monkeypatch.setattr(server, "_gamma_surface_contracts_with_stream_overlay",
                        lambda t, c, now: (c, 0, None))
    body = json.loads(server.get_chain(ticker="$SPX", expiry="2026-10-16").body)
    assert body["adjusted_deliverable_symbols"] == [cts[0]["symbol"]]


def test_the_largest_strike_of_each_profile_is_the_producers(held):
    """The route picked each profile's largest strike itself. The GEX profile's is the published
    net_gex_peak level; the DEX and OI profiles' are published with their rows."""
    rows = held["_per_strike"]["all"]
    body = json.loads(server.get_terrain_strikes(ticker=TK).body)
    assert body["max_abs_strike"] == held["net_gex_peak"] == max(rows, key=lambda r: abs(r[1]))[0]
    for m in ("dex", "oi"):
        served = body["measures"][m]
        assert served["rows"] == held["_per_strike"][m]
        assert served["max_abs_strike"] == held["_per_strike"]["peak"][m]
        assert served["max_abs_strike"] == max(served["rows"], key=lambda r: abs(r[1]))[0]


def test_on_a_closed_market_the_last_trade_is_a_labelled_past_observation(monkeypatch):
    """Sunday 2026-09-27: the daemon streamed SPY's last trade (Friday 18:59:59 CT) on a live
    feed, and the page called it LIVE. Replayed here as the daemon captured it
    (stream_quotes_raw): outside the session it is not live; the row serves it as the closed
    market's last trade with its time, and it is no spot."""
    import live_market_plane as lmp
    import live_price_rows
    from tests.feed_live_helper import CLOSED_NOW, mark_feed_live
    mark_feed_live("SPY", now=CLOSED_NOW)
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=CLOSED_NOW)
    row = live_price_rows.price_row("SPY", CLOSED_NOW)
    assert (row["spot"], row["spot_state"]) == (None, "closed")
    assert row["closed_last"] == {"price": 772.04, "spot_disp": "772.04", "as_of": "Fri 09/25 06:59 PM CT"}
    assert server.resolve_spot("SPY")[0] is None


def test_on_a_closed_market_the_levels_are_ordered_from_the_last_trade(monkeypatch):
    """Monday 2026-09-28 21:40 ET: the Trade Desk chart drew no key level at all after the close --
    /api/levels served 30 SPY levels and an empty by_distance, the order the chart draws them in,
    because it was measured only from a live price. Closed, it is measured from the last streamed
    trade and names it; distance and near-spot stay live-only. Real SPY 1-minute bars
    (2026-09-24 and 25); the last trade is the one the daemon captured."""
    from datetime import datetime as _dt
    import live_market_plane as lmp
    import live_price_rows
    import time_et as te
    from app.options.order_flow import streaming
    from tests.feed_live_helper import CLOSED_NOW, mark_feed_live
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))
    monkeypatch.setattr(server, "_liquidity_1m_bars", lambda t: fx["bars"])
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 25, 16, 5, tzinfo=te.ET))
    mark_feed_live("SPY", now=CLOSED_NOW)
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=CLOSED_NOW)
    monkeypatch.setitem(streaming._price_rows, "SPY", live_price_rows.price_row("SPY", CLOSED_NOW))
    server._publish_price_levels("SPY")                          # as the bar writer does
    body = json.loads(server.get_levels(ticker="SPY").body)
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert len(priced) > 5 and body["spot"] is None
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - 772.04))]
    assert body["by_distance_ref"] == {"price": 772.04, "source": "last trade", "as_of": "Fri 09/25 06:59 PM CT"}
    assert all(r["distance"] is None for r in priced)
