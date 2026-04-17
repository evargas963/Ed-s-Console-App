"""
L1 light SSE backpressure: evict-oldest policy, identity invariant, latest-state retention.
"""
from __future__ import annotations

import asyncio
import queue
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_client_asyncio_queue_evict_oldest_preserves_latest():
    import server as srv

    q = asyncio.Queue(maxsize=2)
    srv._l1_put_l1_client_queue(q, {"n": 1})
    srv._l1_put_l1_client_queue(q, {"n": 2})
    assert q.qsize() == 2
    d0 = int(srv._l1_sse_diag.get("l1_light_sse_client_queue_evicted_oldest", 0))
    srv._l1_put_l1_client_queue(q, {"n": 3})
    assert q.qsize() == 2
    assert int(srv._l1_sse_diag.get("l1_light_sse_client_queue_evicted_oldest", 0)) >= d0 + 1
    assert q.get_nowait()["n"] == 2
    assert q.get_nowait()["n"] == 3


def test_thread_queue_evict_oldest_preserves_latest(monkeypatch):
    import server as srv

    small = queue.Queue(maxsize=2)
    monkeypatch.setattr(srv, "_l1_sse_thread_queue", small)
    sk = ("SPY", "__auto__")
    srv._l1_put_thread_queue_notify(sk, {"a": 1})
    srv._l1_put_thread_queue_notify(sk, {"a": 2})
    assert small.qsize() == 2
    d0 = int(srv._l1_sse_diag.get("l1_light_sse_thread_queue_evicted_oldest", 0))
    srv._l1_put_thread_queue_notify(sk, {"a": 3})
    assert small.qsize() == 2
    assert int(srv._l1_sse_diag.get("l1_light_sse_thread_queue_evicted_oldest", 0)) >= d0 + 1
    assert small.get_nowait()[1]["a"] == 2
    assert small.get_nowait()[1]["a"] == 3


def test_same_gen_ts_non_material_diff_does_not_increment_identity_violation():
    import server as srv

    srv._l1_last_emit_identity.clear()
    sk = ("SPY", "__auto__")
    base = {
        "l1_generation": 7,
        "_server_build_ts": 12345.0,
        "plane": "L1_context",
        "schema_version": 1,
        "merge_rule": "L0_plus_acknowledged_L2_snapshot",
        "spot": 500.0,
    }
    p1 = {
        **base,
        "as_of_ts": 1.0,
        "l1_instrumentation": {"x": 1},
        "l1_projection": {"cache_age_sec": 1.0, "mode": "x"},
    }
    p2 = {
        **base,
        "as_of_ts": 9.0,
        "l1_instrumentation": {"x": 2},
        "l1_projection": {"cache_age_sec": 99.0, "mode": "y"},
    }
    v0 = int(srv._l1_sse_diag.get("l1_payload_identity_violation", 0))
    srv._l1_record_payload_identity(sk, 7, p1)
    srv._l1_record_payload_identity(sk, 7, p2)
    assert int(srv._l1_sse_diag.get("l1_payload_identity_violation", 0)) == v0


def test_same_gen_ts_material_diff_increments_identity_violation():
    import server as srv

    srv._l1_last_emit_identity.clear()
    sk = ("SPY", "__auto__")
    p1 = {
        "l1_generation": 7,
        "_server_build_ts": 12345.0,
        "plane": "L1_context",
        "schema_version": 1,
        "merge_rule": "L0_plus_acknowledged_L2_snapshot",
        "spot": 500.0,
    }
    p2 = {**p1, "spot": 501.0}
    v0 = int(srv._l1_sse_diag.get("l1_payload_identity_violation", 0))
    srv._l1_record_payload_identity(sk, 7, p1)
    srv._l1_record_payload_identity(sk, 7, p2)
    assert int(srv._l1_sse_diag.get("l1_payload_identity_violation", 0)) >= v0 + 1


def test_diagnostics_l1_sse_light_has_policy_and_semantics():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/diagnostics/l1")
    assert r.status_code == 200
    light = r.json()["ed_l1"]["l1_sse_light"]
    assert "l1_sse_backpressure_policy" in light
    assert "evict_oldest" in light["l1_sse_backpressure_policy"]
    assert "l1_sse_thread_queue_fairness_policy" in light
    assert "global_fifo" in light["l1_sse_thread_queue_fairness_policy"]
    assert "l1_sse_field_semantics" in light
    assert light["l1_sse_field_semantics"]["l1_light_sse_client_queue_evicted_oldest"] == "authoritative_counter"


