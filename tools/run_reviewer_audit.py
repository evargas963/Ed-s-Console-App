#!/usr/bin/env python3
"""Phase 3F — reviewer-safe audit runner (read-only verification commands)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

REVIEWER_STEPS: tuple[tuple[str, list[str]], ...] = (
    (
        "objective-audit",
        [sys.executable, "tools/enforce_all_rules.py", "--objective-audit"],
    ),
    ("adversarial", [sys.executable, "-m", "pytest", "tests/adversarial/", "-q"]),
    ("runtime_proof", [sys.executable, "-m", "pytest", "tests/runtime_proof/", "-q"]),
    ("governance_mutation", [sys.executable, "-m", "pytest", "tests/governance_mutation/", "-q"]),
    (
        "decision_governance",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/decision_reconstruction/",
            "tests/release_object/",
            "tests/test_governance_consolidation.py",
            "-q",
        ],
    ),
    ("agent_preload", [sys.executable, "-m", "pytest", "tests/test_agent_preload_contract.py", "-q"]),
    (
        "phase3d_remote",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_remote_enforcement_evidence.py",
            "tests/test_branch_protection_proof.py",
            "tests/test_required_status_checks.py",
            "tests/test_no_verify_resistance.py",
            "tests/test_governance_self_protection.py",
            "-q",
        ],
    ),
    ("reviewer_evidence", [sys.executable, "-m", "pytest", "tests/test_reviewer_evidence_index.py", "-q"]),
)


def run_reviewer_audit(*, verbose: bool = True) -> dict:
    results: list[dict] = []
    all_ok = True
    for name, cmd in REVIEWER_STEPS:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()
        summary = tail[-1] if tail else ""
        ok = proc.returncode == 0
        all_ok = all_ok and ok
        row = {"step": name, "exit_code": proc.returncode, "summary": summary, "command": " ".join(cmd)}
        results.append(row)
        if verbose:
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {name}: exit {proc.returncode} — {summary}")
    return {"ok": all_ok, "steps": results}


def main() -> int:
    print("=== EdWebConsole reviewer audit ===")
    print(f"Repo: {REPO}")
    print("Entry point: governance/REVIEWER_README.md")
    print("")
    outcome = run_reviewer_audit(verbose=True)
    print("")
    passed = sum(1 for s in outcome["steps"] if s["exit_code"] == 0)
    total = len(outcome["steps"])
    print(f"Reviewer audit: {passed}/{total} steps passed")
    if outcome["ok"]:
        print("VERDICT: reviewer audit CLEAN (local — not GitHub external proof)")
    else:
        failed = [s["step"] for s in outcome["steps"] if s["exit_code"] != 0]
        print(f"VERDICT: FAIL — steps: {', '.join(failed)}")
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
