"""Mechanical locks for universality drift closure state machine."""
from __future__ import annotations

import pytest

from verification.universality_drift_closure import (
    CLOSED_BUCKET_STATUS,
    validate_triage_universality_closure,
    validate_universality_closure_row,
)


def _base_row(
    group: str,
    *,
    status: str = "OPEN",
    classification: str = "NOT_PROVEN",
    closure_allowed: bool = False,
    ticker_dependent: bool = False,
    **overrides,
) -> dict:
    u = {
        "bucket_name": group,
        "changed_files": overrides.pop("changed_files", []),
        "runtime_or_static": overrides.pop("runtime_or_static", "static"),
        "ticker_dependent": ticker_dependent,
        "variation_axes": overrides.pop("variation_axes", []),
        "universal_classification": classification,
        "universal_proof_type": overrides.pop("universal_proof_type", "not_applicable"),
        "representative_only_used": overrides.pop("representative_only_used", False),
        "why_representative_is_sufficient_or_not": overrides.pop(
            "why_representative_is_sufficient_or_not",
            "Universality proof pending.",
        ),
        "parameterized_coverage": overrides.pop("parameterized_coverage", ""),
        "construction_proof": overrides.pop("construction_proof", ""),
        "mechanical_lock_status": overrides.pop("mechanical_lock_status", status),
        "closure_allowed": closure_allowed,
        "code_change_approved": False,
        "artifact_change_approved": False,
        "commit_approved": False,
        "push_approved": False,
        "merge_approved": False,
        "github_pr_path_required": overrides.pop("github_pr_path_required", False),
        "github_pr_run_id": overrides.pop("github_pr_run_id", ""),
        "github_pr_commit": overrides.pop("github_pr_commit", ""),
        "github_pr_failure_count": overrides.pop("github_pr_failure_count", None),
        "local_only_pass": False,
        "touches_contract_locked_ui": False,
        "touches_rth_validation": False,
        "touches_card_explainability": False,
        "explicit_operator_authorization": False,
    }
    u.update(overrides)
    row = {
        "failure_group": group,
        "universality_closure": u,
    }
    if status == CLOSED_BUCKET_STATUS:
        row["bucket_status"] = CLOSED_BUCKET_STATUS
    else:
        row["bucket_status"] = status
    return row


def test_open_not_proven_passes():
    row = _base_row("ML_PREDICT_STRICT_VERSION", status="HOLD", classification="NOT_PROVEN")
    assert validate_universality_closure_row(row) == []


def test_reopened_representative_only_passes():
    row = _base_row(
        "LIVE_BUNDLE_SSE_CACHE",
        status="REOPENED",
        classification="REPRESENTATIVE_ONLY_NOT_ENOUGH",
        representative_only_used=True,
        why_representative_is_sufficient_or_not="NOT SUFFICIENT — reopen for parametric matrix.",
    )
    assert validate_universality_closure_row(row) == []


def test_closed_with_risk_class_fails():
    row = _base_row(
        "LIVE_BUNDLE_SSE_CACHE",
        status=CLOSED_BUCKET_STATUS,
        classification="REPRESENTATIVE_ONLY_NOT_ENOUGH",
        closure_allowed=True,
        changed_files=["tests/test_issue20_23_live_bundle.py"],
        github_pr_path_required=True,
        github_pr_run_id="1",
        github_pr_commit="abc",
    )
    errs = validate_universality_closure_row(row)
    assert any("cannot pair with bucket_status" in e for e in errs)


def test_closure_allowed_with_not_proven_fails():
    row = _base_row(
        "ML_PREDICT_STRICT_VERSION",
        status="HOLD",
        classification="NOT_PROVEN",
        closure_allowed=True,
    )
    errs = validate_universality_closure_row(row)
    assert any("closure_allowed=true" in e for e in errs)


