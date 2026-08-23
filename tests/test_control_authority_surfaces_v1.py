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
        "/tools/install_pm_authority_host.sh",
        "/tools/__init__.py",
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


def test_tools_package_init_is_a_control_authority_surface():
    """tools/__init__.py runs inside the guard process on every `import tools.*`;
    an assigned AI must not be able to plant a monkeypatch there to neuter the rail."""
    assert WDL.is_control_authority_surface("tools/__init__.py")
    assert WDL.control_authority_violation("tools/__init__.py", agent="claude")
    assert WDL.control_authority_violation("tools/__init__.py", agent="cursor")


_HOOK_ENTRYPOINTS = (
    "tools/pretooluse_guard.py", "tools/process_lock_guard.py",
    "tools/stop_guard.py", "tools/proof_only_guard.py",
    "tools/honesty_guard.py", "tools/operator_law_guard.py",
)


def _precommit_entrypoints():
    """tools/*.py referenced as pre-commit hook `entry:` commands — these run in the
    git commit process and decide gate exit codes."""
    cfg = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    import re
    eps = set()
    for m in re.finditer(r"(tools/[A-Za-z0-9_./-]+\.py)", cfg):
        rel = m.group(1)
        if (ROOT / rel).is_file():
            eps.add(rel)
    return eps


def _import_closure(entrypoints):
    """Every repo .py the given entrypoints import transitively — each executes
    inside that enforcement process, so each is a code-injection surface."""
    import os

    def repo_mod(mod):
        p = ROOT / (mod.replace(".", "/") + ".py")
        return p if p.is_file() else None

    seen, stack, closure = set(), list(entrypoints), set()
    while stack:
        rel = stack.pop()
        if rel in seen:
            continue
        seen.add(rel)
        full = ROOT / rel
        if not full.is_file():
            continue
        closure.add(rel)
        tree = ast.parse(full.read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and not (n.level or 0):
                mods.add(n.module)
        for m in mods:
            p = repo_mod(m)
            if p:
                r = os.path.relpath(p, ROOT).replace("\\", "/")
                if r not in seen:
                    stack.append(r)
    return closure


def _codeowners_covers(rel, owners_text):
    import fnmatch
    for line in owners_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pat = line.split()[0].lstrip("/")
        if pat.endswith("/") and rel.startswith(pat):
            return True
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def test_enforcement_execution_closure_is_codeowned_and_hooks_railed():
    """Self-maintaining DURABLE boundary (merge review).

    Every repo module executed inside an enforcement process — the PreToolUse/Stop
    hooks AND the pre-commit hook wrappers — is a code-injection surface: a poisoned
    module runs with the enforcer's privileges and, if merged, poisons production
    enforcement. The DURABLE boundary against that is operator review at merge
    (CODEOWNERS + branch protection), so EVERY member of the combined execution
    closure must be CODEOWNERS-covered. If a guard/wrapper gains a new repo import
    without coverage, this test FAILS — the class cannot silently reopen.

    NOTE ON THE IN-PROCESS RAIL: control_authority_violation blocking the Edit/Write
    tools is DEFENSE-IN-DEPTH, not the boundary — an assigned AI with shell access can
    rewrite any checkout file via cp/mv/sed/tee, which the in-process guards do not
    (and cannot exhaustively) intercept. The capability boundary is the OS PM-authority
    ownership + non-root AI + this merge review. We still assert the hook closure is
    railed (raises the local bar) but the authoritative assertion is CODEOWNERS."""
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    hook_closure = _import_closure(_HOOK_ENTRYPOINTS)
    precommit_closure = _import_closure(_precommit_entrypoints())
    execution_closure = hook_closure | precommit_closure
    assert len(execution_closure) >= 25, execution_closure  # sanity: actually computed

    # DURABLE boundary: the entire execution closure must require operator review to merge.
    not_owned = sorted(m for m in execution_closure if not _codeowners_covers(m, owners))
    assert not_owned == [], f"enforcement-execution modules NOT CODEOWNERS-covered: {not_owned}"

    # Every conftest under tests/ runs at collection and can fake the suite green.
    conftests = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.glob("tests/**/conftest.py")]
    conftests_uncovered = sorted(c for c in conftests if not _codeowners_covers(c, owners))
    assert conftests_uncovered == [], f"conftest execution surfaces NOT CODEOWNERS-covered: {conftests_uncovered}"

    # Defense-in-depth: the PreToolUse/Stop hook closure is also blocked from the
    # Edit/Write file tools (raises the local bar; not the boundary — see docstring).
    not_railed = sorted(m for m in hook_closure if not WDL.is_control_authority_surface(m))
    assert not_railed == [], f"hook-closure modules NOT railed (defense-in-depth gap): {not_railed}"


def test_tools_package_init_has_no_executable_code():
    """Defense-in-depth: even if a poisoned __init__ reached CI, pin it to
    comments/docstring/__future__ only — no import, call, assignment, or def that
    could monkeypatch a guard at hook import time."""
    src = (ROOT / "tools" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        raise AssertionError(
            f"tools/__init__.py must contain no executable code; found "
            f"{type(node).__name__} at line {getattr(node, 'lineno', '?')}"
        )
