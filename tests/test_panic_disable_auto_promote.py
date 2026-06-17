"""Panic env ED_DISABLE_AUTO_PROMOTE overrides enable (PR4 P3-1)."""
from __future__ import annotations


import pytest


@pytest.fixture
def auto_promote_env(monkeypatch):
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE", raising=False)
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)


def test_panic_disables_auto_promote(auto_promote_env, monkeypatch):
    monkeypatch.setenv("ED_DISABLE_AUTO_PROMOTE", "1")
    from arch_competition.scheduler_auto_promote_policy import scheduler_auto_promote_to_active_enabled

    assert scheduler_auto_promote_to_active_enabled() is False


def test_enable_without_panic(auto_promote_env):
    from arch_competition.scheduler_auto_promote_policy import scheduler_auto_promote_to_active_enabled

    assert scheduler_auto_promote_to_active_enabled() is True
