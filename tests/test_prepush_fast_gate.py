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
    check_consolidation_entry_check_only,
    check_prepush_fast_gate_policy,
    check_prepush_hook_order,
    check_working_tree_clean_for_push,
)


def test_prepush_hook_order_matches_policy():
    errs = check_prepush_hook_order()
    assert errs == [], errs


def test_expected_order_constant_matches_audit():
    audit = (REPO / "governance/artifacts/PREPUSH_FAST_FAIL_AUDIT.json").read_text(encoding="utf-8")
    for hook_id in EXPECTED_PREPUSH_HOOK_ORDER:
        assert hook_id in audit


def test_consolidation_entry_is_check_only_pytest():
    errs = check_consolidation_entry_check_only()
    assert errs == [], errs


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


def test_governance_consolidation_runs_after_fast_gates_in_yaml():
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    idx_fast = cfg.find("id: prepush-fast-gate")
    idx_artifacts = cfg.find("id: generated-artifacts-clean-check")
    idx_static = cfg.find("id: fix-everything-we-touch-full-static")
    idx_consolidation = cfg.find("id: governance-consolidation-tests")
    assert -1 not in (idx_fast, idx_artifacts, idx_static, idx_consolidation)
    assert idx_fast < idx_artifacts < idx_static < idx_consolidation
