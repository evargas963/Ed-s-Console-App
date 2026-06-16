"""Tests for check-only generated governance artifact verification."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_governance_generated_artifacts_clean import (  # noqa: E402
    check_governance_generated_artifacts_clean,
    regeneration_commands,
)


def test_generated_artifacts_clean_on_current_repo(monkeypatch):
    import tools.check_governance_generated_artifacts_clean as mod

    monkeypatch.setattr(mod, "_persistence_needs_check", lambda: False)
    monkeypatch.setattr(mod, "_check_stack_needs_check", lambda: False)
    monkeypatch.setattr(mod, "_precommit_audit_needs_check", lambda: False)
    errs = mod.check_governance_generated_artifacts_clean()
    assert errs == [], errs


def test_regeneration_commands_are_explicit_and_separate():
    cmds = regeneration_commands()
    assert "python tools/audit_persistence_consumers.py" in cmds
    assert "python tools/build_check_stack_inventory.py" in cmds
    assert all("--write" not in c or "audit_precommit" in c for c in cmds)


def test_check_is_non_mutating(monkeypatch):
    """Verification must not change artifact mtimes."""
    import tools.check_governance_generated_artifacts_clean as mod

    monkeypatch.setattr(mod, "_persistence_needs_check", lambda: False)
    monkeypatch.setattr(mod, "_check_stack_needs_check", lambda: False)
    monkeypatch.setattr(mod, "_precommit_audit_needs_check", lambda: False)
    targets = [
        REPO / "governance/artifacts/persistence_consumer_map.json",
        REPO / "governance/artifacts/CHECK_STACK_INVENTORY.json",
    ]
    before = {p: p.stat().st_mtime_ns for p in targets if p.is_file()}
    errs = mod.check_governance_generated_artifacts_clean()
    assert errs == [], errs
    for p, mtime in before.items():
        assert p.stat().st_mtime_ns == mtime


def test_stale_persistence_map_fails_before_long_tests(monkeypatch):
    import tools.check_governance_generated_artifacts_clean as mod

    def _stale(*, force_deep=False):
        return ["persistence map stale — run regen"]

    monkeypatch.setitem(mod._CHECK_DISPATCH, "persistence_consumer_map", _stale)
    errs = mod.check_governance_generated_artifacts_clean()
    assert any("persistence" in e.lower() for e in errs)


def test_stale_check_stack_inventory_detected(monkeypatch):
    import tools.check_governance_generated_artifacts_clean as mod

    def _stale(*, force_deep=False):
        return [
            "governance/artifacts/CHECK_STACK_INVENTORY.json is stale — "
            "run: python tools/build_check_stack_inventory.py"
        ]

    monkeypatch.setitem(mod._CHECK_DISPATCH, "check_stack_inventory", _stale)
    monkeypatch.setattr(mod, "_persistence_needs_check", lambda: False)
    monkeypatch.setattr(mod, "_precommit_audit_needs_check", lambda: False)
    errs = mod.check_governance_generated_artifacts_clean(force_deep=False)
    assert any("CHECK_STACK_INVENTORY" in e for e in errs)


def test_deep_hygiene_only_when_forced(monkeypatch):
    import tools.check_governance_generated_artifacts_clean as mod

    calls: list[str] = []

    def _spy_inv(*, force_deep=False):
        calls.append("inv")
        return []

    def _spy_back(*, force_deep=False):
        calls.append("back")
        return []

    def _noop(*, force_deep=False):
        return []

    monkeypatch.setitem(mod._CHECK_DISPATCH, "repo_hygiene_inventory", _spy_inv)
    monkeypatch.setitem(mod._CHECK_DISPATCH, "repo_hygiene_backlog", _spy_back)
    monkeypatch.setitem(mod._CHECK_DISPATCH, "persistence_consumer_map", _noop)
    monkeypatch.setitem(mod._CHECK_DISPATCH, "check_stack_inventory", _noop)
    monkeypatch.setitem(mod._CHECK_DISPATCH, "precommit_performance_audit", _noop)
    mod.check_governance_generated_artifacts_clean(force_deep=False)
    assert calls == []
    mod.check_governance_generated_artifacts_clean(force_deep=True)
    assert calls == ["inv", "back"]


def test_mtime_gate_skips_persistence_when_sources_unchanged(monkeypatch):
    import tools.check_governance_generated_artifacts_clean as mod

    calls: list[bool] = []

    def _spy(*, force_deep=False):
        calls.append(force_deep)
        return []

    monkeypatch.setitem(mod._CHECK_DISPATCH, "persistence_consumer_map", _spy)
    mod.check_governance_generated_artifacts_clean()
    assert calls == [False]


def test_checker_source_is_non_mutating():
    src = (REPO / "tools/check_governance_generated_artifacts_clean.py").read_text(encoding="utf-8")
    assert ".write_text(" not in src
    assert "write_bytes(" not in src
