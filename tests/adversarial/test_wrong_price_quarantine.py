"""Adversarial — wrong-price quarantine (I-28)."""
from __future__ import annotations

import pytest


@pytest.fixture
def release_ready(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)


@pytest.mark.parametrize("spot", [0.01, 50000.0, None, float("nan"), -1.0])
def test_wrong_spot_quarantines_production_decision(release_ready, spot):
    from live_decision_bundle import stamp_decision_bundle

    ms = {
        "ticker": "SPY",
        "spot": spot,
        "call_signal": "long",
        "call_conviction": "high",
        "validation_summary": "should_not_stand",
    }
    out = stamp_decision_bundle(ms, route="server._fetch_state")
    assert out.get("decision_id") is None
    assert out.get("decision_generation_skipped") is True
    assert out.get("decision_gate_blocked") is True
    quarantine = out.get("market_data_quarantine") or {}
    assert quarantine.get("active") is True
    assert out.get("call_signal") == "wait"
    assert out.get("trade_valid") is False


def test_qqq_wrong_spot_quarantines(release_ready):
    from live_decision_bundle import stamp_decision_bundle

    ms = {"ticker": "QQQ", "spot": 0.01, "call_signal": "short", "validation_summary": "x"}
    out = stamp_decision_bundle(ms, route="server._fetch_state")
    assert out.get("decision_id") is None
    assert (out.get("market_data_quarantine") or {}).get("active") is True


def test_valid_spot_allows_decision_id(release_ready):
    from live_decision_bundle import stamp_decision_bundle

    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "validation_summary": "ok",
    }
    out = stamp_decision_bundle(ms, route="server._fetch_state")
    assert out.get("decision_id")
    assert not out.get("decision_gate_blocked")
