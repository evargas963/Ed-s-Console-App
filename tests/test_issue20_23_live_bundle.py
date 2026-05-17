"""
Issue 20 / 23 — coherent live decision bundle (transport + ordering guards).

Proves: monotonic stamping ties spot + decision fields; tick partial-patch helpers stay removed;
/api/state TTL bypass when SSE subscribers exist; client HTML generation-order guard present.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_stamp_decision_bundle_monotonic_and_spot_same_generation():
    from live_decision_bundle import stamp_decision_bundle

    d = {"spot": 100.0, "zone": "test_zone", "vwap_side": "above"}
    stamp_decision_bundle(d)
    g0 = d["decision_generation_id"]
    ts0 = d["decision_timestamp_utc"]
    assert isinstance(g0, int) and g0 > 0
    assert isinstance(ts0, float) and ts0 > 0
    d2 = {"spot": 101.0, "zone": "other"}
    stamp_decision_bundle(d2)
    assert d2["decision_generation_id"] > g0
    assert d["decision_generation_id"] == g0
    assert d["spot"] == 100.0 and d["zone"] == "test_zone"


def test_tick_partial_patch_helpers_removed_from_server():
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "_patch_snapshot_with_fresh_order_flow" not in src
    assert "_ORDER_FLOW_PATCH_KEYS" not in src
    assert "sse_live" in src
    assert "sse_live = _sse_subscribers.get" in src


def test_sse_broadcast_only_passes_full_fetch_result():
    """No alternate partial payload may be queued to SSE clients (Issue 20/23)."""
    import re

    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    pat = re.compile(r"_broadcast_snapshot\s*\(\s*result\s*\)")
    hits = [
        ln
        for ln in src.splitlines()
        if pat.search(ln) and "def _broadcast_snapshot" not in ln and "async def _broadcast_snapshot" not in ln
    ]
    assert len(hits) == 1, f"expected exactly 1 _broadcast_snapshot(result) call site (Tier C bg worker), got {hits!r}"


def test_index_html_rejects_older_decision_generation():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "_lastRenderedDecisionGen" in html
    assert "decision_generation_id" in html
    assert "_decGen < _prevGen" in html
    assert "canonical snapshot" in html.lower() or "render(d) only" in html


def test_index_html_render_return_gates_live_and_last_render_ts():
    """Issue 24: gated render() return — do not bump _lastRenderTs when render() drops a frame."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "return true" in html and "return false" in html
    assert html.count("_lastRenderTs = Date.now()") == 6
    for needle in ("if (_didRender) {", "if (_didRenderPoll) {", "if (_didRenderSse) {"):
        assert needle in html, f"missing {needle!r}"


