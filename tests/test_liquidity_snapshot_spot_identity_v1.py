"""spot_used_for_scoring must never silently carry a VWAP value (RC-close-2026-09-11), and a
genuine Schwab-auth-unavailable failure must propagate as its own HTTPException status code
(503), not a blanket 500 -- both found by independent review of /api/liquidity-snapshot,
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


def _wire_common(monkeypatch, *, raw_levels, zones=None):
    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_liquidity_fusion_from_cache", lambda *a, **k: ([], None, "disabled"))
    monkeypatch.setattr(srv, "_liquidity_spot_from_cache_any_expiry", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda *a, **k: None)

    import polling_adapter
    monkeypatch.setattr(
        polling_adapter, "fetch_bars_via_schwab_for_session",
        lambda *a, **k: [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    fake_out = _FakeSnapshotOutput("SPY", "2020-01-02", raw_levels, zones=zones)
    monkeypatch.setattr(lve, "build_live_snapshot", lambda *a, **k: fake_out)
    return fake_out


def test_spot_used_for_scoring_is_null_not_vwap_when_no_live_spot_is_cached(monkeypatch):
    """MEASURED 2026-09-11: with no live spot in cache, build_live_snapshot is called with
    spot=None (proven -- no real spot ever reached it), yet spot_used_for_scoring used to be
    silently backfilled with the VWAP number afterward and reported under the "spot" name. It
    must now report null -- absence stays absence -- with the VWAP estimate, if any, reported
    under its own honestly-named field instead."""
    _wire_common(monkeypatch, raw_levels={"vwap": 123.45, "cutoff_et": "2020-01-02T10:00:00"})
    # a date far from "today" so the canonical-carry branch (which needs a live DB row) is skipped
    resp = srv.get_liquidity_snapshot(ticker="SPY", date="2020-01-02", snapshot="live", expiry=None, fusion=False)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert body["spot_used_for_scoring"] is None
    assert body["spot_estimate_vwap_fallback"] == 123.45


def test_missing_spot_produces_honest_null_distance_and_neutral_score_through_the_real_zone_path(monkeypatch):
    """MEASURED 2026-09-11 (independent review, correcting this fix's own prior explanation):
    the VWAP-as-spot value did not only mislabel a reported field -- under the pre-fix code it
    was ALSO fed into _liquidity_zone_tradeable_fields() and the zone sort, which compute
    distance_to_spot/spot_inside_zone/tradeable_score and order zones by them. This drives a
    REAL Zone object through the actual route code (not a zones=[] stub that skips that path
    entirely) and proves the None now reaching it produces the honest absence values
    _liquidity_zone_tradeable_fields already defines for spot=None -- not a crash, not a
    fabricated distance, and not the old VWAP-influenced number."""
    zone = Zone(
        zone_type=ZoneType.PIVOT_VALUE, zone_low=100.0, zone_high=102.0, zone_mid=101.0,
        source_tags=["GAMMA_WALL"],
    )
    _wire_common(monkeypatch, raw_levels={"vwap": 123.45}, zones=[zone])
    resp = srv.get_liquidity_snapshot(ticker="SPY", date="2020-01-02", snapshot="live", expiry=None, fusion=False)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert len(body["zones"]) == 1
    z = body["zones"][0]
    # honest absence -- not None-crashes-to-exception, not a distance computed against VWAP
    assert z["distance_to_spot"] is None
    assert z["spot_inside_zone"] is None
    assert isinstance(z["tradeable_score"], (int, float))  # neutral score, not a crash


def test_spot_used_for_scoring_reports_the_real_cached_spot_when_available(monkeypatch):
    """The companion positive control: when a real live spot IS available, it is reported as
    spot_used_for_scoring exactly as before, and the VWAP-fallback field stays null -- this fix
    narrows a false claim, it does not remove the real value when one genuinely exists."""
    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_liquidity_fusion_from_cache", lambda *a, **k: ([], 456.78, "n/a"))
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda *a, **k: None)
    import polling_adapter
    monkeypatch.setattr(
        polling_adapter, "fetch_bars_via_schwab_for_session",
        lambda *a, **k: [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    fake_out = _FakeSnapshotOutput("SPY", "2020-01-02", {"vwap": 123.45})
    monkeypatch.setattr(lve, "build_live_snapshot", lambda *a, **k: fake_out)
    resp = srv.get_liquidity_snapshot(ticker="SPY", date="2020-01-02", snapshot="live", expiry="2020-01-03", fusion=True)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert body["spot_used_for_scoring"] == 456.78
    assert body["spot_estimate_vwap_fallback"] is None


def test_schwab_auth_unavailable_propagates_503_not_a_generic_500(monkeypatch):
    """MEASURED 2026-09-11: get_client() raises HTTPException(503, ...) when Schwab auth is
    genuinely unavailable -- the blanket `except Exception` caught it too and re-issued it as a
    bare 500, discarding the real classification. Must now propagate as 503."""
    from fastapi import HTTPException

    def _raise_auth_unavailable():
        raise HTTPException(status_code=503, detail="Schwab auth failed: token_invalid")
    monkeypatch.setattr(srv, "get_client", _raise_auth_unavailable)
    resp = srv.get_liquidity_snapshot(ticker="SPY", date="2020-01-02", snapshot="live", expiry=None, fusion=False)
    assert resp.status_code == 503
    body = json.loads(resp.body)
    assert "token_invalid" in body["error"] or "Schwab auth failed" in body["error"]


def test_an_unrelated_crash_still_reports_500(monkeypatch):
    """Negative control: the new HTTPException branch must not swallow OTHER exceptions into a
    misleading 503 -- a genuine unexpected error still reports 500, unchanged."""
    def _boom():
        raise RuntimeError("something actually broke")
    monkeypatch.setattr(srv, "get_client", _boom)
    resp = srv.get_liquidity_snapshot(ticker="SPY", date="2020-01-02", snapshot="live", expiry=None, fusion=False)
    assert resp.status_code == 500
