"""Phase 3D — required status checks specification tests."""
from __future__ import annotations

from tools.check_required_status_checks import (
    build_required_status_checks_spec,
    run_required_status_checks_check,
)


def test_required_status_checks_passes_on_current_repo() -> None:
    assert run_required_status_checks_check() == []


def test_required_status_checks_spec_honest_unverified() -> None:
    spec = build_required_status_checks_spec()
    assert spec["workflow_exists"] is True
    assert spec["remote_enforcement_verified"] is False
    assert all(spec["commands_in_workflow"].values())
