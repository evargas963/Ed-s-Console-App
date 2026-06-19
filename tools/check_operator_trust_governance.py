#!/usr/bin/env python3
"""Operator-trust governance mechanical locks — passive risks, harnesses, stabilization gate."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from verification.operator_trust_backtrack import (
    CARD_EXPLAINABILITY_BLOCKING_OPEN_ITEMS,
)
from verification.operator_trust_rth_validation import (
    ALLOWED_OPEN_ITEM_STATUSES,
    CLOSURE_HANDLING_PHRASES,
    OPEN_ITEM_REQUIRED_FIELDS,
    PASSIVE_RISK_PHRASES,
)

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "docs/OPEN_ITEMS_OPERATOR_TRUST.md",
    "docs/PR_REVIEW_STANDARD.md",
    "docs/ADMIN_BYPASS_REGISTER.md",
    "docs/RUNTIME_EVIDENCE_ENV_CONTRACT.md",
    "docs/NO_SILENT_DEGRADATION_POLICY.md",
    "reports/rth_validation/RTH_OPERATOR_TRUST_VALIDATION_RUNBOOK.md",
    "tools/run_rth_guest_switch_validation.py",
    "tools/run_rth_db_contention_validation.py",
    "tools/run_rth_base_capture_normalization_validation.py",
    "reports/ci/ci_nonblocking_failure_triage_2026-06-18.md",
    "reports/ci/ci_nonblocking_failure_triage_2026-06-18.json",
    "reports/operator_trust_backtrack/pr_completion_audit_2026-06-18.md",
    "reports/operator_trust_backtrack/pr_completion_audit_2026-06-18.json",
    "reports/operator_trust_backtrack/stabilization_decision_2026-06-18.md",
    "governance/OPERATOR_TRUST_STABILIZATION_GATE.json",
    ".github/pull_request_template.md",
)

PASSIVE_SCAN_GLOBS: tuple[str, ...] = (
    "docs/OPEN_ITEMS_OPERATOR_TRUST.md",
    "reports/operator_trust_backtrack/*.md",
    "reports/ui_transport/ui_guest_switch_sla_2026-06-18.md",
)

CI_CHECKS = ("hardening", "pytest-full", "schwab-csv-first")
CI_CLASSIFICATIONS = (
    "FIXED_NOW",
    "FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI",
    "CLOSED_WITH_EVIDENCE",
    "EXTERNAL_SECRET_REQUIRED_WITH_EVIDENCE",
    "OPEN_BLOCKING",
    "PRE_EXISTING_BUT_BLOCKING",
    "PRE_EXISTING_AND_ACCEPTED_WITH_REASON",
    "NOT_REPRODUCED",
)


def _read(rel: str) -> str:
    p = _REPO / rel
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def check_required_artifacts() -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_ARTIFACTS:
        if not (_REPO / rel).is_file():
            errors.append(f"operator_trust: missing required artifact {rel}")
    return errors


def check_stabilization_gate_json() -> list[str]:
    errors: list[str] = []
    path = _REPO / "governance/OPERATOR_TRUST_STABILIZATION_GATE.json"
    if not path.is_file():
        return ["operator_trust: missing governance/OPERATOR_TRUST_STABILIZATION_GATE.json"]
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"operator_trust: stabilization gate invalid JSON: {e}"]
    banned_fields = (
        "card_explainability_gate_unblocked",
        "safe_to_proceed_card_explainability",
        "stabilization_gate_pass",
    )
    for field in banned_fields:
        if field in raw:
            errors.append(
                f"operator_trust: gate uses banned ambiguous field {field!r} — "
                "use stabilization_artifacts_gate_pass / operator_readiness_gate_pass / "
                "card_explainability_allowed"
            )
    for key in (
        "stabilization_artifacts_gate_pass",
        "ci_triage_gate_pass",
        "operator_readiness_gate_pass",
        "card_explainability_allowed",
        "next_allowed_step",
    ):
        if key not in data:
            errors.append(f"operator_trust: gate missing required field {key}")
    if data.get("card_explainability_allowed") is True:
        errors.append("operator_trust: card_explainability_allowed must be false until readiness gate passes")
    if data.get("operator_readiness_gate_pass") is False and data.get("card_explainability_allowed") is True:
        errors.append(
            "operator_trust: card_explainability_allowed cannot be true when operator_readiness_gate_pass is false"
        )
    if data.get("stabilization_artifacts_gate_pass") is not True:
        errors.append("operator_trust: stabilization_artifacts_gate_pass must be true on this branch")
    ci_pass = data.get("ci_triage_gate_pass")
    next_step = str(data.get("next_allowed_step") or "")
    if ci_pass is False and next_step not in ("await_pr19_ci_results", "resolve_pytest_full_failures"):
        errors.append(
            "operator_trust: when ci_triage_gate_pass is false, next_allowed_step must be "
            "await_pr19_ci_results or resolve_pytest_full_failures"
        )
    if ci_pass is True and next_step != "operator_rth_validation":
        errors.append(
            "operator_trust: when ci_triage_gate_pass is true, next_allowed_step must be operator_rth_validation"
        )
    legacy_branch = str(data.get("next_allowed_branch") or "")
    if legacy_branch == "audit/ci-nonblocking-failures-triage":
        errors.append(
            "operator_trust: next_allowed_branch must not self-reference audit/ci-nonblocking-failures-triage "
            "(use next_allowed_step)"
        )
    blocked = data.get("blocked_branches") or data.get("blocked_branches_until_pass") or []
    if "fix/card-price-conflict-explainability" not in blocked:
        errors.append("operator_trust: fix/card-price-conflict-explainability must remain in blocked_branches")
    for key in ("required_artifacts", "required_harnesses", "required_policy_docs"):
        items = data.get(key) or []
        for rel in items:
            if not (_REPO / rel).is_file():
                errors.append(f"operator_trust: gate lists missing {rel}")
    return errors


def _open_item_status(open_items_text: str, item_id: str) -> str | None:
    """Return status slug for ### ITEM_ID section, or None if missing."""
    m = re.search(
        rf"### {re.escape(item_id)}\s+.*?\*\*Status\*\*\s*\|\s*`([^`]+)`",
        open_items_text,
        re.S,
    )
    return m.group(1) if m else None


