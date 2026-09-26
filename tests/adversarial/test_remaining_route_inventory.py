"""Adversarial — remaining route inventory closure (R-011, R-027, R-033, R-034)."""
from __future__ import annotations





def test_r011_debug_endpoint_blocked_without_flag(monkeypatch):
    monkeypatch.delenv("ED_ALLOW_DEBUG_ENDPOINTS", raising=False)
    from starlette.testclient import TestClient

    import server as srv

    with TestClient(srv.app) as client:
        r = client.get("/api/debug/prediction?ticker=SPY")
    assert r.status_code == 404






