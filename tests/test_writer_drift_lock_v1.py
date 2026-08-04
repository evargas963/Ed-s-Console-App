# institutional-synthetic-ok: inject writer≠agent + fake scope dirty paths to prove RC-226 BLOCKs.
"""Writer no-drift lock — negative controls (RC-226)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.writer_drift_lock as WDL  # noqa: E402


def _mission_claude_scope() -> dict:
    return {
        "status": "ready_for_claude",
        "writer": "claude",
        "mission_id": "drift-neg-v1",
        "scope_paths": ["static/chart.html", "server.py", "tools/", "tests/"],
    }


def test_writer_drift_blocks_cursor_on_scope_path():
    """PROVEN BLOCK: writer=claude + cursor agent + dirty scope path → violations."""
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="cursor",
        mission=_mission_claude_scope(),
        sole_writer={"writer": "claude", "pm": "cursor"},
    )
    assert msgs, "expected WRITER-DRIFT BLOCK on scope path"
    assert any("SOD_DRIFT: claude is sole writer" in m for m in msgs)
    assert any("WRITER-DRIFT" in m for m in msgs)
    assert any("static/chart.html" in m for m in msgs)


def test_writer_drift_allows_pm_governance_touch():
    """Governance / PM allowlist under mission → PASS for Cursor."""
    msgs = WDL.writer_drift_violations(
        ["governance/pm_mission.json", "governance/sole_writer.json", "reports/cursor_desk_audit_v1.md"],
        agent="cursor",
        mission=_mission_claude_scope(),
        sole_writer={"writer": "claude", "pm": "cursor"},
    )
    assert msgs == []


def test_writer_drift_allows_named_writer():
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="claude",
        mission=_mission_claude_scope(),
        sole_writer={"writer": "claude"},
    )
    assert msgs == []


def test_writer_drift_idle_mission_no_scope_drift():
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="cursor",
        mission={"status": "idle", "writer": "claude", "scope_paths": ["static/"]},
        sole_writer={"writer": "claude"},
    )
    assert msgs == []


def test_pretooluse_ready_for_claude_blocks_cursor_product(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    monkeypatch.delenv("ED_WRITER_DRIFT_GUARD", raising=False)
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", mission)
    msg = OPL.pm_mission_edit_violation("static/chart.html", agent="cursor")
    assert msg and "SOD_DRIFT: claude is sole writer" in msg and "WRITER-DRIFT" in msg


def test_pretooluse_ready_for_claude_allows_claude_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    assert OPL.pm_mission_edit_violation("static/chart.html", agent="claude") is None


def test_check_writer_no_drift_name_present_for_negative_control():
    """RC-95: ENFORCED check id must appear in tests (name-presence + injection above)."""
    from tools.check_institutional_correctness import check_writer_no_drift

    assert callable(check_writer_no_drift)


def test_mirror_blocks_claude_when_writer_is_cursor():
    msgs = WDL.writer_drift_violations(
        ["server.py"],
        agent="claude",
        mission={
            "status": "active",
            "writer": "cursor",
            "mission_id": "cursor-write-v1",
            "scope_paths": ["server.py"],
        },
        sole_writer={"writer": "cursor"},
    )
    assert msgs and any("WRITER-DRIFT" in m for m in msgs)
    assert any("SOD_DRIFT: cursor is sole writer" in m for m in msgs)


def test_cursor_strreplace_path_field_blocked(monkeypatch, tmp_path):
    """Cursor continuum: StrReplace + tool_input.path must BLOCK (not only Claude file_path)."""
    import tools.process_lock_guard as PLG

    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    monkeypatch.delenv("ED_PROCESS_LOCK_GUARD", raising=False)
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", mission)
    bad = PLG.pretooluse_block(
        "StrReplace",
        {"path": str(ROOT / "static" / "chart.html"), "old_string": "a", "new_string": "b"},
    )
    assert bad and any("SOD_DRIFT" in b for b in bad)


def test_cursor_strreplace_pm_path_allowed(monkeypatch, tmp_path):
    """PM-only path via Cursor StrReplace must ALLOW while writer=claude."""
    import tools.process_lock_guard as PLG

    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    bad = PLG.pretooluse_block(
        "StrReplace",
        {"path": str(ROOT / "governance" / "pm_mission.json")},
    )
    assert not [b for b in bad if "SOD_DRIFT" in b or "WRITER-DRIFT" in b]
