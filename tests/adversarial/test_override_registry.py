"""Adversarial — override registry append-only (R-017 / I-30)."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


def test_override_registry_append_only(tmp_path):
    from override_registry import append_override_record, count_override_records

    db_path = tmp_path / "ov.db"
    rid = append_override_record(
        ticker="SPY",
        route="signals._compute_signals_impl",
        override_source="test",
        override_direction="up",
        override_payload={"direction": "up", "source": "test"},
        db_path=db_path,
    )
    assert rid >= 1
    assert count_override_records(db_path) == 1
    rid2 = append_override_record(
        ticker="SPY",
        route="signals._compute_signals_impl",
        override_source="test2",
        override_direction="down",
        override_payload={"direction": "down"},
        db_path=db_path,
    )
    assert rid2 > rid
    assert count_override_records(db_path) == 2


def test_production_decision_without_release_id_rejected(release_ready):
    from live_decision_bundle import stamp_decision_bundle

    ms = {"ticker": "SPY", "spot": 500.0, "call_signal": "wait", "validation_summary": "ok"}
    out = stamp_decision_bundle(ms, route="server._fetch_state")
    assert out.get("release_id")
    assert out.get("decision_id")


def test_production_decision_without_decision_id_when_quarantined(release_ready):
    from live_decision_bundle import stamp_decision_bundle

    ms = {"ticker": "SPY", "spot": 0.01, "call_signal": "long", "validation_summary": "x"}
    out = stamp_decision_bundle(ms, route="server._fetch_state")
    assert out.get("decision_id") is None
    assert out.get("release_id") is None
