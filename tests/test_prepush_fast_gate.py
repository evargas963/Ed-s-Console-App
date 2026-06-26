"""Tests for pre-push fast-fail gate."""
from __future__ import annotations

import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_prepush_fast_gate import (  # noqa: E402
    EXPECTED_PREPUSH_HOOK_ORDER,
    PREPUSH_LOCAL_BUDGET_HARD_SEC,
    PREPUSH_LOCAL_BUDGET_TARGET_SEC,
    check_prepush_fast_gate_policy,
    check_prepush_hook_order,
    check_prepush_lightweight_only,
    check_required_ci_backing,
    check_working_tree_clean_for_push,
)


def test_prepush_hook_order_matches_policy():
    errs = check_prepush_hook_order()
    assert errs == [], errs


def test_expected_order_constant_matches_audit():
    audit = (REPO / "governance/artifacts/PREPUSH_FAST_FAIL_AUDIT.json").read_text(encoding="utf-8")
    for hook_id in EXPECTED_PREPUSH_HOOK_ORDER:
        assert hook_id in audit


def test_expected_order_is_lightweight_two_gates_only():
    # Phase 2B: local pre-push is the two fast gates only — no repo-wide pytest hook.
    assert EXPECTED_PREPUSH_HOOK_ORDER == (
        "prepush-fast-gate",
        "generated-artifacts-clean-check",
    )


def test_consolidation_pytest_not_on_local_prepush():
    # The repo-wide consolidation pytest suite must NOT be a local pre-push hook.
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    idx = cfg.find("id: governance-consolidation-tests")
    assert idx == -1, "governance-consolidation-tests must not be a hook (required CI owns it)"
    errs = check_prepush_lightweight_only()
    assert errs == [], errs


def test_required_ci_backs_moved_coverage():
    errs = check_required_ci_backing()
    assert errs == [], errs


def test_prepush_local_budget_bounds():
    assert PREPUSH_LOCAL_BUDGET_TARGET_SEC <= PREPUSH_LOCAL_BUDGET_HARD_SEC
    assert PREPUSH_LOCAL_BUDGET_HARD_SEC <= 60.0
    assert PREPUSH_LOCAL_BUDGET_TARGET_SEC <= 30.0


def test_prepush_fast_gate_policy_passes_on_current_repo():
    errs = check_prepush_fast_gate_policy()
    assert errs == [], errs


def test_dirty_tree_fails_fast(monkeypatch):
    monkeypatch.setattr(
        "tools.check_prepush_fast_gate.subprocess.run",
        lambda *a, **k: type("P", (), {"returncode": 1, "stdout": " M foo.py", "stderr": ""})(),
    )
    start = time.perf_counter()
    errs = check_working_tree_clean_for_push()
    elapsed = time.perf_counter() - start
    assert errs
    assert elapsed < 5.0
    assert any("dirty" in e.lower() for e in errs)


def test_clean_tree_passes_fast_gate(monkeypatch):
    monkeypatch.setattr(
        "tools.check_prepush_fast_gate.subprocess.run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    start = time.perf_counter()
    errs = check_working_tree_clean_for_push()
    elapsed = time.perf_counter() - start
    assert errs == []
    assert elapsed < 5.0


def test_fast_gates_present_and_ordered_in_yaml():
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    idx_fast = cfg.find("id: prepush-fast-gate")
    idx_artifacts = cfg.find("id: generated-artifacts-clean-check")
    idx_static = cfg.find("id: fix-everything-we-touch-full-static")
    assert -1 not in (idx_fast, idx_artifacts)
    assert idx_static < 0, "fix-everything-we-touch-full-static must not be on pre-push"
    # Lightweight-only: the repo-wide consolidation pytest hook is gone (required CI owns it).
    assert cfg.find("id: governance-consolidation-tests") < 0
    assert idx_fast < idx_artifacts
