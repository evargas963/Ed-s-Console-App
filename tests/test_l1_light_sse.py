"""
L1 light SSE — event-driven delivery; no duplicate _project_l1; generation in envelope.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_l1_sse_diagnostics_exposed():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/diagnostics/l1")
    assert r.status_code == 200
    ed = r.json()["ed_l1"]
    assert "l1_sse_light" in ed
    assert "l1_light_sse_connections" in ed["l1_sse_light"]


def test_notify_noop_without_subscribers():
    import server as srv

    srv._l1_light_sse_clients.clear()
    n = srv._l1_sse_thread_queue.qsize()
    srv._l1_notify_sse_after_authoritative_build("SPY", None)
    assert srv._l1_sse_thread_queue.qsize() == n


def test_notify_enqueues_when_subscribed(monkeypatch):
    import server as srv

    q = asyncio.Queue(maxsize=10)
    key = ("SPY", "__auto__")
    srv._l1_light_sse_clients.append((q, key))
    try:
        monkeypatch.setattr(
            srv,
            "_l1_http_get_projection",
            lambda t, e, force=False: {"l1_generation": 42, "_server_build_ts": 1700000000.0, "ok": True},
        )
        n0 = srv._l1_sse_thread_queue.qsize()
        srv._l1_notify_sse_after_authoritative_build("SPY", None)
        assert srv._l1_sse_thread_queue.qsize() == n0 + 1
        sk, env = srv._l1_sse_thread_queue.get_nowait()
        assert sk == key
        assert env["l1_generation"] == 42
        assert env["l1_sse_schema"] == 1
        assert env["payload"]["ok"] is True
        assert "l1_payload_fingerprint" in env
        assert len(env["l1_payload_fingerprint"]) == 32
    finally:
        srv._l1_light_sse_clients.clear()
        while not srv._l1_sse_thread_queue.empty():
            try:
                srv._l1_sse_thread_queue.get_nowait()
            except Exception:
                break


def test_notify_throttled_within_window(monkeypatch):
    import server as srv

    q = asyncio.Queue(maxsize=10)
    key = ("ZZZ", "__auto__")
    srv._l1_light_sse_clients.append((q, key))
    th0 = int(srv._l1_sse_diag.get("l1_light_sse_events_throttled", 0))
    try:
        monkeypatch.setattr(
            srv,
            "_l1_http_get_projection",
            lambda t, e, force=False: {"l1_generation": 1},
        )
        monkeypatch.setattr(srv, "_L1_SSE_MIN_INTERVAL_SEC", 60.0)
        srv._l1_notify_sse_after_authoritative_build("ZZZ", None)
        srv._l1_notify_sse_after_authoritative_build("ZZZ", None)
        assert int(srv._l1_sse_diag.get("l1_light_sse_events_throttled", 0)) >= th0 + 1
    finally:
        srv._l1_light_sse_clients.clear()
        srv._l1_sse_last_emit_mono.pop(key, None)
        while not srv._l1_sse_thread_queue.empty():
            try:
                srv._l1_sse_thread_queue.get_nowait()
            except Exception:
                break


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
