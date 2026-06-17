#!/usr/bin/env python3
"""Phase 3D-Verification — fetch or apply remote GitHub enforcement evidence.

Usage:
  python tools/verify_remote_enforcement.py --fetch-github
  python tools/verify_remote_enforcement.py --fetch-github --run-id 27662986304
  python tools/verify_remote_enforcement.py --configure-main-protection
  python tools/verify_remote_enforcement.py --attestation governance/artifacts/REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.json
  python tools/verify_remote_enforcement.py --write-pending
  python tools/verify_remote_enforcement.py --status

Does NOT set verified=true without github_api | github_cli | exported_ruleset evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.remote_enforcement_evidence import (  # noqa: E402
    ATTESTATION_TEMPLATE,
    DEFAULT_OBJECTIVE_AUDIT_RUN_ID,
    EVIDENCE_PATH,
    apply_manual_attestation,
    build_phase3d_evidence_artifact,
    empty_remote_evidence,
    fetch_github_evidence,
    load_remote_evidence,
    save_remote_evidence,
    write_all_artifacts,
)


def _write_attestation_template() -> None:
    template = {
        "schema_version": 1,
        "artifact": "governance/artifacts/REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.template.json",
        "verification_method": "operator_manual_attestation",
        "evidence_source": "operator_manual_attestation",
        "evidence_timestamp": "2026-06-15T00:00:00+00:00",
        "repository": "OWNER/REPO",
        "protected_branch": "main",
        "required_status_checks": ["objective-audit"],
        "required_reviews": 1,
        "pr_review_required": True,
        "allows_force_pushes": False,
        "allows_deletions": False,
        "bypass_actors": [],
        "verified_by": "operator@example.com",
        "attestation_note": "Manual attestation is NOT API verification. verified remains false until gh api proof.",
    }
    ATTESTATION_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    ATTESTATION_TEMPLATE.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


def _write_phase3d(evidence: dict) -> None:
    phase3d = build_phase3d_evidence_artifact(evidence)
    phase3d["generated"] = date.today().isoformat()
    (REPO / "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3D_EVIDENCE.json").write_text(
        json.dumps(phase3d, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 3D-Verification remote enforcement proof")
    p.add_argument("--fetch-github", action="store_true", help="Fetch via GitHub CLI or REST API (token)")
    p.add_argument(
        "--run-id",
        type=int,
        default=DEFAULT_OBJECTIVE_AUDIT_RUN_ID,
        help="Attach public Actions run inspection (check name discovery)",
    )
    p.add_argument(
        "--configure-main-protection",
        action="store_true",
        help="Set main branch protection requiring objective-audit (GITHUB_TOKEN admin)",
    )
    p.add_argument("--attestation", type=str, help="Apply operator manual attestation JSON")
    p.add_argument("--write-pending", action="store_true", help="Write pending unverified evidence")
    p.add_argument("--write-template", action="store_true", help="Write manual attestation template")
    p.add_argument("--status", action="store_true", help="Print current evidence status")
    args = p.parse_args(argv)

    if args.write_template:
        _write_attestation_template()
        print(f"wrote {ATTESTATION_TEMPLATE.relative_to(REPO)}")
        return 0

    if args.write_pending:
        evidence = empty_remote_evidence()
        write_all_artifacts(evidence, generated=date.today().isoformat())
        _write_phase3d(evidence)
        print("wrote pending remote enforcement evidence (verified=false)")
        return 0

    if args.configure_main_protection:
        from tools import set_branch_protection

        rc = set_branch_protection.main(["--checks", "objective-audit"])
        if rc != 0:
            print(
                "configure-main-protection failed — set GITHUB_TOKEN (repo admin) and retry, "
                "or configure in GitHub UI (see governance/docs/BRANCH_PROTECTION_REQUIRED.md)",
                file=sys.stderr,
            )
            return rc
        evidence = fetch_github_evidence(run_id=args.run_id)
        write_all_artifacts(evidence, generated=date.today().isoformat())
        _write_phase3d(evidence)
        print(
            f"configure-main-protection: verified={evidence.get('branch_protection_verified')} "
            f"checks_enforced={evidence.get('required_checks_enforced')}"
        )
        return 0

    if args.fetch_github:
        evidence = fetch_github_evidence(run_id=args.run_id)
        if evidence.get("verification_method") == "pending":
            print(
                "GitHub branch protection not API-verified — "
                f"operator_action_required={evidence.get('operator_action_required')}",
                file=sys.stderr,
            )
        write_all_artifacts(evidence, generated=date.today().isoformat())
        _write_phase3d(evidence)
        print(
            f"fetch-github: verified={evidence.get('branch_protection_verified')} "
            f"checks_enforced={evidence.get('required_checks_enforced')} "
            f"check_name={evidence.get('objective_audit_check_name')!r} "
            f"operator_action_required={evidence.get('operator_action_required')}"
        )
        return 0

    if args.attestation:
        path = REPO / args.attestation
        if not path.is_file():
            print(f"missing attestation file: {path}", file=sys.stderr)
            return 1
        att = json.loads(path.read_text(encoding="utf-8"))
        evidence = apply_manual_attestation(att)
        write_all_artifacts(evidence, generated=date.today().isoformat())
        _write_phase3d(evidence)
        print("applied manual attestation — verified=false (not API verification)")
        return 0

    if args.status:
        ev = load_remote_evidence()
        print(json.dumps(ev, indent=2))
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
