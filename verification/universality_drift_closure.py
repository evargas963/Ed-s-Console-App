"""Universality drift closure validation — CI triage matrix bucket proof registry."""
from __future__ import annotations

import re
from typing import Any

CLOSURE_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "UNIVERSAL_BY_CONSTRUCTION",
        "UNIVERSAL_WITH_PARAMETRIC_TESTS",
        "NOT_TICKER_RELATED",
    }
)

OPEN_RISK_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "NOT_PROVEN",
        "REPRESENTATIVE_ONLY_NOT_ENOUGH",
        "TICKER_SPECIFIC_RISK",
    }
)

ALLOWED_CLASSIFICATIONS: frozenset[str] = CLOSURE_CLASSIFICATIONS | OPEN_RISK_CLASSIFICATIONS

NON_CLOSURE_BUCKET_STATUSES: frozenset[str] = frozenset(
    {"OPEN", "HOLD", "REOPENED", "NOT_CLOSED"}
)

CLOSED_BUCKET_STATUS = "CLOSED_WITH_EVIDENCE"

REQUIRED_UNIVERSALITY_FIELDS: tuple[str, ...] = (
    "bucket_name",
    "changed_files",
    "runtime_or_static",
    "ticker_dependent",
    "variation_axes",
    "universal_classification",
    "universal_proof_type",
    "representative_only_used",
    "why_representative_is_sufficient_or_not",
    "parameterized_coverage",
    "construction_proof",
    "mechanical_lock_status",
    "closure_allowed",
    "code_change_approved",
    "artifact_change_approved",
    "commit_approved",
    "push_approved",
    "merge_approved",
    "github_pr_path_required",
    "github_pr_run_id",
    "github_pr_commit",
    "github_pr_failure_count",
    "local_only_pass",
    "touches_contract_locked_ui",
    "touches_rth_validation",
    "touches_card_explainability",
    "explicit_operator_authorization",
)

_BASE_THREE_ONLY_RE = re.compile(
    r"^(SPY|QQQ|IWM)(\s*,\s*(SPY|QQQ|IWM))*$",
    re.I,
)


def infer_bucket_status(row: dict[str, Any]) -> str:
    explicit = str(row.get("bucket_status") or "").strip()
    if explicit:
        return explicit
    if str(row.get("local_fix_status") or "").strip() == CLOSED_BUCKET_STATUS:
        return CLOSED_BUCKET_STATUS
    if str(row.get("fix_now_or_defer") or "").strip() == "closed":
        return CLOSED_BUCKET_STATUS
    return "OPEN"


