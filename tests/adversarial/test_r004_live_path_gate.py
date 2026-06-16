"""Adversarial — R-004 dedicated gate proof (server._fetch_state production route)."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_r004_wrong_price_quarantines_no_decision_id(release_ready, tmp_path, monkeypatch):
    import server as srv
    from decision_record import get_production_decision_by_id

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    import db as db_mod

    db_path = tmp_path / "r004_bad.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    ms = {
        "ticker": "SPY",
        "spot": 0.01,
        "call_signal": "long",
        "validation_summary": "should_quarantine",
        "signals_engine_failed": False,
    }
    out = srv._finalize_production_decision(ms, "server._fetch_state")
    assert out.get("decision_id") is None
    assert out.get("decision_gate_blocked") is True
    assert (out.get("market_data_quarantine") or {}).get("active") is True
    assert get_production_decision_by_id("fake", db_path) is None


def test_r004_missing_validation_blocks_directional(release_ready, tmp_path, monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    import db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "r004_noval.db")
    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "long",
        "signals_engine_failed": False,
    }
    out = srv._finalize_production_decision(ms, "server._fetch_state")
    assert out.get("decision_id") is None
    assert out.get("decision_gate_blocked") is True


def test_r004_valid_path_emits_release_and_decision_id(release_ready, tmp_path, monkeypatch):
    from decision_record import live_path_simulation_emission, reconstruction_complete

    import server as srv

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    result = live_path_simulation_emission(tmp_path / "r004_ok.db", ticker="SPY")
    assert result["source"] == "live_path_simulation"
    assert result["route"] == "server._fetch_state"
    assert result["decision_id"]
    assert result["release_id"]
    assert result["market_validation_summary"]
    assert result["risk_validation_summary"]
    ok, missing = reconstruction_complete(result["payload"])
    assert ok, missing


def test_r004_inventory_marked_proven_gated():
    from trade_impacting_gate import ROUTE_INVENTORY_EVIDENCE

    r4 = ROUTE_INVENTORY_EVIDENCE["R-004"]
    assert r4["enforcement_state"] == "proven_gated"
    assert "test_r004_live_path_gate.py" in str(r4["evidence_tests"])
