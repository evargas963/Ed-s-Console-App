"""
Issue 22: L1 l1_generation — atomic increment, strict monotonicity, client ordering mirror.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


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
    before = int(srv._l1_instrumentation["l1_generation_assign_total"])
    srv._l1_next_generation(k)
    after = int(srv._l1_instrumentation["l1_generation_assign_total"])
    assert after == before + 1


# Client-side out-of-order-generation rejection (static/js/l1_sse_guards.js's
# l1ApplyTierBLightMonotonic) is proven against the REAL shipped JS by
# tests/l1_sse_guards_node.mjs (run via test_l1_sse_guards_client.py), not mirrored here —
# a hand-copied Python re-implementation of that guard used to live in this file and was
# removed 2026-09-15 (same defect class as the mirror test_l1_remediation.py documents
# retiring: testing a local copy proves nothing about the shipped client rule).
