"""Phase 3D — no-verify resistance model tests."""
from __future__ import annotations

from tools.check_no_verify_resistance import (
    build_no_verify_resistance,
    run_no_verify_resistance_check,
)


def test_no_verify_resistance_passes_on_current_repo() -> None:
    assert run_no_verify_resistance_check() == []


def test_no_verify_status_open_until_external_proof() -> None:
    from tools.remote_enforcement_evidence import build_no_verify_artifact, empty_remote_evidence

    model = build_no_verify_artifact(empty_remote_evidence())
    assert model["local_pre_commit_bypassable"] is True
    assert model["no_verify_status"] == "open"
