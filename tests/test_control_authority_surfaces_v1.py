# institutional-synthetic-ok: mutate vendor-hardcodes and allowlist grants to prove
# Architecture A rejects the known-bad control-authority class (RC-453).
"""Control-authority surfaces — vendor-agnostic assignment and CODEOWNERS coverage."""
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


def test_assignment_is_vendor_agnostic_codex_writer():
    mission = {**_MISSION, "writer": "codex"}
    sole = {**_SOLE, "writer": "codex"}
    assert WDL.writer_drift_violations(
        ["server.py"], agent="codex", mission=mission, sole_writer=sole
    ) == []
    blocked = WDL.writer_drift_violations(
        ["server.py"], agent="cursor", mission=mission, sole_writer=sole
    )
    assert blocked and any("SOD_DRIFT" in m for m in blocked)


def test_switch_writer_without_changing_policy_code():
    """Operator-selected writer works; previous writer loses the assignment."""
    before = WDL.writer_drift_violations(
        ["server.py"], agent="claude", mission=_MISSION, sole_writer=_SOLE
    )
    assert before == []
    after_mission = {**_MISSION, "writer": "gpt"}
    after_sole = {**_SOLE, "writer": "gpt"}
    assert WDL.writer_drift_violations(
        ["server.py"], agent="gpt", mission=after_mission, sole_writer=after_sole
    ) == []
    lost = WDL.writer_drift_violations(
        ["server.py"], agent="claude", mission=after_mission, sole_writer=after_sole
    )
    assert lost and any("gpt is sole writer" in m for m in lost)


def test_any_agent_cannot_reassign_writer():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    new = json.dumps({"writer": "codex", "pm": "operator", "auditor": "cursor", "note": "n"})
    for agent in ("claude", "cursor", "codex", "gpt"):
        v = WDL.pm_status_field_violations(
            "governance/sole_writer.json", new, agent=agent, current_text=cur
        )
        assert v, f"{agent} reassigned writer without BLOCK"


def test_operator_unassigned_may_switch_writer():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    new = json.dumps({"writer": "codex", "pm": "operator", "auditor": "cursor", "note": "n"})
    assert WDL.pm_status_field_violations(
        "governance/sole_writer.json", new, agent="", current_text=cur
    ) == []


def test_writer_cannot_redefine_lock_or_hooks():
    for rel in (
        "tools/writer_drift_lock.py",
        "tools/operator_law_guard.py",
        ".cursor/hooks.json",
        ".github/workflows/hardening.yml",
        "tests/test_architecture_a_bypass_class_v1.py",
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
    )
    missing = [p for p in required if p not in owners]
    assert missing == [], missing
    # Routine product must not be listed — that would make the operator a bottleneck.
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


def test_mutation_enforcement_allowlist_is_gone():
    src = (ROOT / "tools" / "writer_drift_lock.py").read_text(encoding="utf-8")
    assert "is_enforcement_surface" not in src
    assert "if agent != \"cursor\"" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "is_pm_allowlisted":
            dumped = ast.dump(node)
            assert "is_enforcement_surface" not in dumped
            assert "is_control_authority_surface" in dumped


@pytest.mark.parametrize("agent", ["cursor", "claude", "codex"])
def test_self_grant_blocked_for_any_principal(agent):
    cur = json.dumps({"writer": "other", "pm": "operator", "auditor": "cursor"})
    new = json.dumps({"writer": agent, "pm": "operator", "auditor": "cursor"})
    v = WDL.pm_status_field_violations(
        "governance/sole_writer.json", new, agent=agent, current_text=cur
    )
    assert v and any("cannot authorize itself as writer" in m or "writer" in m for m in v)
