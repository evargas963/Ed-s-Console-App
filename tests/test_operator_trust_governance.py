"""Mechanical locks for operator-trust stabilization governance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_operator_trust_governance import (
    check_operator_trust_governance,
    check_passive_risk_language,
)
from verification.operator_trust_rth_validation import (
    build_dry_run_report,
    capture_runtime_env,
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
    assert gate.get("card_explainability_blocked_until_gate_passes") is True
    assert "fix/card-price-conflict-explainability" in (gate.get("blocked_branches_until_pass") or [])


def test_pr_completion_audit_mentions_pr16_incomplete():
    text = (ROOT / "reports/operator_trust_backtrack/pr_completion_audit_2026-06-18.md").read_text(
        encoding="utf-8"
    )
    assert "16" in text
    assert "INCOMPLETE" in text or "harness" in text.lower()
