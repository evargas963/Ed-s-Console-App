# institutional-synthetic-ok: inject leftover writer metadata + env/grant payloads to prove
# Architecture A rejects the actual prohibited bypass actions (RC-450 / RC-454).
"""Architecture A — mandatory controls are not subject-disableable.

These tests attempt the prohibited action and require the real boundary to reject it.
A function-exists assertion is not enough.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operator_law_guard as G  # noqa: E402
import tools.writer_drift_lock as WDL  # noqa: E402

_MISSION = {
    "status": "active",
    "writer": "claude",
    "pm": "operator",
    "auditor": "cursor",
    "mission_id": "arch-a-neg-v1",
    "scope_paths": ["static/chart.html", "server.py", "tools/", "tests/"],
}
_SOLE = {"writer": "claude", "pm": "operator", "auditor": "cursor"}

_MATERIAL_GUARD_FILES = (
    "tools/writer_drift_lock.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "tools/pretooluse_guard.py",
    "tools/stop_guard.py",
    "tools/proof_only_guard.py",
    "tools/honesty_guard.py",
    "tools/operator_law_guard.py",
    "tools/rc_resolve_lock.py",
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


def test_stale_writer_cannot_block_operator_selected_product_work():
    msgs = WDL.writer_drift_violations(
        ["server.py"], agent="cursor", mission=_MISSION, sole_writer=_SOLE
    )
    assert msgs == []


@pytest.mark.parametrize("value", ["off", "0", "false", "OFF", "False", " off ", "FALSE"])
def test_writer_drift_env_disable_still_blocks_rails(value, monkeypatch):
    monkeypatch.setenv("ED_WRITER_DRIFT_GUARD", value)
    msgs = WDL.writer_drift_violations(
        ["tools/writer_drift_lock.py"], agent="cursor", mission=_MISSION, sole_writer=_SOLE
    )
    assert msgs, f"ED_WRITER_DRIFT_GUARD={value!r} disabled the control"


def test_assigned_writer_cannot_rewrite_the_writer_guard():
    msgs = WDL.writer_drift_violations(
        ["tools/writer_drift_lock.py"], agent="claude", mission=_MISSION, sole_writer=_SOLE
    )
    assert msgs and any("control-authority" in m for m in msgs)


def test_assigned_writer_works_without_disabling_any_guard(monkeypatch):
    monkeypatch.delenv("ED_WRITER_DRIFT_GUARD", raising=False)
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    for agent in ("claude", "cursor"):
        msgs = WDL.writer_drift_violations(
            ["server.py"], agent=agent, mission=_MISSION, sole_writer=_SOLE
        )
        assert msgs == [], agent


def test_self_set_writer_does_not_unlock_rails():
    cur = json.dumps({"writer": "claude", "pm": "operator", "auditor": "cursor", "note": "n"})
    new = json.dumps({
        "writer": "cursor",
        "pm": "operator",
        "auditor": "cursor",
        "note": "# sod-role-ok: I assign myself",
    })
    v = WDL.pm_status_field_violations(
        "governance/sole_writer.json", new, agent="cursor", current_text=cur
    )
    assert v == []
    assert WDL.control_authority_violation("tools/writer_drift_lock.py", agent="cursor")


def test_cursor_edit_ok_json_cannot_authorize_rails_rewrite():
    msgs = WDL.writer_drift_violations(
        ["server.py"],
        agent="cursor",
        mission=_MISSION,
        sole_writer={**_SOLE, "cursor_edit_ok": True},
    )
    assert msgs == []
    rails = WDL.writer_drift_violations(
        ["tools/writer_drift_lock.py"],
        agent="cursor",
        mission=_MISSION,
        sole_writer={**_SOLE, "cursor_edit_ok": True},
    )
    assert rails and any("control-authority" in m for m in rails)


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


def test_grant_file_cannot_authorize_no_verify():
    src = (ROOT / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert "_no_verify_grant_covers" not in src
    assert "git show HEAD:governance/operator_grants.json" not in src
    grants = json.loads((ROOT / "governance" / "operator_grants.json").read_text(encoding="utf-8"))
    assert grants.get("grants") == {}
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in out), out


def test_hook_entrypoint_rejects_no_verify_with_guard_env_off(monkeypatch):
    """Attempt the real hook process, not a helper-exists check."""
    monkeypatch.setenv("ED_OPERATOR_LAW_GUARD", "off")
    payload = json.dumps({
        "session_id": "arch-a",
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
        assert "ED_WRITER_DRIFT_GUARD" not in src, name
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