def check_card_explainability_permission() -> list[str]:
    errors: list[str] = []
    gate_path = _REPO / "governance/OPERATOR_TRUST_STABILIZATION_GATE.json"
    decision_path = _REPO / "reports/operator_trust_backtrack/stabilization_decision_2026-06-18.md"
    for rel in (
        "governance/OPERATOR_TRUST_STABILIZATION_GATE.json",
        "reports/operator_trust_backtrack/stabilization_decision_2026-06-18.md",
    ):
        text = _read(rel)
        for banned in (
            "card_explainability_gate_unblocked",
            "safe_to_proceed_card_explainability: true",
            "safe_to_proceed_card_explainability: True",
        ):
            if banned.lower() in text.lower():
                errors.append(f"{rel}: banned contradictory field {banned!r}")
    if not gate_path.is_file():
        return errors
    data = json.loads(gate_path.read_text(encoding="utf-8"))
    open_items = _read("docs/OPEN_ITEMS_OPERATOR_TRUST.md")
    blocking_open: list[str] = []
    for item in CARD_EXPLAINABILITY_BLOCKING_OPEN_ITEMS:
        status = _open_item_status(open_items, item)
        if status is None:
            errors.append(f"OPEN_ITEMS_OPERATOR_TRUST.md: missing blocking item {item}")
            continue
        if status not in ("CLOSED_WITH_EVIDENCE",):
            blocking_open.append(item)
    if data.get("card_explainability_allowed") is True and blocking_open:
        errors.append(
            "operator_trust: card_explainability_allowed true while blocking items remain open: "
            + ", ".join(blocking_open)
        )
    if decision_path.is_file():
        dec_text = decision_path.read_text(encoding="utf-8")
        if "card_explainability_allowed: True" in dec_text:
            errors.append("stabilization_decision: card_explainability_allowed must be False")
        if "operator_readiness_gate_pass: True" in dec_text and blocking_open:
            errors.append(
                "stabilization_decision: operator_readiness_gate_pass cannot be True while blocking items open"
            )
    return errors


