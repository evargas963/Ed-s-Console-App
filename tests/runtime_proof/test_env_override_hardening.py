"""Runtime proof — ED_* env override inventory and production gate."""
from __future__ import annotations

import pytest

from tools.check_env_override_hardening import (
    ENV_OVERRIDE_INVENTORY,
    build_env_override_inventory_artifact,
    is_production_serving_context,
    run_env_override_hardening_check,
)


def test_env_inventory_has_high_risk_entries():
    art = build_env_override_inventory_artifact()
    assert art["inventory_count"] >= 10
    assert art["high_risk_count"] >= 2
    names = {e["name"] for e in art["entries"]}
    assert "ED_ALLOW_DEBUG_ENDPOINTS" in names
    assert "ED_CONSOLE_ALLOW_PRED_OVERRIDE" in names


def test_production_dangerous_blocked_in_serving_context(monkeypatch):
    monkeypatch.setattr(
        "tools.check_env_override_hardening.is_production_serving_context",
        lambda: True,
    )
    monkeypatch.setenv("ED_ALLOW_DEBUG_ENDPOINTS", "1")
    errors = run_env_override_hardening_check()
    assert any("ED_ALLOW_DEBUG_ENDPOINTS" in e for e in errors)


def test_non_production_mode_allows_check_pass(monkeypatch):
    monkeypatch.setenv("ED_NON_PRODUCTION_MODE", "1")
    monkeypatch.setenv("ED_ALLOW_DEBUG_ENDPOINTS", "1")
    assert is_production_serving_context() is False
    assert run_env_override_hardening_check() == []


def test_classifications_are_valid():
    allowed = {"safe_runtime_config", "test_only", "debug_only", "production_dangerous", "governance_sensitive"}
    for meta in ENV_OVERRIDE_INVENTORY.values():
        assert meta["classification"] in allowed
