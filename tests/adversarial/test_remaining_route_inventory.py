"""Adversarial — remaining route inventory closure (R-011, R-027, R-033, R-034)."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_r011_debug_endpoint_blocked_without_flag(monkeypatch):
    monkeypatch.delenv("ED_ALLOW_DEBUG_ENDPOINTS", raising=False)
    from starlette.testclient import TestClient

    import server as srv

    with TestClient(srv.app) as client:
        r = client.get("/api/debug/prediction?ticker=SPY")
    assert r.status_code == 404


def test_r011_debug_fetch_state_no_production_decision_id(release_ready, monkeypatch):
    """Debug _fetch_state uses classified route — no production decision_id."""
    from trade_impacting_gate import resolve_fetch_state_decision_route

    route = resolve_fetch_state_decision_route("debug_endpoint")
    assert route == "server.api.debug_prediction"

    from live_decision_bundle import stamp_decision_bundle

    ms = {
        "ticker": "SPY",
        "spot": 500.0, "prior_close": 500.0,
        "call_signal": "wait",
        "validation_summary": "debug_ok",
    }
    out = stamp_decision_bundle(ms, route=route)
    assert out.get("decision_id") is None
    assert out.get("trade_impacting_route_class") == "classified_non_production"


@pytest.mark.parametrize("route_id", ["R-027", "R-033", "R-034"])
def test_classified_non_production_routes(route_id: str):
    from trade_impacting_gate import ROUTE_INVENTORY_EVIDENCE

    evidence = ROUTE_INVENTORY_EVIDENCE[route_id]
    assert evidence["enforcement_state"] == "classified_non_production"
    assert evidence.get("trade_impacting") is False


def test_priority_routes_have_evidence_tests():
    from trade_impacting_gate import ROUTE_INVENTORY_EVIDENCE

    for route_id, evidence in ROUTE_INVENTORY_EVIDENCE.items():
        tests = evidence.get("evidence_tests") or []
        assert tests, f"{route_id} missing evidence_tests"
        state = evidence["enforcement_state"]
        assert state in (
            "proven_gated",
            "blocked",
            "classified_non_production",
        ), f"{route_id} still unproven: {state}"