def check_passive_risk_language() -> list[str]:
    errors: list[str] = []
    for pattern in PASSIVE_SCAN_GLOBS:
        for path in _REPO.glob(pattern):
            if "archive" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for phrase in PASSIVE_RISK_PHRASES:
                if phrase not in text:
                    continue
                if any(c.lower() in text for c in CLOSURE_HANDLING_PHRASES):
                    continue
                errors.append(
                    f"{path.relative_to(_REPO)}: passive risk {phrase!r} without closure handling"
                )
    triage = _read("reports/ci/ci_nonblocking_failure_triage_2026-06-18.md").lower()
    if re.search(r"(?<!not )failed as before", triage):
        errors.append("ci triage: banned phrase 'failed as before'")
    return errors


def check_open_items_matrix() -> list[str]:
    errors: list[str] = []
    text = _read("docs/OPEN_ITEMS_OPERATOR_TRUST.md")
    if not text:
        return ["docs/OPEN_ITEMS_OPERATOR_TRUST.md: missing"]
    for field in OPEN_ITEM_REQUIRED_FIELDS:
        alt = field.replace(":", "")
        if field not in text and f"**{alt}**" not in text:
            errors.append(f"OPEN_ITEMS_OPERATOR_TRUST.md: missing {field}")
    for status in ALLOWED_OPEN_ITEM_STATUSES:
        if status not in text:
            errors.append(f"OPEN_ITEMS_OPERATOR_TRUST.md: must document status {status}")
    bad_status = re.findall(r"\*\*Status\*\*\s*\|\s*`([^`]+)`", text)
    for st in bad_status:
        if st not in ALLOWED_OPEN_ITEM_STATUSES:
            errors.append(f"OPEN_ITEMS_OPERATOR_TRUST.md: invalid status {st!r}")
    required_items = (
        "LIVE_GUEST_SLA_NOT_PROVEN",
        "DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN",
        "BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE",
        "CI_NONBLOCKING_FAILURES_NOT_TRIAGED",
        "HARDENING_CI_FAILING_NON_BLOCKING",
        "PYTEST_FULL_CI_FAILING_NON_BLOCKING",
        "SCHWAB_CSV_FIRST_FAILING_OR_MIXED_NON_BLOCKING",
        "ADMIN_BYPASS_USED_WITH_FAILED_CHECKS",
        "ED_CALIBRATION_LOG_DISABLED_EVIDENCE_GAP",
        "PROCESS_LOCAL_SQLITE_COUNTERS_ONLY",
        "CARD_EXPLAINABILITY_NOT_IMPLEMENTED",
        "FUSION_HISTOGRAM_OVERRIDE_POLICY_UNDECIDED",
        "MARKET_SESSION_TRADEABILITY_GUARD_NOT_AUDITED",
        "GUEST_DATA_COMPLETENESS_NOT_PROVEN",
        "RTH_VALIDATION_NOT_EXECUTED_AFTER_TRANSPORT_FIXES",
    )
    for item in required_items:
        if item not in text:
            errors.append(f"OPEN_ITEMS_OPERATOR_TRUST.md: missing item {item}")
    return errors


