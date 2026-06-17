#!/usr/bin/env python3
"""No-verify threat model — local pre-commit bypass vs CI mitigation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC = "governance/docs/NO_VERIFY_THREAT_MODEL.md"
ARTIFACT = "governance/artifacts/NO_VERIFY_RESISTANCE.json"


def build_no_verify_resistance() -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.remote_enforcement_evidence import build_no_verify_artifact, load_remote_evidence

    return build_no_verify_artifact(load_remote_evidence())


def run_no_verify_resistance_check() -> list[str]:
    errors: list[str] = []
    if not (REPO_ROOT / DOC).is_file():
        errors.append(f"{DOC}: missing")
    artifact_path = REPO_ROOT / ARTIFACT
    if not artifact_path.is_file():
        errors.append(f"{ARTIFACT}: missing — run tools/_build_institutional_audit_phase3d.py")
        return errors
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{ARTIFACT}: unreadable ({exc})"]

    if data.get("local_pre_commit_bypassable") is not True:
        errors.append(f"{ARTIFACT}: must state local_pre_commit_bypassable=true")

    status = data.get("no_verify_status")
    if status == "mitigated":
        if not data.get("branch_protection_verified"):
            errors.append(f"{ARTIFACT}: no_verify_status=mitigated without branch_protection_verified")
        remote = data.get("remote_evidence") or {}
        if remote.get("verification_method") not in ("github_api", "github_cli", "exported_ruleset"):
            errors.append(f"{ARTIFACT}: mitigated requires API-class verification_method")
    elif status == "closed":
        errors.append(f"{ARTIFACT}: use no_verify_status=mitigated (not closed) for API-verified state")
    elif status not in ("open",):
        errors.append(f"{ARTIFACT}: no_verify_status must be open or mitigated with evidence")

    if status == "open" and data.get("no_verify_closed") is True:
        errors.append(f"{ARTIFACT}: contradictory no_verify_closed flag")

    return errors


def main() -> int:
    errors = run_no_verify_resistance_check()
    if errors:
        for e in errors:
            print(f"check_no_verify_resistance: {e}", file=sys.stderr)
        return 1
    print(f"check_no_verify_resistance: PASS (status={build_no_verify_resistance().get('no_verify_status')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
