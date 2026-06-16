#!/usr/bin/env python3
"""Branch protection proof model — honest verified vs unverified states."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC = "governance/docs/BRANCH_PROTECTION_REQUIRED.md"
ARTIFACT = "governance/artifacts/BRANCH_PROTECTION_PROOF.json"
API_VERIFIED_METHODS = frozenset({"github_api", "github_cli", "exported_ruleset"})


def build_branch_protection_proof() -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.remote_enforcement_evidence import build_branch_protection_artifact, load_remote_evidence

    return build_branch_protection_artifact(load_remote_evidence())


def run_branch_protection_proof_check() -> list[str]:
    errors: list[str] = []
    if not (REPO_ROOT / DOC).is_file():
        errors.append(f"{DOC}: missing")
    if not (REPO_ROOT / "tools/verify_remote_enforcement.py").is_file():
        errors.append("tools/verify_remote_enforcement.py: missing (Phase 3D-Verification)")
    artifact_path = REPO_ROOT / ARTIFACT
    if not artifact_path.is_file():
        errors.append(f"{ARTIFACT}: missing — run tools/_build_institutional_audit_phase3d.py")
        return errors
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{ARTIFACT}: unreadable ({exc})"]

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.remote_enforcement_evidence import load_remote_evidence, validate_verified_claims

    bp = data.get("branch_protection") or {}
    if bp.get("required") is not True:
        errors.append(f"{ARTIFACT}: branch_protection.required must be true")

    verified = bp.get("verified") is True
    remote = data.get("remote_evidence") or {}
    method = remote.get("verification_method")

    if verified:
        if method not in API_VERIFIED_METHODS:
            errors.append(f"{ARTIFACT}: verified=true but verification_method={method!r} not API-class")
        if not data.get("github_api_evidence"):
            errors.append(f"{ARTIFACT}: verified=true without github_api_evidence payload")
        errors.extend(validate_verified_claims(load_remote_evidence(), ARTIFACT))
    else:
        if method in API_VERIFIED_METHODS and load_remote_evidence().get("branch_protection_verified"):
            errors.append(f"{ARTIFACT}: remote evidence says verified but artifact verified=false")

    if data.get("external_enforcement_proven") is True and not verified:
        errors.append(f"{ARTIFACT}: external_enforcement_proven true while branch_protection.verified false")

    if method == "operator_manual_attestation" and verified:
        errors.append(f"{ARTIFACT}: manual attestation cannot set verified=true")

    return errors


def main() -> int:
    errors = run_branch_protection_proof_check()
    if errors:
        for e in errors:
            print(f"check_branch_protection_proof: {e}", file=sys.stderr)
        return 1
    ev = build_branch_protection_proof()
    verified = ev["branch_protection"]["verified"]
    print(f"check_branch_protection_proof: PASS (verified={verified})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
