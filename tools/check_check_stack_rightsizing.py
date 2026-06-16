#!/usr/bin/env python3
"""Mechanical checks for check-stack right-sizing policy (Phase 3I)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INVENTORY_PATH = REPO / "governance" / "artifacts" / "CHECK_STACK_INVENTORY.json"
POLICY_MD = REPO / "governance" / "docs" / "CHECK_STACK_RIGHTSIZING.md"
AGENTS_MD = REPO / "AGENTS.md"


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_check_stack_rightsizing() -> list[str]:
    errors: list[str] = []

    if not POLICY_MD.is_file():
        errors.append("governance/docs/CHECK_STACK_RIGHTSIZING.md: missing")
    else:
        md = POLICY_MD.read_text(encoding="utf-8", errors="replace")
        for marker in ("**Scope:**", "Tier 0", "Tier 1", "Over budget", "Runtime budget"):
            if marker not in md:
                errors.append(f"CHECK_STACK_RIGHTSIZING.md: missing marker {marker!r}")

    inv = _load_json(INVENTORY_PATH)
    if not inv:
        errors.append("governance/artifacts/CHECK_STACK_INVENTORY.json: missing or unreadable")
        return errors

    if inv.get("schema_version") != 1:
        errors.append("CHECK_STACK_INVENTORY.json: schema_version must be 1")

    budgets = inv.get("runtime_budgets_seconds") or {}
    for key in ("precommit_normal", "precommit_governance", "prepush_normal", "prepush_governance"):
        if key not in budgets:
            errors.append(f"CHECK_STACK_INVENTORY.json: missing runtime budget {key!r}")

    if not inv.get("checks"):
        errors.append("CHECK_STACK_INVENTORY.json: checks list empty")

    if inv.get("duplication_analysis") is None:
        errors.append("CHECK_STACK_INVENTORY.json: duplication_analysis missing")
    elif not isinstance(inv.get("duplication_analysis"), list):
        errors.append("CHECK_STACK_INVENTORY.json: duplication_analysis must be a list")

    over = inv.get("over_budget") or []
    prepush_over = [r for r in over if r.get("path") == "pre-push"]
    if not prepush_over:
        errors.append(
            "CHECK_STACK_INVENTORY.json: pre-push over budget must be recorded (not silently accepted)"
        )
    else:
        row = prepush_over[0]
        if not row.get("documented_reason"):
            errors.append("CHECK_STACK_INVENTORY.json: pre-push over_budget row missing documented_reason")

    rec = inv.get("recommendations") or {}
    for key in (
        "keep_in_precommit",
        "move_to_prepush",
        "move_to_ci_only",
        "make_incremental",
        "manual_review",
    ):
        if key not in rec:
            errors.append(f"CHECK_STACK_INVENTORY.json: recommendations missing key {key!r}")

    # Required check families present
    check_ids = {c.get("check_id") for c in inv.get("checks") or []}
    for required in (
        "fix-everything-we-touch",
        "fix-everything-we-touch-full-static",
        "governance-consolidation-tests",
        "enforce_all_rules_objective_audit",
    ):
        if required not in check_ids:
            errors.append(f"CHECK_STACK_INVENTORY.json: missing inventory row for {required!r}")

    builder = REPO / "tools" / "build_check_stack_inventory.py"
    if not builder.is_file():
        errors.append("tools/build_check_stack_inventory.py: missing")

    if AGENTS_MD.is_file():
        agents = AGENTS_MD.read_text(encoding="utf-8", errors="replace")
        if "CHECK_STACK_INVENTORY.json" not in agents and "check_check_stack_rightsizing" not in agents:
            errors.append("AGENTS.md: missing check stack right-sizing markers")
    return errors


def main() -> int:
    errs = check_check_stack_rightsizing()
    if errs:
        print("check_check_stack_rightsizing: FAIL\n- " + "\n- ".join(errs))
        return 1
    print("check_check_stack_rightsizing: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