def check_admin_bypass_register() -> list[str]:
    errors: list[str] = []
    text = _read("docs/ADMIN_BYPASS_REGISTER.md")
    if not text:
        return ["docs/ADMIN_BYPASS_REGISTER.md: missing"]
    for pr in ("#14", "#15", "#16", "#18"):
        if pr not in text and f"PR {pr[1:]}" not in text:
            errors.append(f"ADMIN_BYPASS_REGISTER: missing entry for PR {pr[1:]}")
    for field in (
        "Checks failing",
        "Reason merge proceeded",
        "Follow-up branch",
        "Closure criteria",
    ):
        if field not in text and f"**{field}:**" not in text:
            errors.append(f"ADMIN_BYPASS_REGISTER: missing {field}")
    return errors


def check_ci_triage_report() -> list[str]:
    errors: list[str] = []
    md = _read("reports/ci/ci_nonblocking_failure_triage_2026-06-18.md")
    if not md:
        return ["ci triage md: missing"]
    if "pytest-full failure matrix" not in md.lower() and "pytest_full_failure_matrix" not in md.lower():
        errors.append("ci triage: must include pytest-full failure matrix")
    for check in CI_CHECKS:
        if check not in md.lower():
            errors.append(f"ci triage: must name {check}")
    if "closure criteria" not in md.lower():
        errors.append("ci triage: must include Closure criteria per check")
    for check in CI_CHECKS:
        section = re.search(rf"## {re.escape(check)}\s+(.*?)(?=\n## |\Z)", md, re.S | re.I)
        if not section:
            errors.append(f"ci triage: missing section for {check}")
            continue
        body = section.group(1)
        if not any(c in body for c in CI_CLASSIFICATIONS):
            errors.append(f"ci triage: {check} missing allowed classification")
        if "closure criteria" not in body.lower():
            errors.append(f"ci triage: {check} missing closure criteria")
    try:
        triage_json = json.loads(_read("reports/ci/ci_nonblocking_failure_triage_2026-06-18.json") or "{}")
    except json.JSONDecodeError as e:
        errors.append(f"ci triage json invalid: {e}")
    else:
        for check in CI_CHECKS:
            row = (triage_json.get("checks") or {}).get(check) or {}
            if not row.get("classification"):
                errors.append(f"ci triage json: {check} missing classification")
            if not row.get("closure_criteria"):
                errors.append(f"ci triage json: {check} missing closure_criteria")
        matrix = triage_json.get("pytest_full_failure_matrix") or []
        if not matrix:
            errors.append("ci triage json: pytest_full_failure_matrix missing or empty")
    return errors


def check_rth_harnesses_reference_endpoints() -> list[str]:
    errors: list[str] = []
    guest = _read("tools/run_rth_guest_switch_validation.py")
    if "/api/diagnostics/ticker-switch" not in guest:
        errors.append("guest harness: missing ticker-switch endpoint")
    if "/api/diagnostics/sqlite-contention" not in guest:
        errors.append("guest harness: missing sqlite-contention endpoint")
    if "--dry-run" not in guest:
        errors.append("guest harness: missing --dry-run")
    db_h = _read("tools/run_rth_db_contention_validation.py")
    if "STALE" not in db_h or "LOADING" not in db_h:
        errors.append("db harness: must reference STALE/LOADING correlation")
    base_h = _read("tools/run_rth_base_capture_normalization_validation.py")
    for t in ("SPY", "QQQ", "IWM"):
        if t not in base_h:
            errors.append(f"base capture harness: missing {t}")
    return errors


def check_operator_trust_governance() -> list[str]:
    errors: list[str] = []
    errors.extend(check_required_artifacts())
    errors.extend(check_stabilization_gate_json())
    errors.extend(check_passive_risk_language())
    errors.extend(check_open_items_matrix())
    errors.extend(check_admin_bypass_register())
    errors.extend(check_ci_triage_report())
    errors.extend(check_rth_harnesses_reference_endpoints())
    errors.extend(check_card_explainability_permission())
    return errors


def main() -> int:
    errors = check_operator_trust_governance()
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("check_operator_trust_governance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
