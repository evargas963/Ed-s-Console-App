"""Runtime proof — live_path_simulation via server._finalize_production_decision."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_live_path_simulation_emits_reconstructable_record(release_ready, tmp_path, monkeypatch):
    from decision_record import live_path_simulation_emission, reconstruction_complete

    import server as srv

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    result = live_path_simulation_emission(tmp_path / "live_path.db", ticker="IWM")
    assert result["source"] == "live_path_simulation"
    assert result["source"] != "production_like_integration_harness"
    assert result["source"] != "audit_seed"
    assert result["reconstruction_complete"] is True
    assert result["decision_id"]
    assert result["release_id"]
    payload = result["payload"]
    ok, missing = reconstruction_complete(payload)
    assert ok, missing
    assert payload["route"] == "server._fetch_state"


def test_live_path_record_api_retrieval(release_ready, tmp_path, monkeypatch):
    """TEST_SYSTEM_REHAB_V2 final remediation: this was one of three tests hitting
    GET /api/decision/{id}, all asserting the identical HTTP-boundary trio
    (200/ok/reconstruction_complete). That trio's ONE canonical HTTP proof is
    tests/decision_reconstruction/test_immutable_decision_id.py::
    test_api_decision_endpoint. This test's actual distinct value is proving the
    live_path_simulation harness's emitted record is retrievable -- server's
    api_decision_by_id is a thin, un-decorated pass-through to
    decision_record.get_production_decision_by_id + reconstruction_complete
    (server.py:15191-15204), so calling that pair directly proves the identical
    retrieval correctness without re-asserting the HTTP contract a sibling test
    already owns."""
    import server as srv
    from decision_record import (
        get_production_decision_by_id,
        live_path_simulation_emission,
        reconstruction_complete,
    )

    db_path = tmp_path / "live_api.db"
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    emitted = live_path_simulation_emission(db_path, ticker="QQQ")
    decision_id = emitted["decision_id"]
    assert decision_id

    payload = get_production_decision_by_id(decision_id, db_path)
    assert payload is not None
    ok, missing = reconstruction_complete(payload)
    assert ok, missing


def test_live_path_blind_reconstruction(release_ready, tmp_path, monkeypatch):
    from decision_record import (
        ensure_production_decision_schema,
        live_path_simulation_emission,
        reconstruction_complete,
    )

    import server as srv

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    emitted = live_path_simulation_emission(tmp_path / "blind_live.db")
    decision_id = emitted["decision_id"]

    conn = sqlite3.connect(str(tmp_path / "blind_live.db"))
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


def test_source_labels_are_distinct(release_ready, tmp_path, monkeypatch):
    from decision_record import live_path_simulation_emission, production_like_decision_emission

    import server as srv

    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    live = live_path_simulation_emission(tmp_path / "a.db")
    prod_like = production_like_decision_emission(tmp_path / "b.db")
    assert live["source"] == "live_path_simulation"
    assert prod_like["source"] == "production_like_integration_harness"
    assert live["source"] != prod_like["source"]
