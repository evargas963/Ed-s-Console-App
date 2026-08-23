# institutional-synthetic-ok: mutate leftover assignment JSON and rails to prove
# Architecture A rejects vendor privilege and control-authority rewrite (RC-454).
"""Control-authority surfaces — operator-selected work, no vendor privilege."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.writer_drift_lock as WDL  # noqa: E402

_MISSION = {
    "status": "active",
    "writer": "claude",
    "pm": "operator",
    "auditor": "cursor",
    "mission_id": "auth-v1",
    "scope_paths": ["server.py", "tools/", "tests/"],
}
_SOLE = {"writer": "claude", "pm": "operator", "auditor": "cursor"}


def test_ordinary_product_is_not_vendor_gated():
    for agent in ("claude", "cursor", "codex", "gpt"):
        assert WDL.writer_drift_violations(
            ["server.py"], agent=agent, mission=_MISSION, sole_writer=_SOLE
        ) == [], agent


def test_switch_working_ai_without_changing_policy_code():
    """Changing ED_AGENT_ROLE is the switch; lock source is not edited."""
    src_before = (ROOT / "tools" / "writer_drift_lock.py").read_bytes()
    for agent in ("claude", "cursor", "gpt", "codex"):
        assert WDL.writer_drift_violations(
            ["server.py"], agent=agent, mission=_MISSION, sole_writer=_SOLE
        ) == [], agent
        assert WDL.control_authority_violation(
            "tools/writer_drift_lock.py", agent=agent
        )
    assert (ROOT / "tools" / "writer_drift_lock.py").read_bytes() == src_before


def test_writer_field_flip_is_not_authorization():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    new = json.dumps({"writer": "codex", "pm": "operator", "auditor": "cursor", "note": "n"})
    for agent in ("claude", "cursor", "codex", "gpt"):
        v = WDL.pm_status_field_violations(
            "governance/sole_writer.json", new, agent=agent, current_text=cur
        )
        assert v == [], f"{agent} writer-field flip must not be an authorization decision"
        assert WDL.control_authority_violation(".github/CODEOWNERS", agent=agent)


def test_operator_unassigned_may_edit_leftover_assignment_json():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    new = json.dumps({"writer": "codex", "pm": "operator", "auditor": "cursor", "note": "n"})
    assert WDL.pm_status_field_violations(
        "governance/sole_writer.json", new, agent="", current_text=cur
    ) == []
    steal = json.dumps({"writer": "claude", "pm": "cursor", "auditor": "cursor", "note": "n"})
    assert WDL.pm_status_field_violations(
        "governance/sole_writer.json", steal, agent="", current_text=cur
    ) == []


def test_assigned_agent_cannot_reassign_pm():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    steal = json.dumps({"writer": "claude", "pm": "cursor", "auditor": "cursor", "note": "n"})
    for agent in ("claude", "cursor", "codex", "gpt"):
        from tools.pm_authority import validate_pm_authority_document
        v = validate_pm_authority_document(steal, current_text=cur)
        assert v and any("pm=" in m and "operator" in m for m in v), agent
        assert WDL.pm_status_field_violations(
            "governance/pm_mission.json", steal, agent=agent, current_text=cur
        ) == []


def test_writer_cannot_redefine_lock_or_hooks():
    for rel in (
        "tools/writer_drift_lock.py",
        "tools/operator_law_guard.py",
        ".cursor/hooks.json",
        ".github/workflows/hardening.yml",
        "tests/test_architecture_a_bypass_class_v1.py",
        "tests/test_architecture_a_operator_writer_authority_v1.py",
        "tools/pm_authority.py",
        "tests/test_pm_authority_external_v1.py",
    ):
        msgs = WDL.writer_drift_violations(
            [rel], agent="claude", mission=_MISSION, sole_writer=_SOLE
        )
        assert msgs and any("control-authority" in m for m in msgs), rel


def test_empty_role_abstains_on_product_paths():
    assert WDL.writer_drift_violations(
        ["server.py"], agent="", mission=_MISSION, sole_writer=_SOLE
    ) == []


def test_codeowners_covers_control_authority_set():
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    required = (
        "/.github/workflows/",
        "/.github/CODEOWNERS",
        "/.cursor/hooks.json",
        "/.claude/settings.json",
        "/tools/*_guard.py",
        "/tools/*_lock.py",
        "/tools/check_institutional_correctness.py",
        "/governance/operator_go.json",
        "/tests/test_architecture_a_bypass_class_v1.py",
        "/tests/test_control_authority_surfaces_v1.py",
        "/tests/test_architecture_a_operator_writer_authority_v1.py",
        "/tests/test_pm_authority_external_v1.py",
        "/tools/pm_authority.py",
        "/tools/pm_authority_helper.py",
    )
    missing = [p for p in required if p not in owners]
    assert missing == [], missing
    for banned in ("/server.py", "/signals.py", "/static/"):
        assert banned not in owners, banned


def test_mutation_vendor_default_role_is_detected():
    src = (ROOT / "tools" / "writer_drift_lock.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "current_agent_role":
            dumped = ast.dump(node)
            assert "cursor" not in dumped and "claude" not in dumped, (
                "current_agent_role still hard-codes a vendor principal"
            )
        if isinstance(node, ast.FunctionDef) and node.name == "writer_drift_violations":
            dumped = ast.dump(node)
            assert "resolved_writer" not in dumped
            assert "is sole writer" not in dumped


def test_mutation_enforcement_allowlist_is_gone():
    src = (ROOT / "tools" / "writer_drift_lock.py").read_text(encoding="utf-8")
    assert "is_enforcement_surface" not in src
    assert "HARD_DENYLIST_EXACT" not in src
    assert "HARD_DENYLIST_TEST_MARKERS" not in src
    assert "def resolved_writer" not in src
    assert "if agent != \"cursor\"" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "is_pm_allowlisted":
            dumped = ast.dump(node)
            assert "is_enforcement_surface" not in dumped
            assert "is_control_authority_surface" in dumped


@pytest.mark.parametrize("agent", ["cursor", "claude", "codex"])
def test_self_grant_does_not_unlock_rails(agent):
    cur = json.dumps({"writer": "other", "pm": "operator", "auditor": "cursor"})
    new = json.dumps({"writer": agent, "pm": "operator", "auditor": "cursor"})
    v = WDL.pm_status_field_violations(
        "governance/sole_writer.json", new, agent=agent, current_text=cur
    )
    assert v == []
    assert WDL.control_authority_violation("tools/writer_drift_lock.py", agent=agent)
    assert WDL.control_authority_violation(".github/workflows/pytest.yml", agent=agent)
