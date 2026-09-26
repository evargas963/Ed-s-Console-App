"""
L1 light SSE backpressure: evict-oldest policy, identity invariant, latest-state retention.
"""
from __future__ import annotations

import asyncio
import queue
import sys
from pathlib import Path


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