def test_fingerprint_deterministic_ignores_volatile_fields():
    import server as srv

    base_mat = {
        "plane": "L1_context",
        "schema_version": 1,
        "merge_rule": "L0_plus_acknowledged_L2_snapshot",
        "l1_generation": 1,
        "l2_snapshot_version_used": 3,
        "l2_merge_acknowledged": True,
        "l2_structural_scope_exact": True,
        "structural_context_stale": False,
        "l1_stale": False,
        "spot": 500.0,
        "ticker": "SPY",
        "selected_exp": None,
        "spot_anchors": {"vwap": 499.0, "vwap_side": "above", "dist_to_vwap_pts": 1.0},
        "order_flow": {"order_flow_regime": "x"},
        "liquidity_summary": {
            "behavior_label": "a",
            "absorption_score": 1,
            "continuation_score": 2,
        },
        "readiness_summary": {
            "order_flow_readiness": "ok",
            "structural_anchor_stale": False,
            "has_acknowledged_l2_snapshot": True,
        },
    }
    a = {
        **base_mat,
        "_server_build_ts": 100.0,
        "l1_instrumentation": {"l1_build_total": 1},
        "l1_projection": {
            "mode": "authoritative_cache_read",
            "cache_age_sec": 1.23,
            "l1_http_serve_max_age_sec": 60,
        },
        "order_flow_age_sec": 5.0,
        "brand_new_diagnostic_field": {"n": 1},
    }
    b = {
        **base_mat,
        "_server_build_ts": 100.0,
        "l1_instrumentation": {"l1_build_total": 999},
        "l1_projection": {
            "mode": "authoritative_cache_read",
            "cache_age_sec": 99.0,
            "l1_http_serve_max_age_sec": 60,
        },
        "order_flow_age_sec": 50.0,
        "brand_new_diagnostic_field": {"n": 9},
    }
    assert srv._l1_payload_fingerprint(a) == srv._l1_payload_fingerprint(b)


def test_fingerprint_changes_when_material_field_changes():
    import server as srv

    def _minimal(spot: float) -> dict:
        return {
            "plane": "L1_context",
            "schema_version": 1,
            "merge_rule": "L0_plus_acknowledged_L2_snapshot",
            "l1_generation": 1,
            "_server_build_ts": 100.0,
            "spot": spot,
            "ticker": "SPY",
        }

    a = _minimal(500.0)
    b = _minimal(501.0)
    assert srv._l1_payload_fingerprint(a) != srv._l1_payload_fingerprint(b)


def test_fingerprint_ignores_unknown_top_level_keys():
    import server as srv

    core = {
        "plane": "L1_context",
        "schema_version": 1,
        "merge_rule": "L0_plus_acknowledged_L2_snapshot",
        "l1_generation": 2,
        "spot": 100.0,
        "ticker": "QQQ",
    }
    assert srv._l1_payload_fingerprint({**core, "zzz_future_field": 1}) == srv._l1_payload_fingerprint(
        {**core, "zzz_future_field": 2}
    )


def test_fingerprint_changes_when_structural_field_changes():
    import server as srv

    def _base() -> dict:
        return {
            "plane": "L1_context",
            "schema_version": 1,
            "merge_rule": "L0_plus_acknowledged_L2_snapshot",
            "l1_generation": 1,
            "spot": 500.0,
            "ticker": "SPY",
            "zone": "A",
        }

    a = _base()
    b = {**_base(), "zone": "B"}
    assert srv._l1_payload_fingerprint(a) != srv._l1_payload_fingerprint(b)


def test_fingerprint_repeated_identical_payload_stable():
    import server as srv

    p = {
        "plane": "L1_context",
        "schema_version": 1,
        "merge_rule": "L0_plus_acknowledged_L2_snapshot",
        "l1_generation": 5,
        "spot": 1.234567891234,
        "ticker": "SPY",
    }
    fps = [srv._l1_payload_fingerprint(p) for _ in range(5)]
    assert len(set(fps)) == 1