def test_closed_without_github_run_fails():
    row = _base_row(
        "CALIBRATION_BYPASS_ALLOWLIST",
        status=CLOSED_BUCKET_STATUS,
        classification="NOT_TICKER_RELATED",
        closure_allowed=True,
        changed_files=["tests/test_calibration_bypass_closure.py"],
        github_pr_path_required=True,
        github_pr_run_id="",
        github_pr_commit="",
    )
    errs = validate_universality_closure_row(row)
    assert any("github_pr_run_id" in e for e in errs)


def test_local_only_closed_fails():
    row = _base_row(
        "ET_AUTHORITY_DAILY_SCOREBOARD",
        status=CLOSED_BUCKET_STATUS,
        classification="NOT_TICKER_RELATED",
        closure_allowed=True,
        changed_files=["calibration/daily_scoreboard.py"],
        github_pr_path_required=True,
        github_pr_run_id="27882570666",
        github_pr_commit="afb361d",
        local_only_pass=True,
    )
    errs = validate_universality_closure_row(row)
    assert any("local_only_pass=true" in e for e in errs)


def test_ui_touch_without_auth_fails():
    row = _base_row(
        "UI_V2_CONFIDENCE_LABELS",
        status="OPEN",
        classification="NOT_PROVEN",
        touches_contract_locked_ui=True,
        code_change_approved=True,
    )
    errs = validate_universality_closure_row(row)
    assert any("contract-locked UI" in e for e in errs)


def test_closed_not_ticker_related_with_github_passes():
    row = _base_row(
        "CALIBRATION_BYPASS_ALLOWLIST",
        status=CLOSED_BUCKET_STATUS,
        classification="NOT_TICKER_RELATED",
        closure_allowed=True,
        changed_files=["tests/test_calibration_bypass_closure.py"],
        github_pr_path_required=True,
        github_pr_run_id="27878597275",
        github_pr_commit="7bf369c",
        github_pr_failure_count=20,
        universal_proof_type="not_applicable",
        why_representative_is_sufficient_or_not="Repo-wide static scan; no ticker axis.",
    )
    assert validate_universality_closure_row(row) == []


def test_construction_closed_ticker_dependent_passes():
    row = _base_row(
        "ACTIVE_BUNDLE_ENCODER_LAYOUT",
        status=CLOSED_BUCKET_STATUS,
        classification="UNIVERSAL_BY_CONSTRUCTION",
        closure_allowed=True,
        ticker_dependent=True,
        changed_files=["tests/test_active_bundle_contract_v1.py"],
        variation_axes=["ticker", "horizon", "model_dir"],
        construction_proof=(
            "active_bundle_dir(ticker, hz) and check_active_bundle_complete(ticker, hz) "
            "accept arbitrary ticker strings — no SPY-only branch."
        ),
        github_pr_path_required=True,
        github_pr_run_id="27877046342",
        github_pr_commit="0068226",
        github_pr_failure_count=22,
        universal_proof_type="construction",
        why_representative_is_sufficient_or_not="Construction proof recorded; SPY tests are one instance.",
    )
    assert validate_universality_closure_row(row) == []


def test_base_three_only_param_without_construction_fails():
    row = _base_row(
        "ACTIVE_BUNDLE_ENCODER_LAYOUT",
        status=CLOSED_BUCKET_STATUS,
        classification="UNIVERSAL_WITH_PARAMETRIC_TESTS",
        closure_allowed=True,
        ticker_dependent=True,
        changed_files=["tests/test_active_bundle_contract_v1.py"],
        variation_axes=["ticker"],
        parameterized_coverage="SPY, QQQ, IWM",
        construction_proof="",
        github_pr_path_required=True,
        github_pr_run_id="27877046342",
        github_pr_commit="0068226",
    )
    errs = validate_universality_closure_row(row)
    assert any("base-three-only" in e for e in errs)


def test_checker_passes_on_repo_triage_json():
    from tools.check_universality_drift_closure import check_universality_drift_closure

    assert check_universality_drift_closure() == []
