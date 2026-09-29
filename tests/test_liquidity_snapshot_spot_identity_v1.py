"""spot_used_for_scoring must never silently carry a VWAP value (RC-close-2026-09-11), and a
HTTPException raised on the route's path must propagate as its own status code (e.g. 503), not
a blanket 500 -- both found by independent review of /api/liquidity-snapshot,
verified against the real server route function (not a route-shape simulation)."""
from __future__ import annotations

import json

import server as srv
import liquidity_value_engine as lve
from liquidity_models import SnapshotType, Zone, ZoneType


class _FakeSnapshotOutput:
    def __init__(self, ticker, session_date, raw_levels, zones=None):
        self.ticker = ticker
        self.session_date = session_date
        self.snapshot_type = SnapshotType.LIVE
        self.zones = zones or []
        self.summary = None
        self.raw_levels = raw_levels


class _FakeCanon:
    generation, as_of_ts_utc, bar_source = 1, 0.0, "test"


def _wire_common(monkeypatch, *, raw_levels, zones=None, resolved_spot=None):
    monkeypatch.setattr(srv, "_liquidity_option_levels", lambda *a, **k: ([], "n/a"))
    monkeypatch.setattr(srv, "resolve_spot", lambda *a, **k: (resolved_spot, None, None))
    # the route's one level input: the materialized price-level snapshot
    monkeypatch.setattr(srv, "canonical_price_level_snapshot", lambda t: _FakeCanon())
    monkeypatch.setattr(lve, "carry_snapshot_levels", lambda *a, **k: None)
    fake_out = _FakeSnapshotOutput("SPY", "2020-01-02", raw_levels, zones=zones)
    monkeypatch.setattr(lve, "build_live_snapshot", lambda *a, **k: fake_out)
    return fake_out


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


def test_spot_used_for_scoring_is_null_not_vwap_when_no_live_spot_is_cached(monkeypatch):
    """MEASURED 2026-09-11: with no live spot, spot_used_for_scoring used to be silently
    backfilled with the VWAP number and reported under the "spot" name. It must report null --
    absence stays absence."""
    _wire_common(monkeypatch, raw_levels={"vwap": 123.45, "cutoff_et": "2020-01-02T10:00:00"})
    body = _body(srv.get_liquidity_snapshot(ticker="SPY"))
    assert body["spot_used_for_scoring"] is None
    assert "spot_estimate_vwap_fallback" not in body, "VWAP is never a stand-in for spot"


def test_missing_spot_produces_honest_null_distance_and_neutral_score_through_the_real_zone_path(monkeypatch):
    """MEASURED 2026-09-11: the VWAP-as-spot value was also fed into the zone distance and sort.
    A REAL Zone through the actual route: with no spot, distance and inside-zone are absent and
    the score is neutral -- not a crash, not a fabricated distance."""
    zone = Zone(
        zone_type=ZoneType.PIVOT_VALUE, zone_low=100.0, zone_high=102.0, zone_mid=101.0,
        source_tags=["GAMMA_WALL"],
    )
    _wire_common(monkeypatch, raw_levels={"vwap": 123.45}, zones=[zone])
    body = _body(srv.get_liquidity_snapshot(ticker="SPY"))
    assert len(body["zones"]) == 1
    z = body["zones"][0]
    assert z["distance_to_spot"] is None
    assert z["spot_inside_zone"] is None
    assert isinstance(z["tradeable_score"], (int, float))
    # the pages named every zone that was not support_liquidity "Resistance" (a pivot zone here):
    # each zone's name and side are served from its type
    assert (z["zone_label"], z["zone_side"]) == ("Pivot / value", "value")


def test_spot_used_for_scoring_reports_the_real_live_spot_when_available(monkeypatch):
    """The positive control: a real live spot (resolve_spot, the one spot authority) is reported
    as spot_used_for_scoring."""
    _wire_common(monkeypatch, raw_levels={"vwap": 123.45}, resolved_spot=456.78)
    body = _body(srv.get_liquidity_snapshot(ticker="SPY"))
    assert body["spot_used_for_scoring"] == 456.78
    assert "spot_estimate_vwap_fallback" not in body


def test_an_http_exception_on_the_route_path_keeps_its_status_not_a_generic_500(monkeypatch):
    """MEASURED 2026-09-11: an HTTPException(503, ...) on this route's path was re-issued as a
    bare 500. It must propagate as its own status (raised here from the snapshot read)."""
    from fastapi import HTTPException

    _wire_common(monkeypatch, raw_levels={})

    def _raise_auth_unavailable(*a, **k):
        raise HTTPException(status_code=503, detail="Schwab auth failed: token_invalid")
    monkeypatch.setattr(srv, "canonical_price_level_snapshot", _raise_auth_unavailable)
    resp = srv.get_liquidity_snapshot(ticker="SPY")
    assert resp.status_code == 503
    assert "token_invalid" in json.loads(resp.body)["error"]


def test_an_unrelated_crash_still_reports_500(monkeypatch):
    """Negative control: a genuine unexpected error still reports 500."""
    _wire_common(monkeypatch, raw_levels={})

    def _boom(*a, **k):
        raise RuntimeError("something actually broke")
    monkeypatch.setattr(srv, "canonical_price_level_snapshot", _boom)
    resp = srv.get_liquidity_snapshot(ticker="SPY")
    assert resp.status_code == 500
    assert "something actually broke" in json.loads(resp.body)["error"]
