# institutional-synthetic-ok: mutate leftover assignment JSON and rails to prove
# Architecture A rejects vendor privilege and control-authority rewrite (RC-454).
"""Control-authority surfaces — operator-selected work, no vendor privilege."""
from __future__ import annotations

import ast
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
    """RC-461: writer/auditor are coordination text, never authorization.

    An agent may rewrite them freely - and gains nothing, because the rail reads the
    OPERATOR-ASSIGNED principal, never a field the agent can type.
    """
    for agent in ("claude", "cursor", "codex", "gpt"):
        assert WDL.control_authority_violation(
            "governance/sole_writer.json", agent=agent) is None, agent
        assert WDL.control_authority_violation(".github/CODEOWNERS", agent=agent), agent


def test_operator_unassigned_may_edit_leftover_assignment_json():
    """Empty ED_AGENT_ROLE is the OPERATOR (or CI): no rail constrains them."""
    for rel in ("governance/sole_writer.json", "governance/pm_mission.json",
                ".github/CODEOWNERS", ".claude/settings.json",
                "tools/writer_drift_lock.py", "governance/operator_grants.json"):
        assert WDL.control_authority_violation(rel, agent="") is None, rel


def test_assigned_agent_cannot_reassign_pm():
    """RC-461: 'pm' in a repo JSON is INERT - writing pm=<self> grants nothing.

    Authority is not a value stored in the tree, so there is nothing to forge. It is the
    operator's assignment plus operator review at merge.
    """
    for agent in ("claude", "cursor", "codex", "gpt"):
        assert WDL.control_authority_violation(
            "governance/pm_mission.json", agent=agent) is None, agent
        for rel in (".github/CODEOWNERS", ".claude/settings.json",
                    "governance/operator_grants.json", "tools/writer_drift_lock.py"):
            assert WDL.control_authority_violation(rel, agent=agent), (agent, rel)


