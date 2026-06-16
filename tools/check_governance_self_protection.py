#!/usr/bin/env python3
"""Governance mutation self-protection — Phase 3D surface integrity."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ARTIFACT = "governance/artifacts/GOVERNANCE_SELF_PROTECTION.json"
MATURITY_REGISTER = "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json"

REQUIRED_SURFACES: tuple[str, ...] = (
    "governance/docs/AGENT_OPERATING_CONTRACT.md",
    ".github/workflows/objective-audit.yml",
    "governance/artifacts/BRANCH_PROTECTION_PROOF.json",
    "governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json",
    "governance/artifacts/REQUIRED_STATUS_CHECKS.json",
    "governance/artifacts/GOVERNANCE_CRITICAL_FILES.json",
    "governance/docs/NO_VERIFY_THREAT_MODEL.md",
    "governance/artifacts/NO_VERIFY_RESISTANCE.json",
    ".github/CODEOWNERS",
    "tools/check_branch_protection_proof.py",
    "tools/check_required_status_checks.py",
    "tools/check_governance_critical_files.py",
    "tools/check_no_verify_resistance.py",
    "tools/check_governance_self_protection.py",
    "tools/verify_remote_enforcement.py",
    "tools/remote_enforcement_evidence.py",
    "tools/_build_institutional_audit_phase3d.py",
)

PRELOAD_RULES: tuple[str, ...] = (
    ".cursor/rules/000-agent-operating-contract.mdc",
    ".cursor/rules/010-definition-of-done.mdc",
    ".cursor/rules/020-governance-maturity.mdc",
    ".cursor/rules/030-repo-neatness.mdc",
    ".cursor/rules/040-testing-and-artifacts.mdc",
)


def build_governance_self_protection() -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.remote_enforcement_evidence import build_self_protection_artifact, load_remote_evidence

    base = build_self_protection_artifact(load_remote_evidence())
    surfaces = base.get("surfaces_present") or {}
    for rel in REQUIRED_SURFACES:
        surfaces[rel] = (REPO_ROOT / rel).is_file()
    base["surfaces_present"] = surfaces
    preload = base.get("preload_rules_present") or {}
    for rel in PRELOAD_RULES:
        preload[rel] = (REPO_ROOT / rel).is_file()
    base["preload_rules_present"] = preload
    return base


def _legacy_build_governance_self_protection() -> dict:
    return {
        "schema_version": 1,
        "artifact": ARTIFACT,
        "surfaces_present": {p: (REPO_ROOT / p).is_file() for p in REQUIRED_SURFACES},
        "preload_rules_present": {p: (REPO_ROOT / p).is_file() for p in PRELOAD_RULES},
        "maturity_truth_source": MATURITY_REGISTER,
        "maturity_truth_source_exists": (REPO_ROOT / MATURITY_REGISTER).is_file(),
        "l5_claim_without_proof_forbidden": True,
        "external_enforcement_required": True,
        "external_enforcement_proven": False,
    }


def run_governance_self_protection_check() -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_SURFACES + PRELOAD_RULES:
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"governance self-protection surface missing: {rel}")
    if not (REPO_ROOT / MATURITY_REGISTER).is_file():
        errors.append(f"{MATURITY_REGISTER}: missing (maturity truth source)")

    artifact_path = REPO_ROOT / ARTIFACT
    if not artifact_path.is_file():
        errors.append(f"{ARTIFACT}: missing — run tools/_build_institutional_audit_phase3d.py")
    else:
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{ARTIFACT}: unreadable ({exc})")
        else:
            if data.get("external_enforcement_proven") is True:
                errors.append(f"{ARTIFACT}: external_enforcement_proven must not be true without proof")
            if data.get("l5_claim_without_proof_forbidden") is not True:
                errors.append(f"{ARTIFACT}: must forbid L5 claims without adversarial + external proof")

    # Phase 3D checkers wired into repo-wide audit
    cfe = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if cfe.is_file():
        text = cfe.read_text(encoding="utf-8")
        for fn in (
            "check_branch_protection_proof",
            "check_required_status_checks",
            "check_governance_critical_files",
            "check_no_verify_resistance",
            "check_governance_self_protection",
        ):
            if fn not in text:
                errors.append(f"check_fix_everything_we_touch.py: missing {fn} in repo-wide audit")
    else:
        errors.append("tools/check_fix_everything_we_touch.py: missing")

    # Scan staged governance artifacts for fabricated L5 claims
    for path in (REPO_ROOT / "governance" / "artifacts").glob("INSTITUTIONAL_AUDIT_*.json"):
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if re.search(r'"effective_maturity"\s*:\s*"L5"', body):
            errors.append(f"{path.relative_to(REPO_ROOT)}: L5 effective_maturity claim in artifact")
        if '"maturity_changes_proposed"' in body:
            chunk = body.split('"maturity_changes_proposed"')[1][:400]
            if re.search(r"L5|L4", chunk) and "[]" not in chunk.split("maturity_changes_rejected")[0]:
                if '"L5"' in chunk or '"L4"' in chunk:
                    errors.append(f"{path.relative_to(REPO_ROOT)}: maturity upgrade proposed without proof")

    return errors


def main() -> int:
    errors = run_governance_self_protection_check()
    if errors:
        for e in errors:
            print(f"check_governance_self_protection: {e}", file=sys.stderr)
        return 1
    print("check_governance_self_protection: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
