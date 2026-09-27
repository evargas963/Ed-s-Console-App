"""Page-side one faucet (2026-09-27): every value on the console page has one server producer.

One spot on every screen: each route that serves `spot` serves the live price at response time
(resolve_spot, the rule the header's price row uses); a value computed at another price names that
price `priced_at_spot`. Strike Detail's Net GEX is the heatmap's own cell, and OI/volume cell
totals are served, not summed in the browser."""
import json
import time

import pytest

import server

TK = "CRWD"
PUBLISHED, LIVE = 400.0, 412.5


@pytest.fixture
def held(monkeypatch):
    surface = {"strikes": [400.0], "expiries": ["2030-01-18"], "cells": [], "spot": PUBLISHED,
               "spot_source": "chain", "spot_as_of_ts_utc": 1.0, "gamma_available": True}
    snap = {"ticker": TK, "spot": PUBLISHED, "computed_ts_utc": time.time(),
            "expiries": ["2030-01-18"], "_chain_fetched_ts": time.time(),
            "_chain": [{"expirationDate": "2030-01-18", "strikePrice": 400.0, "putCall": "CALL"}],
            "_gamma_surface": surface, "_vanna_rows": [[400.0, 1.0]], "_charm_rows": [[400.0, 1.0]],
            "_per_strike": {"all": [[390.0, 5.0, 10], [420.0, 7.0, 20]], "near": [], "far": []}}
    monkeypatch.setattr(server, "terrain_cache_get", lambda tk: snap)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (LIVE, "live_quote", time.time()))
    monkeypatch.setattr(server, "_price_stored_chain_when_closed", lambda tk: None)
    monkeypatch.setattr(server, "last_capture_per_day", lambda *a, **k: [])
    monkeypatch.setattr(server, "_gamma_surface_contracts_with_stream_overlay",
                        lambda t, cts, newer_than_ts=None: (cts, 0, None))
    return snap


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker=TK, expiry=None),
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
    sums = json.loads(server.get_terrain_strikes(ticker=TK).body)["today_side_sums"]
    # 390 is below and 420 above the live 412.5 (both sit on one side of neither 400 nor 412.5
    # differently -- so check the basis itself)
    assert sums["spot_basis"] == LIVE and sums["gex_below"] == 5.0 and sums["gex_above"] == 7.0


def test_chain_serves_this_expirys_net_gex_from_the_heatmaps_own_column(held):
    """Strike Detail's Net row: this expiry's column of the published surface -- one producer."""
    held["_gamma_surface"].update(
        expirations=[{"expiry": "2030-01-11"}, {"expiry": "2030-01-18"}],
        cells=[{"strike": 400.0, "gex": [111.0, 222.0]}, {"strike": 405.0, "gex": [333.0, None]}])
    body = json.loads(server.get_chain(ticker=TK, expiry="2030-01-18").body)
    assert body["net_gex_by_strike"] == [[400.0, 222.0]]


def test_oi_and_volume_cells_carry_the_served_total():
    """The OI/Volume heatmap colours by the cell's total, served -- the browser adds nothing. One
    unknown side leaves the total unknown (a missing side is not a zero)."""
    bucket = {"has_oi": True, "has_valid_gamma": True, "net_gex_1pct": 1.0, "net_dex_dollars": 1.0,
              "call_vanna": 0.0, "put_vanna": 0.0,
              "call_oi": 300.0, "put_oi": 200.0, "call_volume": 40.0, "put_volume": None}
    _g, _d, _v, oi, volume, _c, _hg, _ho = server._gamma_surface_cell_fields(bucket, None)
    assert oi == {"call": 300, "put": 200, "total": 500}
    assert volume == {"call": 40, "put": None, "total": None}


def test_every_alert_carries_the_time_it_was_observed(held, monkeypatch):
    """The Trade Desk stamped alerts with the browser's clock; each now carries its own time."""
    held.update(call_wall=413.0, put_wall=None)
    cross_ts = time.time() - 5
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda tk, n=10: [
        {"ts_utc": cross_ts, "direction": "up", "level_name": "gamma_flip"}])
    alerts = json.loads(server.get_alerts(ticker=TK).body)["alerts"]
    assert [a["ts_utc"] for a in alerts][1] == cross_ts
    assert alerts[0]["text"].startswith("Within 0.5pts of 413.00 ceiling") and alerts[0]["ts_utc"] is not None


def test_a_book_with_no_age_is_not_reported_fresh():
    """LIVE badges read book_stale: an unknown book age is unknown (None), never False (fresh)."""
    from app.options.order_flow.engine import compute_book_microstructure
    out = compute_book_microstructure({"content": {}}, now_ts=1_800_000_000.0)
    assert out["ages"]["book_age_sec"] is None and out["ages"]["book_stale"] is None
