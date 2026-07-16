"""Adversarial — production-like decision record proof (NOT audit seed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_production_like_harness_emits_reconstructable_record(release_ready, tmp_path):
    from decision_record import production_like_decision_emission, reconstruction_complete

    result = production_like_decision_emission(tmp_path / "prod_like.db", ticker="SPY")
    assert result["source"] == "production_like_integration_harness"
    assert result["route"] == "server._fetch_state"
    assert result["decision_id"]
    assert result["release_id"]
    assert result["market_validation_summary"]
    assert result["risk_validation_summary"]
    assert result["reconstruction_complete"] is True

    payload = result["payload"]
    ok, missing = reconstruction_complete(payload)
    assert ok, missing
    assert payload["route"] == "server._fetch_state"
    assert payload["market_inputs"]["spot"] == 500.0
    assert payload["risk_state"]["validation_summary"]


def test_production_like_record_retrievable_via_api(release_ready, tmp_path, monkeypatch):
    monkeypatch.setenv("ED_DISABLE_STARTUP_ANALYTICS_WARM", "1")
    from starlette.testclient import TestClient

    import db as db_mod
    import server as srv
    from decision_record import production_like_decision_emission

    db_path = tmp_path / "api_prod_like.db"
    emitted = production_like_decision_emission(db_path, ticker="QQQ")
    decision_id = emitted["decision_id"]
    assert decision_id

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)

    with TestClient(srv.app) as client:
        r = client.get(f"/api/decision/{decision_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reconstruction_complete"] is True
    assert body["decision"]["decision_id"] == decision_id
    assert body["decision"]["release_id"] == emitted["release_id"]


def test_production_like_blind_reconstruction_single_query(release_ready, tmp_path):
    import sqlite3

    from decision_record import (
        ensure_production_decision_schema,
        production_like_decision_emission,
        reconstruction_complete,
    )

    db_path = tmp_path / "blind_prod_like.db"
    emitted = production_like_decision_emission(db_path)
    decision_id = emitted["decision_id"]

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_production_decision_schema(conn)
        row = conn.execute(
            "SELECT reconstruction_json FROM production_decision_records WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row[0])
    ok, missing = reconstruction_complete(payload)
    assert ok, missing


def test_audit_seed_route_is_not_production_like_proof(release_ready, tmp_path):
    """Audit seed uses audit.* prefix — must not satisfy production-like proof."""
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle
    from trade_impacting_gate import classify_route

    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "validation_summary": "audit_seed",
    }
    audit_route = "audit.phase3b_gate_verified"
    assert classify_route(audit_route) == "test_non_production"
    stamp_decision_bundle(ms, route=audit_route)
    did = persist_stamped_decision(ms, route=audit_route, db_path=tmp_path / "audit.db")
    assert did is None
