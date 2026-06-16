"""Phase 3D — governance-critical files protection tests."""
from __future__ import annotations

from tools.check_governance_critical_files import run_governance_critical_files_check


def test_governance_critical_files_passes_on_current_repo() -> None:
    assert run_governance_critical_files_check() == []
