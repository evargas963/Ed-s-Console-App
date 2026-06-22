"""Phase 3D — branch protection proof checker tests."""
from __future__ import annotations

import json
from pathlib import Path

from tools.check_branch_protection_proof import (
    run_branch_protection_proof_check,
)


def test_branch_protection_proof_passes_on_current_repo() -> None:
    assert run_branch_protection_proof_check() == []


def test_branch_protection_proof_honest_unverified() -> None:
    from tools.remote_enforcement_evidence import build_branch_protection_artifact, empty_remote_evidence

    proof = build_branch_protection_artifact(empty_remote_evidence())
    assert proof["branch_protection"]["verified"] is False
    assert proof["external_enforcement_proven"] is False
    assert "GitHub API" in proof["branch_protection"]["reason"] or "without GitHub API" in proof["branch_protection"]["reason"]


def test_branch_protection_proof_fails_if_verified_without_api(tmp_path: Path) -> None:
    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    (tmp_path / "governance" / "docs").mkdir(parents=True)
    (tmp_path / "governance" / "docs" / "BRANCH_PROTECTION_REQUIRED.md").write_text("# doc", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "verify_remote_enforcement.py").write_text("# stub", encoding="utf-8")
    (art / "BRANCH_PROTECTION_PROOF.json").write_text(
        json.dumps(
            {
                "branch_protection": {
                    "required": True,
                    "verified": True,
                    "reason": "Verified via remote evidence.",
                },
                "remote_evidence": {"verification_method": "github_cli"},
                "external_enforcement_proven": False,
            }
        ),
        encoding="utf-8",
    )
    (art / "REMOTE_ENFORCEMENT_EVIDENCE.json").write_text(
        json.dumps({"verification_method": "github_cli", "branch_protection_verified": True}),
        encoding="utf-8",
    )
    import tools.check_branch_protection_proof as mod

    orig = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        errors = mod.run_branch_protection_proof_check()
    finally:
        mod.REPO_ROOT = orig
    assert any("without github_api_evidence" in e for e in errors)
