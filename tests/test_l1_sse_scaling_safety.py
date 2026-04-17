"""
Issue 31 — L1 light SSE multi-connection scaling: ordering, monotonicity, caps, fanout characterization.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_multiple_connections_ordering_per_queue():
    """Fanout delivers the same sequence order to each subscribed connection (per-queue FIFO)."""
    import server as srv

    q1 = asyncio.Queue(maxsize=32)
    q2 = asyncio.Queue(maxsize=32)
    sk = ("SPY", "__auto__")
    srv._l1_light_sse_clients.extend([(q1, sk), (q2, sk)])
    try:

        async def drain():
            g1 = []
            g2 = []
            for i in range(3):
                env = {"l1_sse_schema": 1, "l1_generation": i, "payload": {"i": i}}
                srv._l1_put_l1_client_queue(q1, env)
                srv._l1_put_l1_client_queue(q2, env)
            for _ in range(3):
                g1.append((await q1.get())["l1_generation"])
                g2.append((await q2.get())["l1_generation"])
            return g1, g2

        g1, g2 = asyncio.run(drain())
        assert g1 == [0, 1, 2]
        assert g2 == [0, 1, 2]
    finally:
        srv._l1_light_sse_clients.clear()


def test_monotonicity_across_duplicate_scopes():
    """Per-connection streams preserve non-decreasing l1_generation when events are applied in order."""
    import server as srv

    q1 = asyncio.Queue(maxsize=32)
    q2 = asyncio.Queue(maxsize=32)
    sk = ("SPY", "__auto__")
    srv._l1_light_sse_clients.extend([(q1, sk), (q2, sk)])
    try:

        async def drain():
            for gen in (1, 2, 3):
                env = {"l1_sse_schema": 1, "l1_generation": gen, "payload": {}}
                srv._l1_put_l1_client_queue(q1, env)
                srv._l1_put_l1_client_queue(q2, env)
            last = -1
            for _ in range(3):
                g = (await q1.get())["l1_generation"]
                assert g >= last
                last = g
            last = -1
            for _ in range(3):
                g = (await q2.get())["l1_generation"]
                assert g >= last
                last = g

        asyncio.run(drain())
    finally:
        srv._l1_light_sse_clients.clear()


def test_duplicate_scope_connections_same_payload_fingerprint_per_event():
    """Two connections on the same scope receive the same material for a given fanout envelope."""
    import server as srv

    q1 = asyncio.Queue(maxsize=32)
    q2 = asyncio.Queue(maxsize=32)
    sk = ("SPY", "__auto__")
    srv._l1_light_sse_clients.extend([(q1, sk), (q2, sk)])
    try:
        env = {
            "l1_sse_schema": 1,
            "l1_generation": 7,
            "l1_payload_fingerprint": "abc",
            "payload": {"x": 1},
        }

        async def both():
            srv._l1_put_l1_client_queue(q1, env)
            srv._l1_put_l1_client_queue(q2, env)
            a = await q1.get()
            b = await q2.get()
            return a, b

        a, b = asyncio.run(both())
        assert a["l1_payload_fingerprint"] == b["l1_payload_fingerprint"]
        assert a["l1_generation"] == b["l1_generation"]
    finally:
        srv._l1_light_sse_clients.clear()


def _fake_sse_request(host: str = "10.0.0.1"):
    """Minimal ASGI scope so _l1_sse_remote_key sees client host (avoids TestClient multi-stream deadlock)."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/analytics/light/stream",
        "raw_path": b"/api/analytics/light/stream",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": (host, 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_global_connection_cap_returns_503(monkeypatch):
    import server as srv
    from fastapi import HTTPException

    monkeypatch.setattr(srv, "MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL", 2)
    monkeypatch.setattr(srv, "MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE", 8)
    sk_spy = ("SPY", "__auto__")
    sk_qqq = ("QQQ", "__auto__")
    sk_iwm = ("IWM", "__auto__")
    q1, rs1 = srv._l1_light_sse_try_reserve(_fake_sse_request("10.0.0.1"), sk_spy)
    q2, rs2 = srv._l1_light_sse_try_reserve(_fake_sse_request("10.0.0.2"), sk_qqq)
    try:
        with pytest.raises(HTTPException) as ei:
            srv._l1_light_sse_try_reserve(_fake_sse_request("10.0.0.3"), sk_iwm)
        assert ei.value.status_code == 503
        assert int(srv._l1_sse_diag.get("l1_light_sse_rejected_total", 0)) >= 1
    finally:
        srv._l1_light_sse_release(q1, sk_spy, rs1)
        srv._l1_light_sse_release(q2, sk_qqq, rs2)


def test_per_scope_connection_cap_returns_503(monkeypatch):
    import server as srv
    from fastapi import HTTPException

    monkeypatch.setattr(srv, "MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL", 64)
    monkeypatch.setattr(srv, "MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE", 2)
    sk = ("SPY", "__auto__")
    req = _fake_sse_request("10.0.0.1")
    q1, rs1 = srv._l1_light_sse_try_reserve(req, sk)
    q2, rs2 = srv._l1_light_sse_try_reserve(req, sk)
    try:
        with pytest.raises(HTTPException) as ei:
            srv._l1_light_sse_try_reserve(req, sk)
        assert ei.value.status_code == 503
    finally:
        srv._l1_light_sse_release(q1, sk, rs1)
        srv._l1_light_sse_release(q2, sk, rs2)


def test_duplicate_same_client_same_scope_increments_warn_counter(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE", 8)
    sk = ("SPY", "__auto__")
    req = _fake_sse_request("10.0.0.7")
    w0 = int(srv._l1_sse_diag.get("l1_light_sse_duplicate_scope_same_client_warn_total", 0))
    q1, rs1 = srv._l1_light_sse_try_reserve(req, sk)
    q2, rs2 = srv._l1_light_sse_try_reserve(req, sk)
    try:
        w1 = int(srv._l1_sse_diag.get("l1_light_sse_duplicate_scope_same_client_warn_total", 0))
        assert w1 >= w0 + 1
    finally:
        srv._l1_light_sse_release(q1, sk, rs1)
        srv._l1_light_sse_release(q2, sk, rs2)


def test_diagnostics_include_scaling_fields():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    d = client.get("/api/diagnostics/l1").json()["ed_l1"]["l1_sse_light"]
    assert "l1_light_sse_connections_by_scope" in d
    assert d["l1_light_sse_limit_max_total"] == srv.MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL
    assert d["l1_light_sse_limit_max_per_scope"] == srv.MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE


def test_fanout_cost_characterization_microbenchmark():
    """
    Light characterization: fanout time scales ~linearly with subscriber count (no strict SLA).
    Uses private queue put path only — not a browser or network measurement.
    """
    import server as srv

    for n in (1, 5, 10):
        queues = [asyncio.Queue(maxsize=64) for _ in range(n)]
        sk = ("ZZT", "__auto__")
        srv._l1_light_sse_clients.extend([(q, sk) for q in queues])
        try:
            env = {"l1_sse_schema": 1, "l1_generation": 1, "payload": {}}
            t0 = time.perf_counter()
            for q in queues:
                srv._l1_put_l1_client_queue(q, env)
            elapsed = time.perf_counter() - t0
            assert elapsed < 1.0, f"fanout n={n} took {elapsed}s"
            for q in queues:
                assert q.qsize() == 1
        finally:
            srv._l1_light_sse_clients.clear()
            for q in queues:
                while q.qsize():
                    q.get_nowait()