def validate_universality_closure_row(
    row: dict[str, Any],
    *,
    triage_root: dict[str, Any] | None = None,
    row_index: int | None = None,
) -> list[str]:
    """Validate one pytest_full_failure_matrix row universality_closure block."""
    prefix = f"pytest_full_failure_matrix[{row_index}]" if row_index is not None else "pytest_full_failure_matrix[]"
    group = str(row.get("failure_group") or "")
    errors: list[str] = []

    u = row.get("universality_closure")
    if not isinstance(u, dict):
        return [f"{prefix} ({group}): missing universality_closure object"]

    for field in REQUIRED_UNIVERSALITY_FIELDS:
        if field not in u:
            errors.append(f"{prefix} ({group}): universality_closure missing {field!r}")

    if errors:
        return errors

    if str(u.get("bucket_name") or "") != group:
        errors.append(
            f"{prefix} ({group}): bucket_name {u.get('bucket_name')!r} != failure_group {group!r}"
        )

    cls = str(u.get("universal_classification") or "")
    if cls not in ALLOWED_CLASSIFICATIONS:
        errors.append(f"{prefix} ({group}): invalid universal_classification {cls!r}")

    status = infer_bucket_status(row)
    closed = status == CLOSED_BUCKET_STATUS
    closure_allowed = bool(u.get("closure_allowed"))
    merge_approved = bool(u.get("merge_approved"))
    ticker_dependent = bool(u.get("ticker_dependent"))
    rep_only = bool(u.get("representative_only_used"))
    construction = str(u.get("construction_proof") or "").strip()
    parameterized = str(u.get("parameterized_coverage") or "").strip()
    why_rep = str(u.get("why_representative_is_sufficient_or_not") or "").strip()
    if not why_rep:
        errors.append(f"{prefix} ({group}): why_representative_is_sufficient_or_not must be non-empty")

    if not ticker_dependent and u.get("variation_axes"):
        if u.get("variation_axes") != []:
            errors.append(f"{prefix} ({group}): variation_axes must be [] when ticker_dependent=false")

    # --- open/risk classifications: valid only when not closed ---
    if cls in OPEN_RISK_CLASSIFICATIONS:
        if closed:
            errors.append(
                f"{prefix} ({group}): {cls} cannot pair with bucket_status={status!r}"
            )
        if closure_allowed:
            errors.append(
                f"{prefix} ({group}): {cls} cannot have closure_allowed=true"
            )
        if merge_approved:
            errors.append(
                f"{prefix} ({group}): {cls} cannot have merge_approved=true"
            )

    # --- closure rules ---
    if closed and not closure_allowed:
        errors.append(
            f"{prefix} ({group}): CLOSED_WITH_EVIDENCE requires closure_allowed=true"
        )

    if closed and cls not in CLOSURE_CLASSIFICATIONS:
        errors.append(
            f"{prefix} ({group}): CLOSED_WITH_EVIDENCE requires closure classification, got {cls!r}"
        )

    if closure_allowed and cls not in CLOSURE_CLASSIFICATIONS:
        errors.append(
            f"{prefix} ({group}): closure_allowed=true requires closure classification, got {cls!r}"
        )

    if closure_allowed or closed:
        changed = u.get("changed_files")
        if not isinstance(changed, list) or not changed:
            errors.append(f"{prefix} ({group}): changed_files must be non-empty when closed/closing")

        if cls == "UNIVERSAL_BY_CONSTRUCTION" and ticker_dependent and not construction:
            errors.append(
                f"{prefix} ({group}): UNIVERSAL_BY_CONSTRUCTION + ticker_dependent requires construction_proof"
            )

        if cls == "UNIVERSAL_WITH_PARAMETRIC_TESTS" and not parameterized:
            errors.append(
                f"{prefix} ({group}): UNIVERSAL_WITH_PARAMETRIC_TESTS requires parameterized_coverage"
            )

        if rep_only and closure_allowed and not construction:
            errors.append(
                f"{prefix} ({group}): representative_only_used=true with closure_allowed=true requires construction_proof"
            )

        if ticker_dependent and closure_allowed and not construction and not parameterized:
            errors.append(
                f"{prefix} ({group}): ticker_dependent=true with closure_allowed=true requires "
                "construction_proof or parameterized_coverage"
            )

        if (
            ticker_dependent
            and closure_allowed
            and not construction
            and parameterized
            and _BASE_THREE_ONLY_RE.match(parameterized.strip())
        ):
            errors.append(
                f"{prefix} ({group}): parameterized_coverage is base-three-only (SPY/QQQ/IWM) "
                "without construction_proof"
            )

        if bool(u.get("local_only_pass")) and closed:
            errors.append(
                f"{prefix} ({group}): local_only_pass=true cannot pair with CLOSED_WITH_EVIDENCE"
            )

        if bool(u.get("github_pr_path_required")):
            if closed and not str(u.get("github_pr_run_id") or "").strip():
                errors.append(
                    f"{prefix} ({group}): github_pr_path_required=true requires github_pr_run_id on closure"
                )
            if closed and not str(u.get("github_pr_commit") or "").strip():
                errors.append(
                    f"{prefix} ({group}): github_pr_path_required=true requires github_pr_commit on closure"
                )
            if closure_allowed and not str(u.get("github_pr_run_id") or "").strip():
                errors.append(
                    f"{prefix} ({group}): closure_allowed=true with github_pr_path_required=true "
                    "requires github_pr_run_id"
                )

    # --- blocked work ---
    for touch, label in (
        ("touches_contract_locked_ui", "contract-locked UI"),
        ("touches_rth_validation", "RTH validation"),
        ("touches_card_explainability", "card explainability"),
    ):
        if bool(u.get(touch)) and not bool(u.get("explicit_operator_authorization")):
            if bool(u.get("code_change_approved")) or closure_allowed:
                errors.append(
                    f"{prefix} ({group}): {label} touched without explicit_operator_authorization "
                    "while code_change_approved or closure_allowed is true"
                )

    # --- merge vs CI gates (row-level) ---
    if merge_approved and triage_root:
        obs = triage_root.get("github_checks_last_observed") or {}
        if str(obs.get("pytest-full") or "").lower() != "pass":
            errors.append(
                f"{prefix} ({group}): merge_approved=true while pytest-full is not pass"
            )
        if triage_root.get("ci_triage_gate_pass") is False:
            errors.append(
                f"{prefix} ({group}): merge_approved=true while ci_triage_gate_pass is false"
            )
        if triage_root.get("universality_drift_gate_pass") is False:
            errors.append(
                f"{prefix} ({group}): merge_approved=true while universality_drift_gate_pass is false"
            )

    return errors


def validate_triage_universality_closure(triage: dict[str, Any]) -> list[str]:
    """Validate all matrix rows and root rollup fields."""
    errors: list[str] = []
    matrix = triage.get("pytest_full_failure_matrix")
    if not isinstance(matrix, list) or not matrix:
        return ["ci triage json: pytest_full_failure_matrix missing or empty"]

    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            errors.append(f"pytest_full_failure_matrix[{i}]: row must be object")
            continue
        errors.extend(
            validate_universality_closure_row(row, triage_root=triage, row_index=i)
        )

    root_merge = bool(triage.get("merge_approved"))
    if root_merge:
        obs = triage.get("github_checks_last_observed") or {}
        if str(obs.get("pytest-full") or "").lower() != "pass":
            errors.append("ci triage json: root merge_approved=true while pytest-full is not pass")
        if triage.get("ci_triage_gate_pass") is False:
            errors.append("ci triage json: root merge_approved=true while ci_triage_gate_pass is false")

    # Compute expected gate pass — false while any non-closed bucket remains or pytest-full red
    computed_gate = True
    for row in matrix:
        if not isinstance(row, dict):
            computed_gate = False
            continue
        status = infer_bucket_status(row)
        u = row.get("universality_closure") or {}
        if status == CLOSED_BUCKET_STATUS:
            if not bool(u.get("closure_allowed")):
                computed_gate = False
            if str(u.get("universal_classification") or "") not in CLOSURE_CLASSIFICATIONS:
                computed_gate = False
        elif status in NON_CLOSURE_BUCKET_STATUSES:
            computed_gate = False

    obs = triage.get("github_checks_last_observed") or {}
    if str(obs.get("pytest-full") or "").lower() != "pass":
        computed_gate = False

    declared = triage.get("universality_drift_gate_pass")
    if declared is not None and bool(declared) != computed_gate:
        errors.append(
            f"ci triage json: universality_drift_gate_pass={declared!r} "
            f"but computed gate is {computed_gate!r}"
        )

    return errors