def test_writer_cannot_redefine_lock_or_hooks():
    for rel in (
        "tools/writer_drift_lock.py",
        "tools/operator_law_guard.py",
        ".cursor/hooks.json",
        ".github/workflows/hardening.yml",
        "tests/test_architecture_a_bypass_class_v1.py",
        "tests/test_architecture_a_operator_writer_authority_v1.py",
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
    """CODEOWNERS must own exactly the TRUE AUTHORITY files (RC-461).

    Authority = the files that decide WHO MAY DO WHAT: the review policy and required
    checks, the operator's AI assignment, the rail that enforces it, the operator grant
    rails, and the tests that prove those rules. Nothing else.
    """
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    required = (
        "/.github/CODEOWNERS",
        "/.github/workflows/",
        "/.claude/settings.json",
        "/.cursor/hooks.json",
        "/tools/writer_drift_lock.py",
        "/tools/process_lock_guard.py",
        "/tools/operating_process_lock.py",
        "/governance/operator_go.json",
        "/governance/operator_grants.json",
        "/tests/test_control_authority_surfaces_v1.py",
        "/tests/test_writer_drift_lock_v1.py",
        "/tests/test_architecture_a_bypass_class_v1.py",
        "/tests/test_architecture_a_operator_writer_authority_v1.py",
    )
    missing = [p for p in required if p not in owners]
    assert missing == [], missing
    # Ordinary product work stays autonomous - never operator-review-gated.
    for banned in ("/server.py", "/signals.py", "/static/", "/db.py"):
        assert banned not in owners, banned


def test_codeowners_is_minimal_no_defense_in_depth_padding():
    """The authority set must STAY minimal (RC-461).

    These are quality/process surfaces, not authority: owning them would make the
    operator a reviewer of ordinary engineering without closing an authority hole.
    The removed host-boundary files must never reappear either.
    """
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    owned = {
        line.strip().split()[0]
        for line in owners.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    must_not_be_owned = {
        "/tools/*_guard.py", "/tools/*_lock.py", "/tools/check_*.py",
        "/tools/__init__.py", "/time_et.py",
        "/tests/conftest.py", "/tests/**/conftest.py",
        "/.pre-commit-config.yaml",
        "/tools/run_with_repo_venv.py", "/tools/bootstrap_worktree_venv.py",
        "/tools/precommit_institutional.py",
        "/tools/check_institutional_correctness.py", "/tools/check_delta_adds_no_debt.py",
        # deleted host-boundary architecture - must not return
        "/tools/pm_authority.py", "/tools/pm_authority_helper.py",
        "/tools/install_pm_authority_host.sh", "/tools/install_pm_authority_host.ps1",
        "/tests/test_pm_authority_external_v1.py",
        "/tests/test_pm_authority_windows_boundary_v1.py",
    }
    regressed = sorted(owned & must_not_be_owned)
    assert regressed == [], f"non-authority padding in CODEOWNERS: {regressed}"


def test_removed_host_boundary_architecture_stays_removed():
    """RC-461: the OS sandbox / privileged helper / host provisioning is GONE.

    The operator ruled it overbuilt. If any of these files return, the simplification has
    silently regressed and the repo is carrying an authority story it does not need.
    """
    for rel in ("tools/pm_authority.py", "tools/pm_authority_helper.py",
                "tools/install_pm_authority_host.sh", "tools/install_pm_authority_host.ps1",
                "tests/test_pm_authority_external_v1.py",
                "tests/test_pm_authority_windows_boundary_v1.py",
                "reports/pm_authority_external_implementation.md"):
        assert not (ROOT / rel).exists(), f"removed host-boundary file is back: {rel}"
    # No production module may import the deleted reader.
    for mod in ("tools/operating_process_lock.py", "tools/writer_drift_lock.py",
                "tools/process_lock_guard.py", "tools/rehab_daily_scan.py"):
        assert "pm_authority" not in (ROOT / mod).read_text(encoding="utf-8"), mod


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
        if isinstance(node, ast.FunctionDef) and node.name == "control_authority_violation":
            dumped = ast.dump(node)
            # RC-462: the decision must rest on the ACTING PRINCIPAL and the path, never
            # on a role/writer/auditor field that an agent could type into a file.
            assert "is_control_authority_surface" in dumped
            for role_field in ("writer", "auditor", "sole_writer", "scope_paths"):
                assert role_field not in dumped, role_field


@pytest.mark.parametrize("agent", ["cursor", "claude", "codex"])
def test_self_grant_does_not_unlock_rails(agent):
    """Naming yourself writer unlocks nothing (RC-461)."""
    assert WDL.control_authority_violation(
        "governance/sole_writer.json", agent=agent) is None
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

#: The BLOCKING gate scripts the required `hardening` workflow invokes. Their import
#: closure is DURABLE: the delta gate detects a REMOVED enforced check, but a check whose
#: detection LOGIC is silently weakened keeps its name and reports <= base, so a weakened
#: gate merges CI-green. Operator review at merge is the only control that sees it.
_CI_GATE_SCRIPTS = (
    "tools/check_delta_adds_no_debt.py",
    "tools/check_institutional_correctness.py",
    "tools/check_market_correctness.py",
    "tools/check_institutional_closure_gate.py",
    "tools/check_no_grep_subprocess.py",
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


def test_authority_files_are_both_railed_and_codeowned():
    """RC-461: every authority file is protected TWICE, and product is protected neither.

    CODEOWNERS + branch protection is the DURABLE boundary (operator approval at merge).
    The in-process control-authority rail is defense-in-depth (it denies the edit locally).
    An authority file missing from either side is a hole; an ordinary product file present
    on either side is a tax on autonomous work.
    """
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    authority = [
        ".github/CODEOWNERS",
        ".github/workflows/pytest.yml",
        ".github/workflows/hardening.yml",
        ".claude/settings.json",
        ".cursor/hooks.json",
        "tools/writer_drift_lock.py",
        "tools/process_lock_guard.py",
        "tools/operating_process_lock.py",
        "governance/operator_go.json",
        "governance/operator_grants.json",
    ]
    for rel in authority:
        assert _codeowners_covers(rel, owners), f"authority file NOT codeowned: {rel}"
        assert WDL.is_control_authority_surface(rel), f"authority file NOT railed: {rel}"
    for rel in ("server.py", "db.py", "signals.py", "static/index.html",
                "math_levels.py", "tests/test_ml_feature_provenance.py"):
        assert not _codeowners_covers(rel, owners), f"product file is codeowned: {rel}"
        assert not WDL.is_control_authority_surface(rel), f"product file is railed: {rel}"


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
