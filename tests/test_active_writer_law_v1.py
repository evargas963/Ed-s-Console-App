# institutional-synthetic-ok: inject permanent-identity and wrong-writer assignments.
"""Operator-selected ACTIVE_WRITER + one canonical worktree (RC-452 / RC-457)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.writer_drift_lock as WDL  # noqa: E402
from tools.check_institutional_correctness import (  # noqa: E402
    check_active_writer_law,
    check_writer_no_drift,
)


def _mission(writer: str, **extra: object) -> dict:
    doc = {
        "status": "active",
        "writer": writer,
        "active_writer": writer,
        "pm": "operator",
        "mission_id": "aw-neg-v1",
        "scope_paths": ["static/chart.html", "server.py", "tools/", "tests/"],
        "permanent_writer": None,
        "permanent_auditor": None,
    }
    doc.update(extra)
    return doc


def test_cursor_writes_when_assigned_active_writer():
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="cursor",
        mission=_mission("cursor"),
        sole_writer={"active_writer": "cursor", "writer": "cursor", "pm": "operator"},
    )
    assert msgs == []


def test_claude_writes_when_assigned_active_writer():
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="claude",
        mission=_mission("claude"),
        sole_writer={"active_writer": "claude", "writer": "claude", "pm": "operator"},
    )
    assert msgs == []


def test_neither_has_permanent_writer_privilege():
    v = WDL.permanent_identity_violations(
        sole={"pm": "operator", "writer": "claude", "permanent_writer": "claude"},
        mission={"pm": "operator", "writer": "claude"},
    )
    assert v and any("permanent_writer" in m for m in v)
    v2 = WDL.permanent_identity_violations(
        sole={
            "pm": "operator",
            "writer": "claude",
            "standing_law": "Cursor is an adversarial auditor only and never writes feature/kill/implementation code. Claude is sole writer.",
        },
        mission={"pm": "operator"},
    )
    assert v2 and any("identity-bound privilege" in m for m in v2)


def test_non_active_agent_cannot_mutate_same_worktree():
    cursor_blocked = WDL.writer_drift_violations(
        ["server.py"],
        agent="cursor",
        mission=_mission("claude"),
        sole_writer={"active_writer": "claude", "writer": "claude", "pm": "operator"},
    )
    assert cursor_blocked and any("ACTIVE_WRITER" in m for m in cursor_blocked)
    claude_blocked = WDL.writer_drift_violations(
        ["server.py"],
        agent="claude",
        mission=_mission("cursor"),
        sole_writer={"active_writer": "cursor", "writer": "cursor", "pm": "operator"},
    )
    assert claude_blocked and any("ACTIVE_WRITER" in m for m in claude_blocked)


def test_operator_remains_governing_authority():
    v = WDL.permanent_identity_violations(
        sole={"pm": "cursor", "writer": "cursor", "active_writer": "cursor"},
        mission={"pm": "cursor", "writer": "cursor"},
    )
    assert v and any("must be 'operator'" in m for m in v)


def test_active_writer_disagrees_with_writer_blocks():
    v = WDL.permanent_identity_violations(
        sole={"pm": "operator", "active_writer": "cursor", "writer": "claude"},
        mission={"pm": "operator", "active_writer": "cursor", "writer": "cursor"},
    )
    assert v and any("disagrees" in m for m in v)


def test_pretooluse_cursor_active_writer_allows_product(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    monkeypatch.delenv("ED_WRITER_DRIFT_GUARD", raising=False)
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission("cursor")), encoding="utf-8")
    sole = tmp_path / "sole_writer.json"
    sole.write_text(
        json.dumps({"active_writer": "cursor", "writer": "cursor", "pm": "operator"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(OPL, "SOLE_WRITER_PATH", sole)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(WDL, "SOLE_WRITER_PATH", sole)
    assert OPL.pm_mission_edit_violation("static/chart.html", agent="cursor") is None
    msg = OPL.pm_mission_edit_violation("static/chart.html", agent="claude")
    assert msg and "ACTIVE_WRITER" in msg


def test_check_active_writer_law_name_present():
    assert callable(check_active_writer_law)
    assert callable(check_writer_no_drift)


def test_live_assignment_has_no_permanent_identity():
    """Live sole_writer/pm_mission must satisfy the operator 2026-08-22 law."""
    assert check_active_writer_law() == []
    sole = json.loads((ROOT / "governance" / "sole_writer.json").read_text(encoding="utf-8"))
    assert sole.get("pm") == "operator"
    assert sole.get("permanent_writer") in (None, "", "null")
    assert sole.get("permanent_auditor") in (None, "", "null")
    assert (sole.get("active_writer") or sole.get("writer")) in ("cursor", "claude")
    assert sole.get("one_canonical_worktree") is True
    assert sole.get("one_writer_per_worktree") is not True


def test_second_normal_worktree_blocks():
    policy = {
        "mode": "canonical",
        "max_normal_project_worktrees": 1,
        "exclude_path_substrings": ["/tmp/", "deltagate-", ".claude/worktrees"],
    }
    msgs = WDL.canonical_worktree_violations(
        worktrees=[Path("/workspace"), Path("/workspace-Claude")],
        policy=policy,
        require=True,
    )
    assert msgs and any("CANONICAL_WORKTREE" in m and "2 normal" in m for m in msgs)


def test_measurement_tmp_worktree_does_not_count():
    policy = {
        "mode": "canonical",
        "max_normal_project_worktrees": 1,
        "exclude_path_substrings": ["/tmp/", "deltagate-", ".claude/worktrees"],
    }
    msgs = WDL.canonical_worktree_violations(
        worktrees=[Path("/workspace"), Path("/tmp/deltagate-abc")],
        policy=policy,
        require=True,
    )
    assert msgs == []


def test_zero_worktrees_blocks():
    msgs = WDL.canonical_worktree_violations(
        worktrees=[],
        policy={"mode": "canonical"},
        require=True,
    )
    assert msgs and any("zero" in m for m in msgs)


def test_operator_flip_active_writer_is_clean():
    """Assignment change is a field flip — neither agent keeps privilege."""
    cursor = WDL.resolved_writer(
        {"active_writer": "cursor", "writer": "cursor"},
        {"active_writer": "cursor", "writer": "cursor"},
    )
    claude = WDL.resolved_writer(
        {"active_writer": "claude", "writer": "claude"},
        {"active_writer": "claude", "writer": "claude"},
    )
    assert cursor == "cursor"
    assert claude == "claude"
    assert cursor != claude


def test_one_writer_per_worktree_flag_blocks():
    v = WDL.permanent_identity_violations(
        sole={
            "pm": "operator",
            "writer": "cursor",
            "one_writer_per_worktree": True,
            "one_canonical_worktree": True,
        },
        mission={"pm": "operator", "writer": "cursor"},
    )
    assert v and any("one_writer_per_worktree" in m for m in v)
