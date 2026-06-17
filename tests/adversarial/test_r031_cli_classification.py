"""Adversarial — R-031 verify_model_outputs classified diagnostic_only."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_r031_route_resolution():
    from trade_impacting_gate import classify_route, resolve_fetch_state_decision_route

    route = resolve_fetch_state_decision_route("verify_model_outputs_cli")
    assert route == "cli.verify_model_outputs"
    assert classify_route(route) == "classified_non_production"


def test_r031_cli_path_no_production_decision_id(release_ready, tmp_path):
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle
    from trade_impacting_gate import resolve_fetch_state_decision_route

    route = resolve_fetch_state_decision_route("verify_model_outputs_cli")
    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "validation_summary": "cli_diagnostic",
        "signals_engine_failed": False,
    }
    out = stamp_decision_bundle(ms, route=route)
    assert out.get("decision_id") is None
    assert out.get("decision_gate_blocked") is True
    did = persist_stamped_decision(out, route=route, db_path=tmp_path / "r031.db")
    assert did is None


def test_r031_inventory_classified_non_production():
    from trade_impacting_gate import ROUTE_INVENTORY_EVIDENCE

    r31 = ROUTE_INVENTORY_EVIDENCE["R-031"]
    assert r31["enforcement_state"] == "classified_non_production"
    assert r31.get("route_class") == "diagnostic_only"
    assert r31["trade_impacting"] is False
