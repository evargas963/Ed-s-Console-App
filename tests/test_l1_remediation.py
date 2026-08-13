"""
L1 remediation — explicit-expiry L2 scope, l1_stale truth, persisted snapshots, instrumentation, hooks.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def l1_clean_spy(monkeypatch):
    """Isolate SPY rows in server caches for this test."""
    import server as srv

    keys = [k for k in list(srv._state_cache.keys()) if isinstance(k, tuple) and k and k[0] == "SPY"]
    backup = {k: srv._state_cache[k] for k in keys}
    for k in keys:
        srv._state_cache.pop(k, None)
    for k in list(srv._l1_snapshot_cache.keys()):
        if k[0] == "SPY":
            srv._l1_snapshot_cache.pop(k, None)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 500.0, "bid": 499.0, "ask": 501.0},
    )
    monkeypatch.setattr(srv, "_l2_refresh_in_progress_for_l1", lambda *a, **k: False)
    monkeypatch.setattr(srv._lmp, "apply_l1_live_quote_overlay", lambda *a, **k: None)
    yield srv
    for k in list(srv._state_cache.keys()):
        if isinstance(k, tuple) and k and k[0] == "SPY":
            srv._state_cache.pop(k, None)
    srv._state_cache.update(backup)


def test_l1_explicit_expiry_cache_miss_no_wrong_expiry_merge(l1_clean_spy):
    """Explicit expiry with no L2 row must not merge another expiry's ms_dict."""
    srv = l1_clean_spy
    t = "SPY"
    e_other = "2026-06-01"
    e_req = "2027-01-15"
    srv._state_cache[(t, e_other)] = {
        "ts": time.time(),
        "generated_at": time.time(),
        "analytics_version": 42,
        "ms_dict": {
            "zone": "ZONE_FROM_OTHER_EXPIRY",
            "selected_exp": e_other,
        },
    }
    out = srv._project_l1(t, e_req, reason="test")
    assert out.get("l2_merge_acknowledged") is False
    assert out.get("l2_structural_scope_exact") is False
    assert out.get("selected_exp") == e_req
    assert out.get("zone") != "ZONE_FROM_OTHER_EXPIRY"


def test_l1_auto_mode_uses_latest_when_present(l1_clean_spy):
    srv = l1_clean_spy
    t = "SPY"
    e = "2026-06-01"
    srv._state_cache[(t, e)] = {
        "ts": time.time(),
        "generated_at": time.time(),
        "analytics_version": 1,
        "ms_dict": {"zone": "FROM_LATEST", "selected_exp": e},
    }
    out = srv._project_l1(t, None, reason="test")
    assert out.get("l2_merge_acknowledged") is True
    assert out.get("zone") == "FROM_LATEST"


def test_l1_no_l2_cache_merge_unacknowledged(l1_clean_spy):
    srv = l1_clean_spy
    out = srv._project_l1("SPY", None, reason="test")
    assert out.get("l2_merge_acknowledged") is False
    assert (out.get("l2_snapshot_version_used") or 0) == 0


def test_l1_inflight_semantics(l1_clean_spy, monkeypatch):
    srv = l1_clean_spy
    monkeypatch.setattr(srv, "_l2_refresh_in_progress_for_l1", lambda *a, **k: True)
    out = srv._project_l1("SPY", None, reason="test")
    assert out.get("l2_analytics_refresh_in_progress") is True


