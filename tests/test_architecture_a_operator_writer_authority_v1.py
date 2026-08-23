# institutional-synthetic-ok: drive the live PreToolUse seam against leftover
# assignment metadata to prove RC-454 operator-writer authority.
"""Architecture A — operator selects the working AI; rails stay denied.

These tests exercise process_lock_guard.pretooluse_block, not a constructed
authorization dictionary. Live pm_mission.json may still say writer=claude;
that leftover must not veto the AI the operator is running.
"""
from __future__ import annotations

import json
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


def _active_mission_with_stale_writer() -> dict:
    live = json.loads((ROOT / "governance" / "pm_mission.json").read_text(encoding="utf-8"))
    return {
        "status": "active",
        "writer": live.get("writer") or "claude",
        "pm": "operator",
        "auditor": "cursor",
        "mission_id": "rc454-authority",
        "scope_paths": ["*"],
    }


def _pin_mission(monkeypatch, tmp_path, mission: dict | None = None) -> None:
    path = tmp_path / "pm_mission.json"
    path.write_text(json.dumps(mission or _active_mission_with_stale_writer()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", path)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", path)


def _writer_veto(messages: list[str]) -> list[str]:
    needles = ("sole writer", "WRITER-DRIFT", "is sole writer")
    return [m for m in messages if any(n in m for n in needles)]


@pytest.mark.parametrize("agent", ["claude", "cursor", "codex", "gpt"])
def test_ordinary_product_not_intrinsically_vendor_only(agent, monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", agent)
    for rel in _PRODUCT:
        assert OPL.sole_writer_edit_violation(rel, agent=agent) is None, rel
        assert WDL.hard_denylist_violation(rel, agent=agent) is None, rel
        bad = PLG.pretooluse_block("Edit", {"file_path": str(ROOT / rel)})
        assert not _writer_veto(bad), (agent, rel, bad)
        assert not any("control-authority" in b for b in bad), (agent, rel, bad)


def test_live_stale_assignment_cannot_veto_operator_selected_work(monkeypatch, tmp_path):
    live = json.loads((ROOT / "governance" / "pm_mission.json").read_text(encoding="utf-8"))
    assert live.get("writer") == "claude", (
        "this proof requires the live leftover writer=claude metadata; "
        "do not flip it to the currently selected agent"
    )
    _pin_mission(monkeypatch, tmp_path, {
        "status": "active",
        "writer": live["writer"],
        "pm": live.get("pm") or "operator",
        "mission_id": "rc454-live-stale",
        "scope_paths": ["*"],
    })
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    for rel in ("server.py", "db.py"):
        assert OPL.sole_writer_edit_violation(rel, agent="cursor") is None, rel
        bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / rel), "content": "x"})
        assert not _writer_veto(bad), (rel, bad)


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
    cur = json.dumps({"writer": "claude", "pm": "operator", "status": "active",
                      "scope_paths": ["server.py"], "remaining": [{"id": "X"}]})
    new = json.dumps({"writer": "cursor", "pm": "operator", "status": "active",
                      "scope_paths": ["server.py"], "remaining": [{"id": "X"}]})
    assert WDL.pm_status_field_violations(
        "governance/pm_mission.json", new, agent="cursor", current_text=cur
    ) == []
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block(
        "Edit",
        {"file_path": str(ROOT / "tools" / "operating_process_lock.py")},
    )
    assert any("control-authority" in b for b in bad), bad


def test_legitimate_product_development_succeeds(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path)
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    assert OPL.pm_mission_edit_violation("server.py", agent="cursor") is None
    assert OPL.pm_mission_edit_violation("db.py", agent="codex") is None
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
    grow = json.dumps({
        "status": "active",
        "writer": "cursor",
        "scope_paths": ["server.py", "tools/"],
        "remaining": [{"id": "X"}],
    })
    cur = json.dumps({
        "status": "active",
        "writer": "claude",
        "scope_paths": ["server.py"],
        "remaining": [{"id": "X"}],
    })
    assert WDL.pm_status_field_violations(
        "governance/pm_mission.json", grow, agent="cursor", current_text=cur
    )
    for rel in _RAILS:
        assert WDL.writer_drift_violations([rel], agent="cursor")
    no_verify = __import__(
        "tools.operator_law_guard", fromlist=["bash_violations"]
    ).bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in no_verify)


def test_idle_mission_still_blocks_gated_product(monkeypatch, tmp_path):
    _pin_mission(monkeypatch, tmp_path, {
        "status": "idle",
        "writer": "claude",
        "scope_paths": ["*"],
    })
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    msg = OPL.pm_mission_edit_violation("db.py", agent="cursor")
    assert msg and "PM-FIRST" in msg
