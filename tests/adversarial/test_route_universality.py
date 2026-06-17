"""Adversarial — route universality / synthetic bypass (R-005, I-29)."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_synthetic_no_valid_expiry_route_blocked_from_decision_id(release_ready):
    from trade_impacting_gate import apply_trade_impacting_gate

    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "state_error": "no_valid_expiry",
        "validation_summary": "synthetic",
    }
    apply_trade_impacting_gate(ms, route="server._fetch_state.no_valid_expiry")
    assert ms.get("trade_impacting_route_class") == "synthetic_non_production"
    assert ms.get("trade_valid") is False
    quarantine = ms.get("market_data_quarantine") or {}
    assert quarantine.get("active") is True


def test_synthetic_route_does_not_persist_production_record(release_ready, tmp_path):
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle

    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "validation_summary": "ok",
    }
    stamp_decision_bundle(ms, route="server._fetch_state.no_valid_expiry")
    assert ms.get("decision_id") is None
    did = persist_stamped_decision(ms, route="server._fetch_state.no_valid_expiry", db_path=tmp_path / "x.db")
    assert did is None


def test_production_route_requires_validation_summary_for_directional(release_ready):
    from trade_impacting_gate import validate_trade_impacting_gate

    ms = {"ticker": "SPY", "spot": 500.0, "call_signal": "long"}
    result = validate_trade_impacting_gate(ms, route="server._fetch_state")
    assert not result.ok
    assert any("validation_summary" in r for r in result.reasons)