def test_l1_copies_gamma_flip_and_gamma_walls_from_acknowledged_l2():
    """B_light must copy flip/walls from L2 ms_dict the same way it copies PIN/HVL.

    Console KEY LEVELS and exec-gflip read these from the light payload; omitting
    them dashes the Console while /api/state and /api/terrain still show the levels.
    L1 never recomputes — copy-only from the acknowledged snapshot.
    """
    from math_snapshot_derive import derive_vwap_side

    from planes.context_light import L1BuildContext, _STRUCTURAL_KEYS, build_l1_context

    for k in ("kl_gamma_flip", "kl_call_gamma_wall", "kl_put_gamma_wall"):
        assert k in _STRUCTURAL_KEYS, k

    now = time.time()
    ctx = L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"spot": 779.5, "bid": 779.4, "ask": 779.6},
        l2_cache_entry={
            "analytics_version": 9,
            "generated_at": now,
            "ts": now,
            "ms_dict": {
                "kl_gamma_pin": 780.0,
                "kl_gamma_flip": 768.36,
                "kl_call_gamma_wall": 780.0,
                "kl_put_gamma_wall": 770.0,
                "kl_hvl": 780.0,
                "kl_net_gex": 4.41e9,
            },
        },
        now_ts=now,
        l2_analytics_refresh_in_progress=True,
        l1_generation=4,
    )
    out = build_l1_context(ctx, derive_vwap_side_fn=derive_vwap_side, order_flow_compact={})
    assert out["_tier"] == "B_light"
    assert out["kl_gamma_pin"] == 780.0
    assert out["kl_gamma_flip"] == 768.36
    assert out["kl_call_gamma_wall"] == 780.0
    assert out["kl_put_gamma_wall"] == 770.0
    structural = out["tier_b_structural"]
    assert structural["kl_gamma_flip"] == 768.36
    assert structural["kl_call_gamma_wall"] == 780.0
    assert structural["kl_put_gamma_wall"] == 770.0
    # Absent / None L2 values stay omitted (same rule as PIN) — no fabricated dash fill.
    ctx_missing = L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"spot": 779.5, "bid": 779.4, "ask": 779.6},
        l2_cache_entry={
            "analytics_version": 9,
            "generated_at": now,
            "ts": now,
            "ms_dict": {"kl_gamma_pin": 780.0, "kl_gamma_flip": None},
        },
        now_ts=now,
        l2_analytics_refresh_in_progress=True,
        l1_generation=5,
    )
    out_missing = build_l1_context(
        ctx_missing, derive_vwap_side_fn=derive_vwap_side, order_flow_compact={}
    )
    assert "kl_gamma_flip" not in out_missing
    assert "kl_gamma_flip" not in out_missing["tier_b_structural"]
    assert out_missing["kl_gamma_pin"] == 780.0


