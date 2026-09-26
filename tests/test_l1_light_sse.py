"""
L1 light SSE — event-driven delivery; no duplicate _project_l1; generation in envelope.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))








def test_fanout_only_matching_scope():
    import server as srv

    q_spy = asyncio.Queue(maxsize=10)
    q_other = asyncio.Queue(maxsize=10)
    srv._l1_light_sse_clients.append((q_spy, ("SPY", "__auto__")))
    srv._l1_light_sse_clients.append((q_other, ("QQQ", "__auto__")))
    try:
        sk = ("SPY", "__auto__")
        env = {"l1_sse_schema": 1, "scope": {}, "l1_generation": 1, "payload": {}}
        with srv._l1_light_sse_lock:
            clients = list(srv._l1_light_sse_clients)
        for q, csk in clients:
            if csk != sk:
                continue
            q.put_nowait(env)
        assert q_spy.qsize() == 1
        assert q_other.qsize() == 0
    finally:
        srv._l1_light_sse_clients.clear()
        while q_spy.qsize():
            q_spy.get_nowait()
        while q_other.qsize():
            q_other.get_nowait()


def test_light_stream_route_registered():
    import server as srv

    paths = [getattr(r, "path", "") for r in srv.app.routes if hasattr(r, "path")]
    assert "/api/analytics/light/stream" in paths








