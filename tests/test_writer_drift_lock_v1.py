# institutional-synthetic-ok: inject assigned principals + dirty rails to prove RC-454 BLOCKs.
"""Architecture A control-authority lock — negative controls (RC-454)."""
from __future__ import annotations

import json
import os
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
        "pm": "operator",
        "writer": "claude",
        "mission_id": "drift-neg-v1",
        "scope_paths": ["static/chart.html", "server.py", "tools/", "tests/"],
    }


def test_stale_writer_metadata_cannot_block_cursor_on_product():
    """PROVEN: writer=claude leftover + cursor agent + dirty product → no writer veto."""
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="cursor",
        mission=_mission_claude_scope(),
        sole_writer={"writer": "claude", "pm": "operator"},
    )
    assert msgs == []


def test_writer_drift_allows_pm_governance_touch():
    """Governance / leftover assignment JSON under mission → PASS for Cursor."""
    msgs = WDL.writer_drift_violations(
        ["governance/pm_mission.json", "governance/sole_writer.json", "reports/cursor_desk_audit_v1.md"],
        agent="cursor",
        mission=_mission_claude_scope(),
        sole_writer={"writer": "claude", "pm": "operator"},
    )
    assert msgs == []


def test_writer_drift_allows_any_assigned_product_agent():
    for agent in ("claude", "cursor", "codex", "gpt"):
        msgs = WDL.writer_drift_violations(
            ["static/chart.html"],
            agent=agent,
            mission=_mission_claude_scope(),
            sole_writer={"writer": "claude"},
        )
        assert msgs == [], agent


def test_writer_drift_idle_mission_no_scope_drift():
    msgs = WDL.writer_drift_violations(
        ["static/chart.html"],
        agent="cursor",
        mission={"status": "idle", "writer": "claude", "scope_paths": ["static/"]},
        sole_writer={"writer": "claude"},
    )
    assert msgs == []


def test_ordinary_product_is_autonomous_for_every_assigned_agent(monkeypatch, tmp_path):
    """RC-461: the coding AI does ordinary repo work WITHOUT operator approval.

    The PM-mission edit gate is gone. Whatever a mission file happens to say - even a
    mission naming a different writer with a narrow scope - ordinary product paths stay
    open to every assigned principal. Only AUTHORITY files are denied.
    """
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", mission)
    for agent in ("cursor", "claude", "codex", "gpt"):
        for rel in ("static/chart.html", "server.py", "db.py", "signals.py"):
            assert WDL.control_authority_violation(rel, agent=agent) is None, (agent, rel)
        assert WDL.writer_drift_violations(
            ["static/chart.html", "server.py", "db.py"], agent=agent
        ) == [], agent
    # ...and the gate that used to block them no longer exists at all.
    assert not hasattr(OPL, "pm_mission_edit_violation")
    assert not hasattr(OPL, "sole_writer_edit_violation")


def test_hard_denylist_no_longer_vendor_gates_product(monkeypatch):
    """Product hard-denylist retired: chart/server/db are not writer-gated."""
    monkeypatch.delenv("ED_WRITER_DRIFT_GUARD", raising=False)
    mission = {"status": "active", "writer": "claude", "mission_id": "m1", "scope_paths": ["tools/"]}
    sole = {"writer": "claude"}
    for rel in ("static/chart.html", "server.py", "market_context.py", "db.py"):
        assert WDL.control_authority_violation(rel, agent="cursor") is None
        assert WDL.control_authority_violation(rel, agent="claude") is None


def test_lock1_lock_modules_are_not_agent_writable(monkeypatch):
    """Architecture A: no assigned principal may rewrite control-authority rails."""
    mission = {"status": "active", "writer": "claude", "mission_id": "m1", "scope_paths": ["tools/"]}
    sole = {"writer": "claude"}
    assert WDL.control_authority_violation(
        "tools/check_institutional_correctness.py", agent="cursor"
    )
    assert WDL.writer_drift_violations(
        ["tools/writer_drift_lock.py"],
        agent="cursor",
        mission=mission,
        sole_writer=sole,
    )
    assert WDL.writer_drift_violations(
        ["tools/writer_drift_lock.py"],
        agent="claude",
        mission=mission,
        sole_writer=sole,
    )
    assert WDL.control_authority_violation("server.py", agent="cursor") is None


def test_persisted_metadata_grants_no_authority(monkeypatch, tmp_path):
    """RC-461: no writer/auditor/vendor/pm field in a repo JSON grants authority.

    An agent may freely rewrite coordination metadata - including naming ITSELF writer,
    or writing pm=<itself> - and gains NOTHING by it: the control-authority rail still
    denies every authority file, because the rail reads the operator-assigned principal,
    never a field the agent can type.
    """
    mission = tmp_path / "pm_mission.json"
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", mission)
    for agent in ("cursor", "claude", "codex"):
        mission.write_text(json.dumps({
            "status": "active", "writer": agent, "auditor": agent,
            "pm": agent, "mission_id": "m1", "scope_paths": ["*"],
        }), encoding="utf-8")
        # Self-declared pm/writer buys no authority.
        for rel in (".github/CODEOWNERS", ".claude/settings.json",
                    "tools/writer_drift_lock.py", "governance/operator_grants.json",
                    ".github/workflows/pytest.yml"):
            assert WDL.control_authority_violation(rel, agent=agent), (agent, rel)
        # ...and ordinary product remains open regardless of what the file claims.
        assert WDL.control_authority_violation("server.py", agent=agent) is None