def test_index_html_tier_b_paints_kl_flip_from_light_payload():
    """renderTierBLight must paint KEY LEVELS + exec-gflip once B_light carries the fields."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    start = html.index("function renderTierBLight")
    end = html.index("\nfunction ", start + 1)
    body = html[start:end]
    assert "__renderKeyLevelsLive" in body
    assert "exec-gflip" in body
    assert "kl_gamma_flip" in body
    assert "kl_call_gamma_wall" in body
    assert "kl_put_gamma_wall" in body


def test_l1_stale_truth_spot_unusable():
    from math_snapshot_derive import derive_vwap_side

    from planes.context_light import L1BuildContext, build_l1_context

    ctx = L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"spot": 0, "bid": 1, "ask": 2},
        l2_cache_entry=None,
        now_ts=time.time(),
        l2_analytics_refresh_in_progress=False,
        l1_generation=1,
    )
    out = build_l1_context(ctx, derive_vwap_side_fn=derive_vwap_side)
    assert out["l1_stale"] is True

    ctx2 = L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"bid": 1, "ask": 2},
        l2_cache_entry=None,
        now_ts=time.time(),
        l2_analytics_refresh_in_progress=False,
        l1_generation=2,
    )
    out2 = build_l1_context(ctx2, derive_vwap_side_fn=derive_vwap_side)
    assert out2["l1_stale"] is True


def test_l1_quote_hook_persists_snapshot(l1_clean_spy):
    srv = l1_clean_spy
    srv._state_cache[("SPY", "2099-02-01")] = {
        "ts": time.time(),
        "ms_dict": {"zone": "Z"},
        "analytics_version": 1,
    }
    srv._l1_snapshot_cache.clear()
    srv._l1_on_quote_updated("SPY")
    assert ("SPY", "2099-02-01") in srv._l1_snapshot_cache
    snap = srv._l1_snapshot_cache[("SPY", "2099-02-01")]
    assert snap.get("l1_instrumentation", {}).get("l1_build_reason") == "quote_material"


def test_l1_project_never_calls_tier_c_merge_into_state(monkeypatch, l1_clean_spy):
    """L1 compute must not use merge_into_state (Tier C); L0 overlay is apply_l1_live_quote_overlay on HTTP read."""
    srv = l1_clean_spy

    def boom(*a, **k):
        raise AssertionError("merge_into_state must not be invoked from _project_l1")

    monkeypatch.setattr(srv._lmp, "merge_into_state", boom)
    srv._project_l1("SPY", None, reason="test")


def test_quote_material_skip_when_inputs_unchanged(l1_clean_spy):
    from planes.context_light import compute_order_flow_compact, order_flow_compact_signature

    srv = l1_clean_spy
    row = srv._lmp.get_quote("SPY")
    of_sig = order_flow_compact_signature(compute_order_flow_compact("SPY", row))
    srv._project_l1("SPY", None, reason="seed")
    skip0 = int(srv._l1_instrumentation["l1_quote_material_skip_total"])
    srv._l1_maybe_rebuild_quote_scope("SPY", None, of_sig=of_sig)
    assert srv._l1_instrumentation["l1_quote_material_skip_total"] > skip0


def test_l1_instrumentation_fields(l1_clean_spy):
    srv = l1_clean_spy
    out = srv._project_l1("SPY", None, reason="unit_test")
    inst = out.get("l1_instrumentation") or {}
    assert inst.get("l1_build_reason") == "unit_test"
    assert inst.get("l1_build_scope", {}).get("ticker") == "SPY"
    assert inst.get("l1_build_scope", {}).get("expiry") == "__auto__"
    assert "l1_build_total" in inst and inst["l1_build_total"] >= 1
    assert "l2_merge_acknowledged" in inst


def test_quote_of_signature_change_triggers_rebuild(l1_clean_spy):
    srv = l1_clean_spy
    srv._project_l1("SPY", None, reason="seed")
    k = ("SPY", "__auto__")
    old_sig = (("order_flow_verdict", "OLDVERDICT"),)
    new_sig = (("order_flow_verdict", "NEWVERDICT"),)
    srv._l1_snapshot_cache[k]["_l1_of_signature"] = old_sig
    srv._l1_maybe_rebuild_quote_scope("SPY", None, of_sig=new_sig)
    assert int(srv._l1_instrumentation["l1_build_by_reason"].get("quote_material_of", 0)) >= 1


def test_http_cache_hit_includes_order_flow_freshness_fields(monkeypatch):
    import server as srv
    from planes import l1_events

    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: {"spot": 400.0, "bid": 399.0, "ask": 401.0})
    monkeypatch.setattr(srv._lmp, "apply_l1_live_quote_overlay", lambda *a, **k: None)
    srv._l1_snapshot_cache.clear()
    srv._l1_scope_lru.clear()
    d1 = l1_events.notify_ticker_expiry_changed("SPY", None)
    assert "order_flow_age_sec" in d1
    assert "order_flow_stale" in d1
    assert d1.get("order_flow_as_of_ts") is not None
    d2 = l1_events.notify_ticker_expiry_changed("SPY", None)
    assert d2.get("l1_projection", {}).get("mode") == "authoritative_cache_read"
    assert "order_flow_age_sec" in d2


def test_ttl_eviction_removes_scope_and_lru(monkeypatch):
    import planes.l1_runtime as lr

    import server as srv

    monkeypatch.setattr(lr, "L1_CACHE_ENTRY_TTL_SEC", 0.001)
    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: {"spot": 100.0, "bid": 99.0, "ask": 101.0})
    srv._l1_snapshot_cache.clear()
    srv._l1_scope_lru.clear()
    srv._project_l1("SPY", None, reason="ttl_seed")
    k = ("SPY", "__auto__")
    time.sleep(0.02)
    srv._l1_cache_maintain(time.time())
    assert k not in srv._l1_snapshot_cache
    assert k not in srv._l1_scope_lru


def test_lru_eviction_keeps_touched_scope(monkeypatch):
    import planes.l1_runtime as lr

    import server as srv

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 2)
    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: {"spot": 100.0, "bid": 99.0, "ask": 101.0})
    srv._l1_snapshot_cache.clear()
    srv._l1_scope_lru.clear()
    srv._project_l1("AAA", None, reason="a")
    srv._project_l1("BBB", None, reason="b")
    srv._project_l1("CCC", None, reason="c")
    assert ("AAA", "__auto__") not in srv._l1_snapshot_cache
    srv._l1_touch_scope(("BBB", "__auto__"))
    srv._project_l1("DDD", None, reason="d")
    assert ("BBB", "__auto__") in srv._l1_snapshot_cache


def test_notify_ticker_expiry_changed_cold_start_then_cache_read(monkeypatch):
    import server as srv
    from planes import l1_events

    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: {"spot": 400.0, "bid": 399.0, "ask": 401.0})
    monkeypatch.setattr(srv._lmp, "apply_l1_live_quote_overlay", lambda *a, **k: None)
    srv._l1_snapshot_cache.pop(("SPY", "__auto__"), None)
    d = l1_events.notify_ticker_expiry_changed("SPY", None)
    assert d.get("l1_instrumentation", {}).get("l1_build_reason") == "cold_start"
    d2 = l1_events.notify_ticker_expiry_changed("SPY", None)
    assert d2.get("l1_projection", {}).get("mode") == "authoritative_cache_read"
    assert d2.get("l1_instrumentation", {}).get("l1_projection_read") is True


def test_l1_diagnostics_endpoint_exposes_ed_l1(monkeypatch):
    from starlette.testclient import TestClient

    import server as srv

    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 400.0, "bid": 399.0, "ask": 401.0},
    )
    with TestClient(srv.app) as client:
        r = client.get("/api/diagnostics/l1")
        assert r.status_code == 200
        j = r.json()
        assert "ed_l1" in j
        assert "l1_build_total" in j["ed_l1"]
        assert "l1_build_by_reason" in j["ed_l1"]
        assert "policy" in j["ed_l1"]
        assert "L1_ORDER_FLOW_STALE_SEC" in j["ed_l1"]["policy"]
        assert "l1_lru_order_len" in j["ed_l1"]


def test_index_html_l1_scope_and_generation_guards():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "_l1GenByScope" in html
    assert "renderTierBLight" in html
    assert "l1_generation" in html
    assert "REJECTED stale l1_generation" in html or "stale l1_generation" in html


def test_index_html_l1_quote_vs_of_freshness_ui():
    """L1 UI trust: separate quote vs OF chips, server field wiring, throttle guard."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "b-l1-label-quote" in html
    assert "b-l1-label-of" in html
    assert "b-l1-dot-quote" in html
    assert "b-l1-dot-of" in html
    assert "l1QuoteFreshTier" in html
    assert "l1OfFreshTier" in html
    assert "quote_overlay_age_sec" in html
    assert "order_flow_age_sec" in html
    assert "order_flow_stale" in html
    assert "l1ShouldPaintFreshness" in html
    assert "_l1FreshnessPaint" in html


def test_client_l1_generation_guard_logic_mirror():
    """Mirror index.html: do not accept older l1_generation for the same scope key."""

    def accept(prev: float | None, g: float) -> bool:
        if prev is not None and g < prev:
            return False
        return True

    assert accept(5.0, 3.0) is False
    assert accept(5.0, 6.0) is True
    assert accept(None, 1.0) is True
