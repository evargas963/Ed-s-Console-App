"""Pre-commit performance audit — tier policy + artifact contract."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_security_by_design_control_title_allowed():
    from governance.forbidden_phrases import find_by_design_excuses, find_forbidden_phrases

    line = '("T1-09", "Security by design"),'
    assert find_by_design_excuses(line) == []
    assert find_forbidden_phrases(line) == []


def test_working_by_design_excuse_blocked():
    from governance.forbidden_phrases import find_by_design_excuses, find_forbidden_phrases

    line = "this is working by design and we ship anyway."
    assert "by design" in find_by_design_excuses(line)
    assert "by design" in find_forbidden_phrases(line)


def test_left_incomplete_by_design_blocked():
    from governance.forbidden_phrases import find_by_design_excuses

    line = "left incomplete by design for this slice."
    assert "by design" in find_by_design_excuses(line)


def test_works_as_designed_blocked():
    from governance.forbidden_phrases import find_by_design_excuses, find_forbidden_phrases

    line = "The gate works as designed so we skip the fix."
    assert "works as designed" in find_by_design_excuses(line)
    assert "works as designed" in find_forbidden_phrases(line)


def test_staged_builder_line_passes_rule_drift():
    import sys

    tools = REPO / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import check_fix_everything_we_touch as mod

    line = '        ("T1-09", "Security by design"),'
    hits = mod._line_rule_drift_hits(REPO / "tools/_build_governance_coverage_matrix.py", 55, line)
    assert hits == []


def test_precommit_performance_artifact_exists():
    p = REPO / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"
    assert p.is_file(), "run: python tools/audit_precommit_performance.py --write"
    import json

    audit = json.loads(p.read_text(encoding="utf-8"))
    assert audit.get("schema_version") == 1
    hooks = {h["id"]: h for h in audit.get("hooks") or []}
    # Phase 2B: the repo-wide consolidation pytest suite is required-CI-owned, not a hook.
    assert "governance-consolidation-tests" not in hooks
    assert "fix-everything-we-touch-full-static" not in hooks
    ci_backed = audit.get("ci_backed_suites") or {}
    gct = ci_backed.get("governance-consolidation-tests")
    assert gct, "ci_backed_suites must record governance-consolidation-tests"
    assert gct.get("required_ci_check") == "pytest-full"
    assert audit.get("local_prepush_mode") == "lightweight_only"
    assert audit.get("local_prepush_budget_hard_seconds") <= 60.0


def test_governance_consolidation_not_a_local_hook():
    # Phase 2B: the repo-wide consolidation pytest suite must not be any local hook.
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert cfg.find("id: governance-consolidation-tests") == -1


def test_precommit_performance_contract_checker():
    import sys

    tools = REPO / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import check_fix_everything_we_touch as mod

    assert mod.check_precommit_performance_contract() == []
