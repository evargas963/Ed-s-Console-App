#!/usr/bin/env python3
"""Verify CI workflow defines required objective-audit and governance test commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC = "governance/docs/REQUIRED_STATUS_CHECKS.md"
ARTIFACT = "governance/artifacts/REQUIRED_STATUS_CHECKS.json"
WORKFLOW = ".github/workflows/objective-audit.yml"

REQUIRED_COMMANDS: tuple[str, ...] = (
    "python tools/enforce_all_rules.py --objective-audit",
    "python -m pytest tests/adversarial/",
    "python -m pytest tests/decision_reconstruction/",
    "python -m pytest tests/release_object/",
    "python -m pytest tests/test_governance_consolidation.py",
    "python -m pytest tests/test_agent_preload_contract.py",
    "python tools/check_agent_preload_contract.py",
)

REQUIRED_CHECKER_TESTS: tuple[str, ...] = (
    "tests/test_branch_protection_proof.py",
    "tests/test_required_status_checks.py",
    "tests/test_governance_critical_files.py",
    "tests/test_no_verify_resistance.py",
    "tests/test_governance_self_protection.py",
    "tests/test_remote_enforcement_evidence.py",
)

# GitHub required status check name — must match jobs.<id>.name in objective-audit.yml
REQUIRED_GITHUB_CHECK_NAME = "objective-audit"


def _workflow_spec_base() -> dict:
    workflow_text = ""
    wf = REPO_ROOT / WORKFLOW
    if wf.is_file():
        workflow_text = wf.read_text(encoding="utf-8")
    commands_present = {
        cmd: cmd.split()[-1] in workflow_text or cmd in workflow_text for cmd in REQUIRED_COMMANDS
    }
    return {
        "artifact": ARTIFACT,
        "workflow_file": WORKFLOW,
        "workflow_exists": wf.is_file(),
        "required_commands": list(REQUIRED_COMMANDS),
        "commands_in_workflow": commands_present,
        "reason": (
            "Workflow file proves CI specification; GitHub required-check enforcement is not proven locally."
        ),
    }


def build_required_status_checks_spec() -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.remote_enforcement_evidence import build_required_status_checks_artifact, load_remote_evidence

    return build_required_status_checks_artifact(load_remote_evidence())


def run_required_status_checks_check() -> list[str]:
    errors: list[str] = []
    if not (REPO_ROOT / DOC).is_file():
        errors.append(f"{DOC}: missing")
    wf = REPO_ROOT / WORKFLOW
    if not wf.is_file():
        errors.append(f"{WORKFLOW}: missing")
        return errors
    text = wf.read_text(encoding="utf-8")
    required_fragments = (
        "--objective-audit",
        "tests/adversarial/",
        "tests/decision_reconstruction/",
        "tests/release_object/",
        "test_governance_consolidation.py",
        "test_agent_preload_contract.py",
        "check_agent_preload_contract.py",
        "test_remote_enforcement_evidence.py",
    )
    for frag in required_fragments:
        if frag not in text:
            errors.append(f"{WORKFLOW}: missing required fragment {frag!r}")
    if f"name: {REQUIRED_GITHUB_CHECK_NAME}" not in text:
        errors.append(
            f"{WORKFLOW}: job name must be {REQUIRED_GITHUB_CHECK_NAME!r} "
            f"(GitHub required status check name — do not rename casually)"
        )
    if "jobs:\n  objective-audit:" not in text and "  objective-audit:" not in text:
        errors.append(f"{WORKFLOW}: missing job id objective-audit")
    artifact_path = REPO_ROOT / ARTIFACT
    if not artifact_path.is_file():
        errors.append(f"{ARTIFACT}: missing — run tools/_build_institutional_audit_phase3d.py")
    else:
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{ARTIFACT}: unreadable ({exc})")
        else:
            enforced = (data.get("required_checks") or {}).get("enforced") is True
            if enforced and not data.get("remote_enforcement_verified"):
                errors.append(f"{ARTIFACT}: required_checks.enforced true without remote_enforcement_verified")
            if data.get("remote_enforcement_verified") is True:
                remote = data.get("remote_evidence") or {}
                if remote.get("verification_method") not in ("github_api", "github_cli", "exported_ruleset"):
                    errors.append(f"{ARTIFACT}: remote_enforcement_verified without API-class method")
    for test_path in REQUIRED_CHECKER_TESTS:
        if not (REPO_ROOT / test_path).is_file():
            errors.append(f"{test_path}: missing (Phase 3D checker test)")
    return errors


def main() -> int:
    errors = run_required_status_checks_check()
    if errors:
        for e in errors:
            print(f"check_required_status_checks: {e}", file=sys.stderr)
        return 1
    print("check_required_status_checks: PASS (CI spec present; remote enforcement unverified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
