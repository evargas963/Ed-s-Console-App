"""
L1 cache lifecycle: LRU, TTL, cap, invariants, generation pruning, diagnostics.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_snap(as_of: float) -> dict:
    return {"as_of_ts": as_of, "_server_build_ts": as_of, "l1_instrumentation": {}}


@pytest.fixture
def l1_cache_clean(monkeypatch):
    import server as srv

    srv._l1_snapshot_cache.clear()
    srv._l1_scope_lru.clear()
    with srv._l1_generation_lock:
        srv._l1_generation.clear()
        srv._l1_last_generation_seen.clear()
    yield srv
    srv._l1_snapshot_cache.clear()
    srv._l1_scope_lru.clear()
    with srv._l1_generation_lock:
        srv._l1_generation.clear()
        srv._l1_last_generation_seen.clear()


def test_lru_eviction_order_least_recently_used_first(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 3)
    srv = l1_cache_clean
    k1 = ("AAA", "__auto__")
    k2 = ("BBB", "__auto__")
    k3 = ("CCC", "__auto__")
    k4 = ("DDD", "__auto__")
    t0 = 1_000_000.0
    srv._l1_snapshot_cache[k1] = _minimal_snap(t0)
    srv._l1_touch_scope(k1)
    srv._l1_snapshot_cache[k2] = _minimal_snap(t0)
    srv._l1_touch_scope(k2)
    srv._l1_snapshot_cache[k3] = _minimal_snap(t0)
    srv._l1_touch_scope(k3)
    srv._l1_cache_maintain(t0)
    assert list(srv._l1_scope_lru.keys()) == [k1, k2, k3]
    srv._l1_touch_scope(k1)
    assert list(srv._l1_scope_lru.keys()) == [k2, k3, k1]
    srv._l1_snapshot_cache[k4] = _minimal_snap(t0)
    srv._l1_touch_scope(k4)
    srv._l1_cache_maintain(t0)
    assert k1 in srv._l1_snapshot_cache
    assert k2 not in srv._l1_snapshot_cache
    assert k3 in srv._l1_snapshot_cache
    assert k4 in srv._l1_snapshot_cache
    assert k2 not in srv._l1_generation


def test_http_touch_updates_lru_like_hot_scope(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 3)
    srv = l1_cache_clean
    t0 = 2_000_000.0
    keys = [("H%d" % i, "__auto__") for i in range(3)]
    for k in keys:
        srv._l1_snapshot_cache[k] = _minimal_snap(t0)
        srv._l1_touch_scope(k)
    srv._l1_cache_maintain(t0)
    hot, cold_a, cold_b = keys[0], keys[1], keys[2]
    srv._l1_touch_scope(hot)
    kn = ("NEW", "__auto__")
    srv._l1_snapshot_cache[kn] = _minimal_snap(t0)
    srv._l1_touch_scope(kn)
    srv._l1_cache_maintain(t0)
    assert hot in srv._l1_snapshot_cache
    assert kn in srv._l1_snapshot_cache
    assert cold_a not in srv._l1_snapshot_cache
    assert cold_b in srv._l1_snapshot_cache


def test_ttl_eviction_removes_expired_even_if_in_lru(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_CACHE_ENTRY_TTL_SEC", 100.0)
    srv = l1_cache_clean
    now = 3_000_000.0
    k = ("TTL1", "e1")
    srv._l1_snapshot_cache[k] = _minimal_snap(now - 200.0)
    srv._l1_touch_scope(k)
    with srv._l1_generation_lock:
        srv._l1_generation[k] = 5
        srv._l1_last_generation_seen[k] = 5
    before_ttl = int(srv._l1_instrumentation["l1_cache_eviction_ttl_total"])
    srv._l1_cache_maintain(now)
    assert k not in srv._l1_snapshot_cache
    assert k not in srv._l1_scope_lru
    assert k not in srv._l1_generation
    assert int(srv._l1_instrumentation["l1_cache_eviction_ttl_total"]) == before_ttl + 1


def test_ttl_then_cap_both_increment_separate_counters(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 2)
    monkeypatch.setattr(lr, "L1_CACHE_ENTRY_TTL_SEC", 50.0)
    srv = l1_cache_clean
    now = 4_000_000.0
    k_old = ("OLD", "x")
    srv._l1_snapshot_cache[k_old] = _minimal_snap(now - 100.0)
    srv._l1_touch_scope(k_old)
    srv._l1_cache_maintain(now)
    assert int(srv._l1_instrumentation["l1_cache_eviction_ttl_total"]) >= 1
    k_a = ("A", "x")
    k_b = ("B", "x")
    k_c = ("C", "x")
    for kk in (k_a, k_b, k_c):
        srv._l1_snapshot_cache[kk] = _minimal_snap(now)
        srv._l1_touch_scope(kk)
    cap_before = int(srv._l1_instrumentation["l1_cache_eviction_cap_total"])
    srv._l1_cache_maintain(now)
    assert len(srv._l1_snapshot_cache) <= 2
    assert int(srv._l1_instrumentation["l1_cache_eviction_cap_total"]) == cap_before + 1


def test_bounded_cache_under_churn(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 5)
    srv = l1_cache_clean
    base = 5_000_000.0
    from planes.l1_cache_lifecycle import l1_cache_invariants

    for i in range(30):
        k = ("CHURN", "e%d" % i)
        srv._l1_snapshot_cache[k] = _minimal_snap(base + i)
        srv._l1_touch_scope(k)
        srv._l1_cache_maintain(base + i)
        inv = l1_cache_invariants(srv._l1_snapshot_cache, srv._l1_scope_lru)
        assert inv["keys_match"], inv
        assert len(srv._l1_snapshot_cache) <= 5
        assert len(srv._l1_scope_lru) <= 5


def test_generation_pruned_when_scope_evicted(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 1)
    srv = l1_cache_clean
    t = 6_000_000.0
    k1 = ("G1", "a")
    k2 = ("G2", "a")
    srv._l1_snapshot_cache[k1] = _minimal_snap(t)
    srv._l1_touch_scope(k1)
    with srv._l1_generation_lock:
        srv._l1_generation[k1] = 100
        srv._l1_last_generation_seen[k1] = 100
    srv._l1_snapshot_cache[k2] = _minimal_snap(t)
    srv._l1_touch_scope(k2)
    with srv._l1_generation_lock:
        srv._l1_generation[k2] = 1
        srv._l1_last_generation_seen[k2] = 1
    srv._l1_cache_maintain(t)
    assert len(srv._l1_snapshot_cache) == 1
    assert k1 not in srv._l1_generation
    surviving = k2 if k2 in srv._l1_snapshot_cache else k1
    assert srv._l1_generation.get(surviving, 0) >= 1


def test_reconcile_drops_lru_orphan(l1_cache_clean):
    srv = l1_cache_clean
    from planes.l1_cache_lifecycle import l1_cache_invariants, reconcile_lru_with_snapshot

    ghost = ("GHOST", "z")
    srv._l1_scope_lru[ghost] = None
    pruned = reconcile_lru_with_snapshot(srv._l1_snapshot_cache, srv._l1_scope_lru)
    assert pruned == 1
    assert ghost not in srv._l1_scope_lru
    assert l1_cache_invariants(srv._l1_snapshot_cache, srv._l1_scope_lru)["keys_match"]


def test_ensure_backfills_lru_when_cache_has_row(l1_cache_clean):
    srv = l1_cache_clean
    from planes.l1_cache_lifecycle import ensure_lru_covers_snapshot, l1_cache_invariants

    k = ("BF", "q")
    srv._l1_snapshot_cache[k] = _minimal_snap(7_000_000.0)
    n = ensure_lru_covers_snapshot(srv._l1_snapshot_cache, srv._l1_scope_lru)
    assert n == 1
    assert l1_cache_invariants(srv._l1_snapshot_cache, srv._l1_scope_lru)["keys_match"]


def test_diagnostics_exposes_lifecycle_and_invariants(l1_cache_clean):
    import server as srv
    from fastapi.testclient import TestClient

    srv._l1_snapshot_cache[("DX", "e")] = _minimal_snap(time.time())
    srv._l1_touch_scope(("DX", "e"))
    client = TestClient(srv.app)
    r = client.get("/api/diagnostics/l1")
    assert r.status_code == 200
    ed = r.json()["ed_l1"]
    assert ed["l1_cache_lifecycle"]["keys_match"] is True
    assert "l1_cache_eviction_ttl_total" in ed
    assert "l1_cache_eviction_cap_total" in ed
    assert ed["l1_cache_scope_count"] == len(srv._l1_snapshot_cache)


def test_repeated_maintain_idempotent_invariants(l1_cache_clean, monkeypatch):
    import planes.l1_runtime as lr
    from planes.l1_cache_lifecycle import l1_cache_invariants

    monkeypatch.setattr(lr, "L1_MAX_CACHE_SCOPES", 4)
    srv = l1_cache_clean
    now = 8_000_000.0
    for i in range(4):
        k = ("RP", str(i))
        srv._l1_snapshot_cache[k] = _minimal_snap(now)
        srv._l1_touch_scope(k)
    for _ in range(5):
        srv._l1_cache_maintain(now)
        assert l1_cache_invariants(srv._l1_snapshot_cache, srv._l1_scope_lru)["keys_match"]
