"""Phase 3D — governance self-protection tests."""
from __future__ import annotations

from tools.check_governance_self_protection import run_governance_self_protection_check


def test_governance_self_protection_passes_on_current_repo() -> None:
    assert run_governance_self_protection_check() == []


def test_self_protection_rejects_proven_without_branch_proof(tmp_path) -> None:
    import json

    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    for rel in (
        "governance/docs/AGENT_OPERATING_CONTRACT.md",
        ".github/workflows/objective-audit.yml",
        "governance/docs/NO_VERIFY_THREAT_MODEL.md",
        ".github/CODEOWNERS",
        "tools/check_branch_protection_proof.py",
        "tools/check_required_status_checks.py",
        "tools/check_governance_critical_files.py",
        "tools/check_no_verify_resistance.py",
        "tools/check_governance_self_protection.py",
        "tools/verify_remote_enforcement.py",
        "tools/remote_enforcement_evidence.py",
        "tools/_build_institutional_audit_phase3d.py",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# stub\n", encoding="utf-8")
    for rel in (
        ".cursor/rules/000-agent-operating-contract.mdc",
        ".cursor/rules/010-definition-of-done.mdc",
        ".cursor/rules/020-governance-maturity.mdc",
        ".cursor/rules/030-repo-neatness.mdc",
        ".cursor/rules/040-testing-and-artifacts.mdc",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\n", encoding="utf-8")
    (tmp_path / "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json").write_text("{}", encoding="utf-8")
    (art / "BRANCH_PROTECTION_PROOF.json").write_text(
        json.dumps(
            {
                "branch_protection": {"required": True, "verified": False},
                "external_enforcement_proven": False,
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "REMOTE_ENFORCEMENT_EVIDENCE.json",
        "REQUIRED_STATUS_CHECKS.json",
        "GOVERNANCE_CRITICAL_FILES.json",
        "NO_VERIFY_RESISTANCE.json",
    ):
        (art / name).write_text("{}", encoding="utf-8")
    (art / "GOVERNANCE_SELF_PROTECTION.json").write_text(
        json.dumps(
            {
                "external_enforcement_proven": True,
                "l5_claim_without_proof_forbidden": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "tools/check_fix_everything_we_touch.py").write_text(
        "check_branch_protection_proof\ncheck_required_status_checks\n"
        "check_governance_critical_files\ncheck_no_verify_resistance\n"
        "check_governance_self_protection\n",
        encoding="utf-8",
    )
    import tools.check_governance_self_protection as mod

    orig = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        errors = mod.run_governance_self_protection_check()
    finally:
        mod.REPO_ROOT = orig
    assert any("external_enforcement_proven true" in e for e in errors)
