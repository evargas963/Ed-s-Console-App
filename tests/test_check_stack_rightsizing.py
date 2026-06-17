"""Tests for Phase 3I check stack right-sizing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_check_stack_rightsizing import check_check_stack_rightsizing  # noqa: E402


def test_check_stack_rightsizing_passes_on_current_repo():
    errs = check_check_stack_rightsizing()
    assert errs == [], errs


def test_inventory_records_prepush_over_budget():
    inv = json.loads(
        (REPO / "governance/artifacts/CHECK_STACK_INVENTORY.json").read_text(encoding="utf-8")
    )
    over = inv.get("over_budget") or []
    prepush = [r for r in over if r.get("path") == "pre-push"]
    assert prepush, "pre-push over budget must be recorded"
    assert prepush[0].get("documented_reason")


def test_ablation_checks_in_inventory_with_profile_times():
    inv = json.loads(
        (REPO / "governance/artifacts/CHECK_STACK_INVENTORY.json").read_text(encoding="utf-8")
    )
    by_id = {c["check_id"]: c for c in inv.get("checks") or []}
    assert "check_ablation_seven_model_four_horizon_grid" in by_id
    assert "check_ablation_equal_layer_consumers" in by_id
    assert by_id["check_ablation_equal_layer_consumers"].get("can_be_cached") is True


def test_duplication_analysis_is_list():
    inv = json.loads(
        (REPO / "governance/artifacts/CHECK_STACK_INVENTORY.json").read_text(encoding="utf-8")
    )
    assert isinstance(inv.get("duplication_analysis"), list)


def test_runtime_budget_targets_present():
    inv = json.loads(
        (REPO / "governance/artifacts/CHECK_STACK_INVENTORY.json").read_text(encoding="utf-8")
    )
    budgets = inv.get("runtime_budgets_seconds") or {}
    assert budgets.get("prepush_governance") == 1200