def test_lock4_self_heal_owed_blocks_until_rc_exists(tmp_path, monkeypatch):
    """LOCK-4: a recorded SOD_DRIFT denial with no RC naming mission+SOD_DRIFT BLOCKS;
    the matching row clears it."""
    ledger = tmp_path / "sod_drift_events.jsonl"
    monkeypatch.setattr(WDL, "SOD_DRIFT_EVENTS_PATH", ledger)
    monkeypatch.setattr(WDL, "PM_MISSION_PATH", tmp_path / "pm_mission.json")
    (tmp_path / "pm_mission.json").write_text(
        '{"status": "active", "writer": "claude", "mission_id": "m-heal"}', encoding="utf-8")
    import json as _json
    ledger.write_text(_json.dumps({
        "ts": 1.0, "agent": "cursor", "mission_id": "m-heal",
        "message": "SOD_DRIFT: synthetic", "healed": False,
    }) + "\n", encoding="utf-8")
    owed = WDL.self_heal_owed_violations(rc_lines=["| RC-1 | OPEN | d | d | x | y | z |"])
    assert owed and owed[0].startswith("SELF_HEAL_OWED:")
    healed_rows = ["| RC-999 | OPEN | d | d | SOD_DRIFT denial for mission m-heal | why | plan |"]
    assert not WDL.self_heal_owed_violations(rc_lines=healed_rows)


# RC-470: the check_writer_no_drift name-presence control left with its check
# (retired - governance/retired_checks.md); the writer_drift_lock library tests
# above are untouched.


def test_stale_cursor_assignment_cannot_block_claude_on_product():
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
    assert msgs == []


def test_cursor_strreplace_product_path_allowed(monkeypatch, tmp_path):
    """Cursor continuum: StrReplace + tool_input.path on ordinary product must ALLOW."""
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
    assert not any("WRITER-DRIFT" in b or "sole writer" in b.lower() for b in bad)
    assert not any("control-authority" in b for b in bad)


def test_cursor_strreplace_pm_path_allowed(monkeypatch, tmp_path):
    """Leftover mission JSON via Cursor StrReplace must ALLOW (not a rail)."""
    import tools.process_lock_guard as PLG

    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(json.dumps(_mission_claude_scope()), encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    # This test asserts a PATH-CLASSIFICATION property. Pin the LOCK-4 ledger to tmp so an
    # unhealed denial in the developer's working tree cannot fail it: that would be ambient
    # state, not the behaviour under test. LOCK-4 is unchanged and is exercised on its own
    # in test_lock4_self_heal_owed_blocks_until_rc_exists.
    monkeypatch.setattr(WDL, "SOD_DRIFT_EVENTS_PATH", tmp_path / "sod_drift_events.jsonl")
    bad = PLG.pretooluse_block(
        "StrReplace",
        {"path": str(ROOT / "governance" / "pm_mission.json")},
    )
    assert not [b for b in bad if "SOD_DRIFT" in b or "WRITER-DRIFT" in b]


def test_rc240_precommit_wrapper_never_fabricates_an_agent_identity():
    """RC-240: the pre-commit wrapper must not INVENT the actor."""
    src = (ROOT / "tools" / "precommit_institutional.py").read_text(encoding="utf-8")
    for forged in ('ED_AGENT_ROLE"] = "cursor"', "ED_AGENT_ROLE'] = 'cursor'",
                   'ED_AGENT_ROLE"] = "claude"', "ED_AGENT_ROLE'] = 'claude'"):
        assert forged not in src, (
            f"the pre-commit wrapper assigns a literal agent role ({forged!r}) — a "
            f"fabricated identity is what RC-240 was opened for"
        )
    assert 'os.environ.pop("ED_AGENT_ROLE", None)' in src, (
        "the wrapper must leave identity ABSENT when the environment carries none, so the "
        "backstop abstains instead of judging under a wrong actor"
    )


def test_rc240_gate_entry_actually_clears_a_fabricated_role_in_process(monkeypatch):
    """RC-240 behavioral: prove the gate entry EXECUTES the clear."""
    import tools.precommit_institutional as PI

    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    PI._neutralize_fabricated_identity()
    assert "ED_AGENT_ROLE" not in os.environ, (
        "the institutional gate entry left a fabricated ED_AGENT_ROLE in its own process — "
        "RC-240 requires it be cleared so nothing downstream judges under a wrong actor"
    )
