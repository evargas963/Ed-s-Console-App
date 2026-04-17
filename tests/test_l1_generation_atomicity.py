"""
Issue 22: L1 l1_generation — atomic increment, strict monotonicity, client ordering mirror.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reset_scope(srv, key: tuple) -> None:
    with srv._l1_generation_lock:
        srv._l1_generation.pop(key, None)
        srv._l1_last_generation_seen.pop(key, None)


def test_generation_monotonic_single_thread():
    import server as srv

    k = ("SEQ", "__auto__")
    _reset_scope(srv, k)
    n = 50
    gens = [srv._l1_next_generation(k) for _ in range(n)]
    for i in range(1, len(gens)):
        assert gens[i] > gens[i - 1]


def test_generation_monotonic_under_concurrency():
    import server as srv

    k = ("CONC", "__auto__")
    _reset_scope(srv, k)
    n_threads = 40
    per_thread = 25

    def worker():
        return [srv._l1_next_generation(k) for _ in range(per_thread)]

    out: list[int] = []
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futs = [pool.submit(worker) for _ in range(n_threads)]
        for f in as_completed(futs):
            out.extend(f.result())

    assert len(out) == n_threads * per_thread
    assert len(set(out)) == len(out), "duplicate generation values under concurrency"
    ordered = sorted(out)
    for i in range(1, len(ordered)):
        assert ordered[i] > ordered[i - 1]


def test_l1_generation_assign_instrumentation_increments():
    import server as srv

    k = ("INST", "__auto__")
    _reset_scope(srv, k)
    before = int(srv._l1_instrumentation.get("l1_generation_assign_total", 0))
    srv._l1_next_generation(k)
    after = int(srv._l1_instrumentation.get("l1_generation_assign_total", 0))
    assert after == before + 1


def _tier_b_monotonic_accept(
    gen_store: dict,
    scope_key: str,
    g: float,
    *,
    server_ts: float | None = None,
    ts_store: dict | None = None,
) -> bool:
    """Mirror static/js/l1_sse_guards.js: reject strictly lower l1_generation for a scope."""
    if g is None or not isinstance(g, (int, float)) or g != g:
        return True
    prev = gen_store.get(scope_key)
    last_ts = ts_store.get(scope_key) if ts_store else None
    if prev is not None and g < prev:
        return False
    if prev is not None and g == prev and ts_store is not None and server_ts is not None and last_ts is not None:
        if server_ts < last_ts:
            return False
    gen_store[scope_key] = max(prev or 0, g)
    if ts_store is not None and server_ts is not None and server_ts == server_ts:
        base = last_ts if last_ts is not None else 0.0
        ts_store[scope_key] = max(base, float(server_ts))
    return True


def test_sse_ordering_rejects_lower_generation_than_last_seen():
    """Light check: client must not accept out-of-order lower generation (matches Playwright guards)."""
    gen_store: dict = {}
    ts_store: dict = {}
    sk = "SPY|"
    assert _tier_b_monotonic_accept(gen_store, sk, 5.0, server_ts=200.0, ts_store=ts_store) is True
    assert _tier_b_monotonic_accept(gen_store, sk, 3.0, server_ts=300.0, ts_store=ts_store) is False
    assert _tier_b_monotonic_accept(gen_store, sk, 6.0, server_ts=250.0, ts_store=ts_store) is True
