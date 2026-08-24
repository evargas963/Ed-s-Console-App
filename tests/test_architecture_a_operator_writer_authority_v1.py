# institutional-synthetic-ok: drive the live PreToolUse seam against a temporary
# stale-writer fixture to prove RC-454 operator-writer authority.
"""Architecture A — operator selects the working AI; rails stay denied.

These tests exercise process_lock_guard.pretooluse_block, not a constructed
authorization dictionary. Stale writer=claude is a synthetic leftover-writer
fixture, not live production metadata.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402
import tools.writer_drift_lock as WDL  # noqa: E402

_PRODUCT = ("server.py", "db.py", "static/chart.html")
_RAILS = (
    "tools/writer_drift_lock.py",
    ".github/CODEOWNERS",
    ".github/workflows/hardening.yml",
    "tests/test_architecture_a_operator_writer_authority_v1.py",
)
_AGENTS = ("claude", "cursor", "codex", "gpt")


def _stale_writer_fixture() -> dict:
    """Temporary leftover assignment. Must not exist on live pm_mission.json."""
    return {
        "status": "active",
        "writer": "claude",
        "pm": "operator",
        "auditor": "cursor",
        "mission_id": "rc454-stale-writer-fixture",
        "scope_paths": ["*"],
    }


def _pin_mission(monkeypatch, tmp_path, mission: dict | None = None) -> None:
    path = tmp_path / "pm_mission.json"
    path.write_text(json.dumps(mission or _stale_writer_fixture()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", path)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", path)


def _writer_veto(messages: list[str]) -> list[str]:
    needles = ("sole writer", "WRITER-DRIFT", "is sole writer")
    return [m for m in messages if any(n in m for n in needles)]


@pytest.mark.parametrize("agent", list(_AGENTS))
def test_ordinary_product_not_intrinsically_vendor_only(agent, monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", agent)
    for rel in _PRODUCT:
        assert WDL.hard_denylist_violation(rel, agent=agent) is None, rel
        bad = PLG.pretooluse_block("Edit", {"file_path": str(ROOT / rel)})
        assert not _writer_veto(bad), (agent, rel, bad)
        assert not any("control-authority" in b for b in bad), (agent, rel, bad)


@pytest.mark.parametrize("agent", list(_AGENTS))
def test_stale_writer_fixture_cannot_veto_operator_selected_work(agent, monkeypatch, tmp_path):
    """Temporary writer=claude must not veto Cursor/Claude/Codex/GPT ordinary work."""
    live = json.loads((ROOT / "governance" / "pm_mission.json").read_text(encoding="utf-8"))
    assert "writer" not in live and "auditor" not in live, (
        "live pm_mission.json still carries writer/auditor — that is stale production "
        "metadata, not a test fixture"
    )
    assert live.get("pm") == "operator"
    fixture = _stale_writer_fixture()
    assert fixture["writer"] == "claude"
    _pin_mission(monkeypatch, tmp_path, fixture)
    monkeypatch.setenv("ED_AGENT_ROLE", agent)
    for rel in ("server.py", "db.py"):
        bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / rel), "content": "x"})
        assert not _writer_veto(bad), (agent, rel, bad)


@pytest.mark.parametrize("agent", list(_AGENTS))
def test_assigned_ai_cannot_self_promote_or_self_authorize(agent, monkeypatch, tmp_path):
    """RC-461: the AI cannot make itself operator, nor grant itself authority.

    There is no executable authority document to forge any more. Self-promotion now
    reduces to editing the files that DECLARE the assignment or define the rules - and
    every one of those is denied to an assigned principal in-process, and needs operator
    review to merge (CODEOWNERS + branch protection).
    """
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", agent)

    # (a) Writing a self-serving claim into coordination metadata grants NOTHING.
    path = tmp_path / "pm_mission.json"
    path.write_text(json.dumps({
        "pm": agent, "writer": agent, "auditor": agent,
        "status": "active", "scope_paths": ["*"], "mission_id": "self-claim",
    }), encoding="utf-8")
    for rel in _RAILS:
        assert WDL.control_authority_violation(rel, agent=agent), (agent, rel)

    # (b) The ASSIGNMENT declaration itself is denied (this is the self-promotion vector).
    for rel in (".claude/settings.json", ".cursor/hooks.json"):
        assert WDL.control_authority_violation(rel, agent=agent), (agent, rel)
        bad = PLG.pretooluse_block("Edit", {"file_path": str(ROOT / rel)})
        assert any("control-authority" in b for b in bad), (agent, rel, bad)

    # (c) The operator GRANT rails are denied (this is the self-authorization vector).
    for rel in ("governance/operator_go.json", "governance/operator_grants.json"):
        assert WDL.control_authority_violation(rel, agent=agent), (agent, rel)

    # (d) ...while ordinary product work stays autonomous.
    for rel in _PRODUCT:
        assert WDL.control_authority_violation(rel, agent=agent) is None, (agent, rel)


@pytest.mark.parametrize("agent", ["claude", "cursor", "codex"])
def test_selected_writer_cannot_redefine_control_authority(agent, monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", agent)
    for rel in _RAILS:
        auth = WDL.control_authority_violation(rel, agent=agent)
        assert auth and "control-authority" in auth, rel
        bad = PLG.pretooluse_block("Edit", {"file_path": str(ROOT / rel)})
        assert any("control-authority" in b for b in bad), (agent, rel, bad)


def test_switching_ai_does_not_edit_policy_code(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    lock = ROOT / "tools" / "writer_drift_lock.py"
    before = lock.read_bytes()
    for agent in ("cursor", "claude", "gpt"):
        monkeypatch.setenv("ED_AGENT_ROLE", agent)
        bad = PLG.pretooluse_block("Edit", {"file_path": str(ROOT / "server.py")})
        assert not _writer_veto(bad), (agent, bad)
        rails = PLG.pretooluse_block("Edit", {"file_path": str(lock)})
        assert any("control-authority" in b for b in rails), agent
    assert lock.read_bytes() == before


def test_writer_self_set_does_not_grant_rails(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    # The agent ACTUALLY writes itself in as writer (RC-461: the file is coordination
    # text, so this write is permitted) - and it still unlocks nothing.
    (tmp_path / "pm_mission.json").write_text(json.dumps({
        "writer": "cursor", "pm": "operator", "status": "active",
        "scope_paths": ["server.py"], "remaining": [{"id": "X"}],
    }), encoding="utf-8")
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block(
        "Edit",
        {"file_path": str(ROOT / "tools" / "operating_process_lock.py")},
    )
    assert any("control-authority" in b for b in bad), bad


def test_legitimate_product_development_succeeds(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    assert WDL.control_authority_violation("server.py", agent="cursor") is None
    assert WDL.control_authority_violation("db.py", agent="codex") is None
    bad = PLG.pretooluse_block(
        "StrReplace",
        {"path": str(ROOT / "server.py"), "old_string": "a", "new_string": "b"},
    )
    assert not _writer_veto(bad)
    assert not any("PM-FIRST" in b for b in bad)
    assert not any("control-authority" in b for b in bad)


def test_negative_mutations_against_protected_control_surfaces_fail(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    # Even a mission the agent has widened to cover tools/ unlocks no rail (RC-461):
    # scope is coordination, never authorization.
    (tmp_path / "pm_mission.json").write_text(json.dumps({
        "status": "active",
        "writer": "cursor",
        "pm": "operator",
        "scope_paths": ["server.py", "tools/"],
        "remaining": [{"id": "X"}],
    }), encoding="utf-8")
    for rel in _RAILS:
        assert WDL.writer_drift_violations([rel], agent="cursor")
    no_verify = __import__(
        "tools.operator_law_guard", fromlist=["bash_violations"]
    ).bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in no_verify)


def test_no_executable_reader_uses_persisted_writer_or_auditor_as_auth():
    """Repo-wide: production Python must not read writer/auditor as a write gate."""
    import ast

    tracked = subprocess.check_output(
        ["git", "ls-files", "*.py"],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
    ).splitlines()
    hits: list[str] = []
    for rel in tracked:
        if rel.startswith("tests/") or rel.startswith("scratchpad/"):
            continue
        src = (ROOT / rel).read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            key = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in ("writer", "auditor")
            ):
                key = node.args[0].value
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value in ("writer", "auditor")
            ):
                key = node.slice.value
            if key:
                hits.append(f"{rel}:{getattr(node, 'lineno', 0)} reads persisted {key!r}")
    assert hits == [], (
        "executable reader still uses persisted writer/auditor — "
        + "; ".join(hits)
    )
