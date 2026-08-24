"""Guard bypass class — mandatory controls are not subject-disableable (RC-450/RC-454).

Carried forward from the Architecture A battery when the role/authority machinery was
torn down (operator, 2026-08-24): the ROLES are gone, but the property that an acting
agent cannot switch off its own guards is not role machinery — it is what makes the
remaining small guard surface real. These tests attempt the prohibited action and
require the real boundary to reject it; a function-exists assertion is not enough.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operator_law_guard as G  # noqa: E402

#: Guards whose blocking behaviour must not carry an ED_* env off-switch.
_MATERIAL_GUARD_FILES = (
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "tools/pretooluse_guard.py",
    "tools/stop_guard.py",
    "tools/proof_only_guard.py",
    "tools/honesty_guard.py",
    "tools/operator_law_guard.py",
    "tools/pm_verify_lock.py",
    "tools/ui_mockup_lock.py",
)


def _disable_if(test: ast.AST) -> bool:
    """True when a test reads ED_*_GUARD/LOCK and compares it to off/0/false."""
    src = ast.dump(test)
    if "ED_" not in src:
        return False
    if "_GUARD" not in src and "_LOCK" not in src:
        return False
    return any(tok in src for tok in ('"off"', "'off'", '"false"', "'false'", '"0"', "'0'"))


def _body_disables(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                return True
            if isinstance(stmt.value, ast.Constant) and stmt.value.value in (0, False, None, ""):
                return True
            if isinstance(stmt.value, (ast.List, ast.Tuple)) and not stmt.value.elts:
                return True
    return False


def test_git_commit_no_verify_blocks():
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in out), out


def test_git_commit_dash_n_blocks():
    out = G.bash_violations("git commit -n -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in out), out


def test_hooks_path_bypass_blocks():
    out = G.bash_violations(
        "git -c core.hooksPath=/dev/null commit -m x", [], payload_cwd=str(ROOT)
    )
    assert any("disables a mechanical lock" in v for v in out), out


def test_no_grant_machinery_can_authorize_no_verify():
    """The operator-grants file is GONE with Architecture A; no repo artifact may
    resurrect a no-verify authorization path inside the guard."""
    src = (ROOT / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert "_no_verify_grant_covers" not in src
    assert "operator_grants.json" not in src
    assert not (ROOT / "governance" / "operator_grants.json").exists()
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in out), out


def test_hook_entrypoint_rejects_no_verify_with_guard_env_off(monkeypatch):
    """Attempt the real hook process, not a helper-exists check."""
    monkeypatch.setenv("ED_OPERATOR_LAW_GUARD", "off")
    payload = json.dumps({
        "session_id": "bypass-class",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit --no-verify -m x"},
        "cwd": str(ROOT),
    })
    p = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "operator_law_guard.py")],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        check=False,
    )
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "disables a mechanical lock" in p.stderr


def test_required_ci_does_not_honor_guard_env():
    hardening = (ROOT / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    pytest_ci = (ROOT / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    for src, name in ((hardening, "hardening.yml"), (pytest_ci, "pytest.yml")):
        assert "ED_OPERATOR_LAW_GUARD=off" not in src, name
        assert "commit --no-verify" not in src, name
    assert "pytest-full" in pytest_ci
    assert "hardening" in hardening


def test_material_guards_have_no_env_off_early_return():
    for rel in _MATERIAL_GUARD_FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not _disable_if(node.test):
                continue
            assert not _body_disables(node.body), (
                f"{rel}:{node.lineno} still subject-disables a mandatory control"
            )
