"""Phase 3F — evidence index and limitations checker tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_evidence_index_exists_with_required_claims():
    path = REPO / "governance" / "artifacts" / "EVIDENCE_INDEX.json"
    assert path.is_file(), "run python tools/_build_evidence_index.py"
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = {c["claim_id"] for c in data["claims"]}
    for required in (
        "agent_preload",
        "r004_gated",
        "r005_blocked",
        "r031_non_production",
        "github_external_enforcement",
        "no_l5_claim",
        "live_schwab_traffic",
    ):
        assert required in ids


def test_current_limitations_has_required_gaps():
    path = REPO / "governance" / "artifacts" / "CURRENT_LIMITATIONS.json"
    assert path.is_file(), "run python tools/_build_current_limitations.py"
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = {lim["limitation_id"] for lim in data["limitations"]}
    assert "live_schwab_proof" in ids
    assert "github_branch_protection" in ids
    assert "l5_not_claimed" in ids
    assert data.get("maturity_changes_proposed") == []


def test_no_l5_claims_in_evidence_index():
    path = REPO / "governance" / "artifacts" / "EVIDENCE_INDEX.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for claim in data["claims"]:
        verdict = claim.get("verdict", "")
        assert verdict != "l5"
        assert "L5 proven" not in claim.get("claim", "")
        if claim.get("claim_id") == "no_l5_claim":
            assert claim["verdict"] == "explicitly_rejected"


def test_reviewer_readme_exists():
    assert (REPO / "governance" / "REVIEWER_README.md").is_file()


def test_reviewer_evidence_checker_passes():
    from tools.check_reviewer_evidence_index import run_reviewer_evidence_index_check

    assert run_reviewer_evidence_index_check() == []


def test_proven_claims_have_tests():
    path = REPO / "governance" / "artifacts" / "EVIDENCE_INDEX.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    proven = {"proven", "partially_proven", "detected_not_prevented"}
    for claim in data["claims"]:
        if claim["verdict"] in proven:
            assert claim.get("test_path"), claim["claim_id"]
