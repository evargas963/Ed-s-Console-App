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
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (wall - 0.5, "live_quote", 1_788_000_000.0))
    cross_ts = time.time() - 5
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda tk, n=10: [
        {"ts_utc": cross_ts, "direction": "up", "level_name": "gamma_flip"}])
    alerts = json.loads(server.get_alerts(ticker=TK).body)["alerts"]
    assert alerts[0]["text"].startswith(f"Within 0.5pts of {wall:.2f} ceiling")
    assert alerts[0]["ts_utc"] == 1_788_000_000.0
    assert alerts[1]["ts_utc"] == cross_ts


def test_a_book_with_no_age_is_not_reported_fresh():
    """LIVE badges read book_stale: an unknown book age is unknown (None), never False (fresh)."""
    from app.options.order_flow.engine import compute_book_microstructure
    out = compute_book_microstructure({"content": {}}, now_ts=1_800_000_000.0)
    assert out["ages"]["book_age_sec"] is None and out["ages"]["book_stale"] is None
