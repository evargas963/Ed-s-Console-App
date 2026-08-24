"""Operator-trust backtrack audit builders (PR #11–#16 reconciliation)."""
from __future__ import annotations

from typing import Any

PR_COMPLETION_ROWS: list[dict[str, Any]] = [
    {
        "pr": 11,
        "title": "UI real-time transport audit",
        "claimed_completion": "Static guard map, core/guest switch contract",
        "actual_completion_status": "AUDIT_ONLY",
        "open_risks_left_behind": ["LIVE_RTH_VALIDATION_NOT_COMPLETE"],
        "missing_proof": "Live switch SLA, STALE/LOADING correlation",
        "missing_harness": "RTH guest switch + master runbook",
        "required_correction": "Stabilization harness (this branch)",
        "status_after_branch": "NEEDS_RTH_VALIDATION_WITH_HARNESS",
    },
    {
        "pr": 12,
        "title": "Tier C duplicate render dedup",
        "claimed_completion": "Duplicate Tier C fingerprint skip",
        "actual_completion_status": "CLOSED_WITH_EVIDENCE",
        "open_risks_left_behind": [],
        "missing_proof": None,
        "missing_harness": None,
        "required_correction": None,
        "status_after_branch": "CLOSED_WITH_EVIDENCE",
    },
    {
        "pr": 13,
        "title": "Card Trust Contract",
        "claimed_completion": "Governing doc for card meaning",
        "actual_completion_status": "DOCS_ONLY",
        "open_risks_left_behind": ["CARD_EXPLAINABILITY_NOT_IMPLEMENTED"],
        "missing_proof": "UI behavior unchanged",
        "missing_harness": "Card conflict explainability branch blocked",
        "required_correction": "fix/card-price-conflict-explainability after stabilization",
        "status_after_branch": "COMPLETION_BRANCH_REQUIRED",
    },
    {
        "pr": 14,
        "title": "SQLite contention impact audit",
        "claimed_completion": "Instrumentation + classifications",
        "actual_completion_status": "AUDIT_AND_INSTRUMENTATION",
        "open_risks_left_behind": ["DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN"],
        "missing_proof": "Lock-wait vs STALE/LOADING causality",
        "missing_harness": "run_rth_db_contention_validation.py",
        "required_correction": "Stabilization harness (this branch)",
        "status_after_branch": "NEEDS_RTH_VALIDATION_WITH_HARNESS",
    },
    {
        "pr": 15,
        "title": "DB contention operator surface",
        "claimed_completion": "DB WAITING/DEGRADED/LOCKED visibility",
        "actual_completion_status": "SURFACE_ONLY",
        "open_risks_left_behind": ["DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN"],
        "missing_proof": "Visibility ≠ root cause proven",
        "missing_harness": "DB RTH correlation harness",
        "required_correction": "Do not label DB fixed — correlation harness required",
        "status_after_branch": "NEEDS_RTH_VALIDATION_WITH_HARNESS",
    },
    {
        "pr": 16,
        "title": "Guest switch SLA diagnostics",
        "claimed_completion": "Per-tier switch timing + switch-state chip",
        "actual_completion_status": "INCOMPLETE",
        "open_risks_left_behind": ["LIVE_GUEST_SLA_NOT_PROVEN"],
        "missing_proof": "Live RTH guest switch SLA",
        "missing_harness": "run_rth_guest_switch_validation.py (added in stabilization)",
        "required_correction": (
            "PR merged without runnable closure harness — completion via stabilization branch"
        ),
        "status_after_branch": "NEEDS_RTH_VALIDATION_WITH_HARNESS",
        "ci_failures_at_merge": ["hardening", "pytest-full", "schwab-csv-first"],
        "admin_bypass": "objective-audit-only gate; other checks red",
    },
]


# Open items that mechanically block card explainability until closed or accepted.
CARD_EXPLAINABILITY_BLOCKING_OPEN_ITEMS: tuple[str, ...] = (
    "LIVE_GUEST_SLA_NOT_PROVEN",
    "DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN",
    "BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE",
    "RTH_VALIDATION_NOT_EXECUTED_AFTER_TRANSPORT_FIXES",
    "HARDENING_CI_FAILING_NON_BLOCKING",
    "PYTEST_FULL_CI_FAILING_NON_BLOCKING",
    "SCHWAB_CSV_FIRST_FAILING_OR_MIXED_NON_BLOCKING",
)

CARD_EXPLAINABILITY_BLOCK_REASONS: tuple[str, ...] = (
    "CI non-blocking failures require triage",
    "RTH validation not executed",
    *CARD_EXPLAINABILITY_BLOCKING_OPEN_ITEMS,
)