def test_index_html_sse_badge_conn_on_open_live_after_payload():
    """SSE badge: CONNECTING/CONN while handshake or socket-only; LIVE only after payload passes guards."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "_setSseUi('socket_open'" in html
    assert "lbl.textContent = 'CONN'" in html
    start = html.find("es.onmessage = (event)")
    assert start != -1
    needle = "const _didRenderSse = render(data, 'sse')"
    end = html.find(needle, start)
    assert end != -1
    assert "_setSseUi('live'" in html[start:end]


def test_client_render_ordering_logic():
    """Mirror static/index.html: older generations must not advance UI state."""

    def apply_render(prev_gen: float, payload_gen: float | None) -> float:
        dec = float(payload_gen) if payload_gen is not None else float("nan")
        if dec == dec:  # finite
            if dec < prev_gen:
                return prev_gen
            return max(prev_gen, dec)
        return prev_gen

    assert apply_render(10, 5) == 10
    assert apply_render(10, 12) == 12
    assert apply_render(10, None) == 10


@pytest.fixture()
def _cache_test_key():
    import server as srv

    key = ("ZZZ_ISSUE20_23", "2099-01-01")
    srv._state_cache.pop(key, None)
    prev_sub = srv._sse_subscribers.pop(key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.clear()
    yield key, srv
    srv._state_cache.pop(key, None)
    if prev_sub is not None:
        srv._sse_subscribers[key] = prev_sub
    else:
        srv._sse_subscribers.pop(key, None)


def test_api_analytics_light_is_tier_b_fast_path():
    """L1 /api/analytics/light — formal plane contract; no Tier C pipeline."""
    from starlette.testclient import TestClient

    import server as srv

    with TestClient(srv.app) as client:
        r = client.get("/api/analytics/light", params={"ticker": "SPY"})
        assert r.status_code == 200
        j = r.json()
        assert j.get("plane") == "L1_context"
        assert j.get("merge_rule") == "L0_plus_acknowledged_L2_snapshot"
        assert j.get("_tier") == "B_light"
        assert j.get("_endpoint") == "/api/analytics/light"
        assert "l2_snapshot_version_used" in j
        assert "l1_generation" in j
        assert "order_flow" in j
        assert "b_light_generated_at" in j
        assert "tier_b_structural" in j


def test_api_state_bypasses_cache_when_sse_subscribers(monkeypatch, _cache_test_key):
    """With active SSE for (ticker, expiry), REST returns stale-while-refresh and schedules background fetch."""
    key, srv = _cache_test_key
    ticker, exp = key
    monkeypatch.setattr(srv, "VIEWER_SSE_REFRESH_SEC", 99999.0)
    monkeypatch.setattr(srv, "CACHE_TTL", 99999.0)
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(t: str, e: str | None, **kwargs):
        calls.append((t, e))
        out = {
            "ticker": t,
            "selected_exp": e,
            "spot": 500.0 + len(calls),
            "decision_generation_id": 424200 + len(calls),
            "_server_build_ts": time.time(),
        }
        srv._state_cache[(t.upper().strip(), e)] = {
            "ts": time.time(),
            "generated_at": time.time(),
            "analytics_version": len(calls),
            "ms_dict": out,
            "pcr_val": None,
            "spot_f": out["spot"],
            "vix": None,
            "price_levels": None,
            "pl_date": "",
            "pl_mono": None,
        }
        return out

    monkeypatch.setattr(srv, "_fetch_state", fake_fetch)
    stale = {
        "ticker": ticker,
        "selected_exp": exp,
        "spot": 1.0,
        "decision_generation_id": 1,
    }
    _now = time.time()
    srv._state_cache[key] = {
        "ts": _now,
        "generated_at": _now,
        "analytics_version": 1,
        "ms_dict": stale,
        "pcr_val": None,
        "spot_f": 1.0,
        "vix": None,
        "price_levels": None,
        "pl_date": "",
        "pl_mono": None,
    }

    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r_hit = client.get("/api/state", params={"ticker": ticker, "expiry": exp})
        assert r_hit.status_code == 200
        body = r_hit.json()
        assert body.get("spot") == 1.0
        assert calls == []

        srv._sse_subscribers[key] = 1
        r_miss = client.get("/api/state", params={"ticker": ticker, "expiry": exp})
        assert r_miss.status_code == 200
        body2 = r_miss.json()
        assert body2.get("spot") == 1.0
        assert body2.get("analytics_stale") is True
        for _ in range(100):
            time.sleep(0.02)
            if calls:
                break
        assert (ticker, exp) in calls
        r3 = client.get("/api/state", params={"ticker": ticker, "expiry": exp})
        assert r3.status_code == 200
        body3 = r3.json()
        assert body3.get("spot", 0) > stale["spot"]
        assert body3.get("decision_generation_id", 0) >= 424201


def test_tick_trigger_zone_desync_from_bias_delta():
    """Stored zone must match derive_zone(bias_signal, net_delta) or we force a full recompute."""
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "bias_signal": "Neutral",
        "net_delta": 0.0,
        "zone": "breakdown",
        "decision_timestamp_utc": time.time(),
    }
    assert tick_triggers_coherent_refresh(md, None, None) is True


def test_tick_trigger_vwap_side_flip_at_stream_spot():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 99.0,
        "vwap": 100.0,
        "vwap_side": "below",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 110.0,
        "kl_put_gamma_wall": 90.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 11.0,
        "nearest_below_dist": 9.0,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": "Put g-Wall",
    }
    assert tick_triggers_coherent_refresh(md, 100.01, None) is True


def test_tick_trigger_nearest_distance_bucket_change():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 100.0,
        "vwap": 95.0,
        "vwap_side": "above",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 102.0,
        "kl_put_gamma_wall": 98.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 2.0,
        "nearest_below_dist": 2.0,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": "Put g-Wall",
    }
    assert tick_triggers_coherent_refresh(md, 101.6, None) is True


def test_tick_trigger_nearest_wall_identity_change():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 100.0,
        "vwap": 50.0,
        "vwap_side": "above",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 101.0,
        "kl_put_gamma_wall": 105.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 1.0,
        "nearest_below_dist": None,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": None,
    }
    assert tick_triggers_coherent_refresh(md, 104.0, None) is True


def test_tick_trigger_session_bucket_boundary(monkeypatch):
    from datetime import datetime

    from zoneinfo import ZoneInfo

    from live_decision_bundle import tick_triggers_coherent_refresh

    monkeypatch.setattr("market_context._derive_session", lambda: "Pre-Market")
    ET = ZoneInfo("America/New_York")
    dec = datetime(2026, 1, 6, 9, 20, tzinfo=ET).timestamp()
    now = datetime(2026, 1, 6, 9, 35, tzinfo=ET).timestamp()
    md = {
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "decision_timestamp_utc": dec,
        "session_label": "Pre-Market",
    }
    assert tick_triggers_coherent_refresh(md, None, None, now_ts=now) is True


def test_tick_trigger_session_label_boundary(monkeypatch):
    from live_decision_bundle import tick_triggers_coherent_refresh

    monkeypatch.setattr("market_context._derive_session", lambda: "RTH")
    md = {
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "session_label": "Pre-Market",
        "decision_timestamp_utc": time.time(),
    }
    assert tick_triggers_coherent_refresh(md, None, None) is True
