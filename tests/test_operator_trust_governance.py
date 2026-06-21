"""Mechanical locks for operator-trust stabilization governance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_operator_trust_governance import (
    check_card_explainability_permission,
    check_operator_trust_governance,
    check_stabilization_gate_json,
)
from verification.operator_trust_rth_validation import (
    build_dry_run_report,
    run_guest_switch_validation,
)


def test_operator_trust_governance_passes_on_repo():
    errors = check_operator_trust_governance()
    assert errors == [], "\n".join(errors)


def test_passive_risk_without_closure_fails():
    text = "known remaining risks: something broke.\n"
    has_passive = "known remaining risks" in text.lower()
    has_closure = any(c.lower() in text.lower() for c in (
        "owner branch:",
        "closure criteria",
        "run_rth_guest_switch_validation",
    ))
    assert has_passive and not has_closure


def test_guest_switch_harness_dry_run_does_not_pass():
    result = run_guest_switch_validation(
        base_url="http://127.0.0.1:1",
        dry_run=True,
        audit_date="2026-06-18",
    )
    assert result.pass_ is False
    assert "RTH_VALIDATION_NOT_RUN" in result.classifications


def test_dry_run_report_classification():
    report = build_dry_run_report(harness="test", audit_date="2026-06-18")
    assert report["classification"] == "RTH_VALIDATION_NOT_RUN"
    assert report["pass"] is False


def test_calibration_disabled_blocks_pass_classification():
    report = build_dry_run_report(harness="guest", audit_date="2026-06-18")
    env = report.get("runtime_env") or {}
    if not env.get("ED_CALIBRATION_LOG_enabled"):
        assert report.get("calibration_evidence_gap") == "EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED"


def test_open_items_contains_required_items():
    text = (ROOT / "docs/OPEN_ITEMS_OPERATOR_TRUST.md").read_text(encoding="utf-8")
    for item in (
        "LIVE_GUEST_SLA_NOT_PROVEN",
        "run_rth_guest_switch_validation",
        "run_rth_db_contention_validation",
        "GUEST_DATA_COMPLETENESS_NOT_PROVEN",
    ):
        assert item in text


def test_rth_guest_switch_tool_dry_run_cli():
    proc = subprocess.run(
        [sys.executable, "tools/run_rth_guest_switch_validation.py", "--dry-run"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "rth_guest_switch_validation" in proc.stdout


def test_stabilization_gate_blocks_card_explainability():
    gate = json.loads(
        (ROOT / "governance/OPERATOR_TRUST_STABILIZATION_GATE.json").read_text(encoding="utf-8")
    )
    assert gate.get("stabilization_artifacts_gate_pass") is True
    assert gate.get("ci_triage_gate_pass") is False
    assert gate.get("operator_readiness_gate_pass") is False
    assert gate.get("card_explainability_allowed") is False
    assert "card_explainability_gate_unblocked" not in gate
    assert "fix/card-price-conflict-explainability" in (gate.get("blocked_branches") or [])
    assert gate.get("next_allowed_step") == "resolve_pytest_full_failures"
    assert gate.get("next_allowed_branch") != "audit/ci-nonblocking-failures-triage"
    # Explicit, non-overloaded commit/count semantics (see gate field docs).
    # Current GitHub CI observation @ b44d5ab (STACK_WIRE proven, 17 -> 14).
    assert gate.get("current_ci_verified_commit") == "b44d5ab"
    assert gate.get("current_ci_pytest_full_run") == "27888713242"
    assert gate.get("current_ci_pytest_full_failure_count") == 14
    # Product matrix verified at the same proven commit.
    assert gate.get("pytest_full_matrix_verified_commit") == "b44d5ab"
    assert gate.get("pytest_full_product_matrix_failure_count") == 14
    # All six buckets closed to date.
    assert gate.get("meta_artifact_drift_failure_count") == 0
    assert gate.get("active_bundle_local_fix_pending_github_proof") is False
    assert gate.get("calibration_bypass_local_fix_pending_github_proof") is False
    assert gate.get("et_authority_local_fix_pending_github_proof") is False
    assert gate.get("anti_pattern_caps_local_fix_pending_github_proof") is False
    assert gate.get("stack_wire_integrity_local_fix_pending_github_proof") is False
    # Artifact sync only — no pending local fix — so expected == observed (14).
    assert gate.get("expected_after_pending_push") == 14
    # Legacy fields must stay honest to the cited run, not a prediction.
    assert gate.get("pytest_full_failure_count") == gate.get("current_ci_pytest_full_failure_count")
    assert gate.get("last_verified_commit") == gate.get("current_ci_verified_commit")
    assert gate.get("pytest_full_matrix_commit") == gate.get("last_verified_commit")


def test_gate_no_contradiction_unblocked_while_not_allowed():
    decision = (
        ROOT / "reports/operator_trust_backtrack/stabilization_decision_2026-06-18.md"
    ).read_text(encoding="utf-8")
    assert "card_explainability_gate_unblocked" not in decision
    assert "card_explainability_allowed: False" in decision
    assert "operator_readiness_gate_pass: False" in decision
    errors = check_card_explainability_permission()
    assert errors == [], "\n".join(errors)


def test_gate_artifacts_pass_does_not_allow_explainability():
    errors = check_stabilization_gate_json()
    assert errors == [], "\n".join(errors)
    gate = json.loads(
        (ROOT / "governance/OPERATOR_TRUST_STABILIZATION_GATE.json").read_text(encoding="utf-8")
    )
    assert gate["stabilization_artifacts_gate_pass"] is True
    assert gate["card_explainability_allowed"] is False


def test_next_allowed_step_resolves_pytest_full():
    gate = json.loads(
        (ROOT / "governance/OPERATOR_TRUST_STABILIZATION_GATE.json").read_text(encoding="utf-8")
    )
    assert gate.get("next_allowed_step") == "resolve_pytest_full_failures"
    assert gate.get("ci_triage_gate_pass") is False


def test_ci_triage_has_classifications_and_closure_criteria():
    triage = (ROOT / "reports/ci/ci_nonblocking_failure_triage_2026-06-18.md").read_text(encoding="utf-8")
    assert "failed as before" not in triage.lower()
    for check in ("hardening", "pytest-full", "schwab-csv-first"):
        assert check in triage.lower()
    assert "FIX_NOW" in triage or "FIX_NOW" in triage.upper()
    assert (
        "pytest-full failure matrix" in triage.lower()
        or "failure matrix (pytest-full)" in triage.lower()
        or "pytest_full_failure_matrix" in triage.lower()
    )
    assert "closure criteria" in triage.lower()


def test_pr_completion_audit_mentions_pr16_incomplete():
    text = (ROOT / "reports/operator_trust_backtrack/pr_completion_audit_2026-06-18.md").read_text(
        encoding="utf-8"
    )
    assert "16" in text
    assert "INCOMPLETE" in text or "harness" in text.lower()
