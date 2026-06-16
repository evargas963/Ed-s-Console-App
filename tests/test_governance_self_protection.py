"""Phase 3D — governance self-protection tests."""
from __future__ import annotations

from tools.check_governance_self_protection import run_governance_self_protection_check


def test_governance_self_protection_passes_on_current_repo() -> None:
    assert run_governance_self_protection_check() == []
