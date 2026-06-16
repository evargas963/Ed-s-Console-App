"""Phase 3D-Verification — remote enforcement evidence integrity tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.remote_enforcement_evidence import (
    API_VERIFIED_METHODS,
    _parse_rulesets_enforcement,
    apply_manual_attestation,
    derive_statuses,
    empty_remote_evidence,
    fetch_github_cli_evidence,
    validate_verified_claims,
)


def test_pending_evidence_is_unverified() -> None:
    ev = empty_remote_evidence()
    statuses = derive_statuses(ev)
    assert statuses["branch_protection_verified"] is False
    assert statuses["required_checks_enforced"] is False
    assert statuses["no_verify_status"] == "open"
    assert statuses["external_enforcement_status"] == "required_not_proven"


def test_manual_attestation_does_not_verify() -> None:
    att = {
        "repository": "owner/repo",
        "required_status_checks": ["objective-audit"],
        "required_reviews": 1,
        "pr_review_required": True,
        "verified_by": "operator@example.com",
    }
    ev = apply_manual_attestation(att)
    statuses = derive_statuses(ev)
    assert ev["operator_attestation"] is True
    assert ev["branch_protection_verified"] is False
    assert statuses["external_enforcement_status"] == "attested_not_api_verified"
    assert statuses["no_verify_status"] == "open"
    assert validate_verified_claims(ev, "test") == []


def test_api_verified_requires_evidence_fields() -> None:
    ev = empty_remote_evidence()
    ev.update(
        {
            "verification_method": "github_cli",
            "branch_protection_verified": True,
            "required_checks_enforced": True,
            "objective_audit_required": True,
            "github_api_evidence": {"branch_protection": {}},
        }
    )
    errors = validate_verified_claims(ev, "test")
    assert errors, "verified without full evidence fields must fail"


def test_api_verified_complete_evidence_passes_validation() -> None:
    ev = empty_remote_evidence()
    ev.update(
        {
            "verification_method": "github_cli",
            "evidence_source": "gh api",
            "evidence_timestamp": "2026-06-15T12:00:00+00:00",
            "repository": "owner/repo",
            "protected_branch": "main",
            "required_status_checks": ["objective-audit"],
            "required_reviews": 1,
            "pr_review_required": True,
            "allows_force_pushes": False,
            "allows_deletions": False,
            "bypass_actors": [],
            "verified_by": "tools/verify_remote_enforcement.py",
            "github_api_evidence": {"branch_protection": {}},
            "branch_protection_verified": True,
            "required_checks_enforced": True,
            "objective_audit_required": True,
        }
    )
    assert validate_verified_claims(ev, "test") == []
    statuses = derive_statuses(ev)
    assert statuses["no_verify_status"] == "mitigated"
    assert statuses["external_enforcement_status"] == "verified"


def test_rulesets_payload_parses_required_checks() -> None:
    payload = [
        {
            "enforcement": "active",
            "rules": [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [{"context": "objective-audit"}],
                    },
                },
                {
                    "type": "pull_request",
                    "parameters": {"required_approving_review_count": 1},
                },
                {"type": "non_fast_forward"},
                {"type": "deletion"},
            ],
        }
    ]
    parsed = _parse_rulesets_enforcement(payload)
    assert "objective-audit" in parsed["required_status_checks"]
    assert parsed["pr_review_required"] is True
    assert parsed["allows_force_pushes"] is False
    assert parsed["allows_deletions"] is False


def test_fetch_github_without_cli_stays_pending() -> None:
    ev = fetch_github_cli_evidence()
    if ev.get("verification_method") == "pending":
        assert ev["branch_protection_verified"] is False


def test_artifacts_cannot_claim_verified_without_api_method(tmp_path: Path) -> None:
    art = tmp_path / "BRANCH_PROTECTION_PROOF.json"
    art.write_text(
        json.dumps(
            {
                "branch_protection": {"required": True, "verified": True},
                "remote_evidence": {"verification_method": "operator_manual_attestation"},
                "github_api_evidence": {"x": 1},
            }
        ),
        encoding="utf-8",
    )
    import tools.check_branch_protection_proof as mod

    (tmp_path / "governance" / "docs").mkdir(parents=True)
    (tmp_path / "governance" / "docs" / "BRANCH_PROTECTION_REQUIRED.md").write_text("#", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "verify_remote_enforcement.py").write_text("#", encoding="utf-8")
    (tmp_path / "governance" / "artifacts").mkdir(parents=True)
    (tmp_path / "governance" / "artifacts" / "BRANCH_PROTECTION_PROOF.json").write_text(
        art.read_text(encoding="utf-8"), encoding="utf-8"
    )
    orig = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        errors = mod.run_branch_protection_proof_check()
    finally:
        mod.REPO_ROOT = orig
    assert any("manual attestation cannot set verified=true" in e for e in errors)
