"""I-31 — immutable decision_id persistence and blind reconstruction."""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


_PRODUCTION_ROUTE = "server._fetch_state"


def test_decision_id_is_uuid_hex_and_unique(release_ready):
    from decision_record import new_decision_id
    from live_decision_bundle import stamp_decision_bundle

    base = {"ticker": "SPY", "spot": 500.0, "call_signal": "wait", "validation_summary": "ok"}
    a = stamp_decision_bundle(dict(base), route=_PRODUCTION_ROUTE)["decision_id"]
    b = stamp_decision_bundle(dict(base), route=_PRODUCTION_ROUTE)["decision_id"]
    assert a and b and a != b
    uuid.UUID(hex=a)
    uuid.UUID(hex=b)


def test_missing_release_blocks_decision_emission(monkeypatch):
    monkeypatch.delenv("ED_BUILD_GENERATION", raising=False)
    from release_object import _cached_release
    import release_object as ro

    ro._cached_release = None
    monkeypatch.setattr(ro, "_git_head_sha", lambda: None)

    from live_decision_bundle import stamp_decision_bundle

    ms = stamp_decision_bundle(
        {"ticker": "SPY", "spot": 500.0, "call_signal": "wait", "validation_summary": "ok"},
        route="server._fetch_state",
    )
    assert ms.get("decision_generation_skipped") is True
    assert ms.get("decision_id") is None
    assert ms.get("release_id") is None


def test_persist_and_retrieve_reconstruction(tmp_path, release_ready):
    from decision_record import get_production_decision_by_id, reconstruction_complete
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle

    db_path = tmp_path / "decisions.db"
    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "call_conviction": "low",
        "dominant_dir": "flat",
        "mhap_rows": [{"horizon": "1c", "signal": "wait"}],
        "fusion_by_horizon": {"1c": {"p_up": 0.3}},
        "validation_summary": "ok",
        "pred_override": None,
    }
    stamp_decision_bundle(ms, route=_PRODUCTION_ROUTE)
    did = persist_stamped_decision(ms, route=_PRODUCTION_ROUTE, db_path=db_path)
    assert did == ms["decision_id"]

    payload = get_production_decision_by_id(did, db_path)
    assert payload is not None
    assert payload["decision_id"] == did
    assert payload["release_id"] == ms["release_id"]
    ok, missing = reconstruction_complete(payload)
    assert ok, missing


def test_blind_reconstruction_single_query(tmp_path, release_ready):
    """Auditor receives only decision_id — one SELECT must reconstruct."""
    from decision_record import ensure_production_decision_schema, reconstruction_complete
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle

    db_path = tmp_path / "blind.db"
    ms = {
        "ticker": "QQQ",
        "spot": 400.0,
        "call_signal": "long",
        "call_conviction": "high",
        "dominant_dir": "up",
        "mhap_rows": [{"horizon": "5c"}],
        "fusion_by_horizon": {"5c": {}},
        "validation_summary": "risk_ok",
    }
    stamp_decision_bundle(ms, route="server._fetch_state")
    decision_id = persist_stamped_decision(ms, route="server._fetch_state", db_path=db_path)
    assert decision_id

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
    assert payload["ticker"] == "QQQ"


def test_api_decision_endpoint(tmp_path, release_ready, monkeypatch):
    monkeypatch.setenv("ED_DISABLE_STARTUP_ANALYTICS_WARM", "1")
    from starlette.testclient import TestClient

    import db as db_mod
    import server as srv

    db_path = tmp_path / "api.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)

    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle

    ms = {
        "ticker": "SPY",
        "spot": 510.0,
        "call_signal": "wait",
        "mhap_rows": [],
        "fusion_by_horizon": {},
        "validation_summary": "x",
    }
    stamp_decision_bundle(ms, route=_PRODUCTION_ROUTE)
    persist_stamped_decision(ms, route=_PRODUCTION_ROUTE, db_path=db_path)

    with TestClient(srv.app) as client:
        r = client.get(f"/api/decision/{ms['decision_id']}")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["reconstruction_complete"] is True
        assert body["decision"]["decision_id"] == ms["decision_id"]
