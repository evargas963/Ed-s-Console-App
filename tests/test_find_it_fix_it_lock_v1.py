# institutional-synthetic-ok: inject incomplete active views and fake blockers.
"""FIND IT → FIX IT — one RC-log authority, derived active view (RC-453)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.find_it_fix_it_lock as FIF  # noqa: E402
from tools.check_institutional_correctness import check_find_it_fix_it  # noqa: E402

TODAY = "2026-08-22"
MISSION = {
    "status": "active",
    "mission_id": "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1",
    "scope_paths": ["order_flow_engine.py", "institutional_behavior.py"],
    "writer": "cursor",
}


def _row(
    rc_id: str,
    *,
    status: str = "OPEN",
    opened: str = TODAY,
    extra_defect: str = "",
    extra_fix: str = "",
) -> str:
    return (
        f"| {rc_id} | {status} | {opened} | 2026-09-22 | "
        f"DEFECT {extra_defect} | (1) why a (2) why b (3) why c (4) why d (5) ROOT | "
        f"{extra_fix} |"
    )


def _offenders(rows: list[str], **kwargs):
    text = "\n".join(rows)
    payload = kwargs.pop("payload", None)
    if payload is None:
        payload = {"_skip_second_work_list": True}
    return FIF.active_obligation_offenders(
        text,
        today=TODAY,
        mission=MISSION,
        dirty_paths=kwargs.pop("dirty_paths", []),
        presented_ids=kwargs.pop("presented_ids", None),
        repo=kwargs.pop("repo", ROOT),
        payload=payload,
    )


def test_rc_log_has_zero_execution_authority():
    """OPEN / CLASS:ACTIVE RC rows do not create, classify, or close work."""
    rows = [
        _row(
            "RC-9001",
            extra_defect="CLASS:ACTIVE mission_id: ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1",
            extra_fix="IN PROGRESS",
        ),
        _row("RC-9003", extra_defect="CLASS:PASSIVE", extra_fix="queued for later"),
    ]
    text = "\n".join(rows)
    assert FIF.derive_active_obligations(text, today=TODAY, mission=MISSION) == []
    assert FIF.illegal_passive_escape_offenders(text, today=TODAY, mission=MISSION) == []
    off = _offenders(rows, presented_ids=["RC-9001"])
    assert not any(rid.startswith("RC-") for rid, _ in off)


def test_live_rc_log_does_not_emit_work_state():
    text = (ROOT / "governance" / "root_cause_log.md").read_text(encoding="utf-8")
    assert FIF.derive_active_obligations(text) == []
    assert FIF.illegal_passive_escape_offenders(text) == []


def test_passive_implicated_by_dirty_product_is_not_rc_work_state():
    rows = [
        _row(
            "RC-9004",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE order_flow_engine.py composite",
            extra_fix="historical note",
        ),
    ]
    off = _offenders(rows, dirty_paths=["order_flow_engine.py"], presented_ids=None)
    assert not any(rid == "RC-9004" for rid, _ in off)


def test_wide_surface_edit_does_not_activate_historical_chart_backlog():
    rows = [
        _row(
            "RC-9005b",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE static/chart.html corridor shade",
            extra_fix="historical note",
        ),
    ]
    off = _offenders(rows, dirty_paths=["static/chart.html"], presented_ids=None)
    assert off == [], "editing chart.html must not activate the entire historical chart backlog"


def test_historical_passive_untouched_does_not_block():
    rows = [
        _row(
            "RC-9005",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE some_unrelated_module.py",
            extra_fix="backlog",
        ),
    ]
    off = _offenders(rows, dirty_paths=[], presented_ids=None)
    assert off == []


def test_fake_rth_blocker_without_probe_is_invalid_metadata():
    ok, why = FIF.blocker_evidence_ok({
        "type": "RTH_ONLY",
        "assertion": "tape_same_ms_loss",
        "probe": "does_not_exist.py",
        "non_rth_complete": "true",
        "rth_observation": "live",
    }, repo=ROOT)
    assert ok is False
    assert "probe" in why


def test_rth_probe_not_designed_for_assertion_blocks(tmp_path):
    probe = tmp_path / "probe_other.py"
    probe.write_text("assert True  # unrelated\n", encoding="utf-8")
    rows = [
        _row(
            "RC-9007",
            extra_defect="CLASS:ACTIVE",
            extra_fix=(
                "HARD_BLOCKER: RTH_ONLY assertion=tape_same_ms_loss "
                f"probe={probe.name} non_rth_complete=true rth_observation=live_tape"
            ),
        ),
    ]
    ok, why = FIF.blocker_evidence_ok({
        "type": "RTH_ONLY",
        "assertion": "tape_same_ms_loss",
        "probe": probe.name,
        "non_rth_complete": "true",
        "rth_observation": "live_tape",
    }, repo=tmp_path)
    assert ok is False
    assert "not designed to test" in why


def test_turn_budget_is_never_a_blocker():
    assert FIF._banned_blocker_language("blocked by turn budget and next pass")


def test_rc_fixed_row_is_not_an_obligation():
    rows = [
        _row(
            "RC-9009",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: renamed the field. command: ``",
        ),
        _row(
            "RC-9010",
            extra_defect="CLASS:ACTIVE",
            extra_fix=(
                "FIXED: lock omission. "
                "VERIFIED: `tests/test_find_it_fix_it_lock_v1.py` "
            ),
        ),
    ]
    off = _offenders(rows, presented_ids=None)
    assert not any(rid in {"RC-9009", "RC-9010"} for rid, _ in off)


def test_derived_active_defects_json_is_not_rc_authority(tmp_path, monkeypatch):
    rc = tmp_path / "root_cause_log.md"
    rc.write_text(
        _row("RC-9011", extra_defect="CLASS:ACTIVE", extra_fix="IN PROGRESS") + "\n",
        encoding="utf-8",
    )
    derived = tmp_path / "active_defects.json"
    derived.write_text(json.dumps({"defects": []}), encoding="utf-8")
    monkeypatch.setattr(FIF, "ACTIVE_DEFECTS_PATH", derived)
    monkeypatch.setattr(FIF, "RC_LOG", rc)
    off = FIF.active_obligation_offenders(
        rc.read_text(encoding="utf-8"),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=FIF.load_optional_derived_view(derived),
        repo=ROOT,
        payload={"_skip_second_work_list": True},
    )
    assert not any(rid == "RC-9011" for rid, _ in off)


def test_stop_and_gate_share_one_authority():
    import tools.stop_guard as SG
    assert SG.fix_law_blockers.__doc__
    src = Path(SG.__file__).read_text(encoding="utf-8")
    assert "find_it_fix_it_lock" in src
    assert "fix_law_blockers" in src


def test_check_find_it_fix_it_name_present():
    assert callable(check_find_it_fix_it)
    assert "find_it_fix_it" in Path(
        ROOT / "tools" / "check_institutional_correctness.py"
    ).read_text(encoding="utf-8")


def test_declared_material_defect_omitted_from_master_blocks():
    rows = [
        _row("RC-9012", extra_defect="CLASS:ACTIVE", extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`"),
    ]
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload={"last_assistant_text": "MATERIAL_DEFECT: RC-9999 tape same-ms loss"},
    )
    assert any(rid == "RC-9999" and "omitted" in why for rid, why in off)


def test_declared_defect_present_on_master_does_not_block():
    rows = [
        _row(
            "RC-9013",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload={
            "last_assistant_text": "MATERIAL_DEFECT: RC-479 lock omission",
            "_requirement_tree": {"items": []},
            "_skip_second_work_list": True,
        },
    )
    assert not any(rid == "RC-479" for rid, _ in off)


def test_token_budget_is_never_a_blocker():
    assert FIF._banned_blocker_language("blocked by token budget and too much work")


def test_rth_probe_without_session_measurement_blocks(tmp_path):
    probe = tmp_path / "probe_named.py"
    probe.write_text("def tape_same_ms_loss():\n    return True\n", encoding="utf-8")
    rows = [
        _row(
            "RC-9015",
            extra_defect="CLASS:ACTIVE",
            extra_fix=(
                "HARD_BLOCKER: RTH_ONLY assertion=tape_same_ms_loss "
                f"probe={probe.name} non_rth_complete=true rth_observation=live_tape"
            ),
        ),
    ]
    ok, why = FIF.blocker_evidence_ok({
        "type": "RTH_ONLY",
        "assertion": "tape_same_ms_loss",
        "probe": probe.name,
        "non_rth_complete": "true",
        "rth_observation": "live_tape",
    }, repo=tmp_path)
    assert ok is False
    assert "must actually measure session hours" in why


def test_external_unimplemented_is_not_unavailability(tmp_path):
    ev = tmp_path / "note.txt"
    ev.write_text("schwab tape not implemented TODO coming soon", encoding="utf-8")
    rows = [
        _row(
            "RC-9016",
            extra_defect="CLASS:ACTIVE",
            extra_fix=(
                "HARD_BLOCKER: EXTERNAL_DATA_UNAVAILABLE assertion=native_tape "
                f"capability=aggressor source=schwab unavailability_evidence={ev.name}"
            ),
        ),
    ]
    ok, why = FIF.blocker_evidence_ok({
        "type": "EXTERNAL_DATA_UNAVAILABLE",
        "assertion": "native_tape",
        "capability": "aggressor",
        "source": "schwab",
        "unavailability_evidence": ev.name,
    }, repo=tmp_path)
    assert ok is False
    assert "unimplemented" in why or "unavailable" in why


def test_destructive_without_object_blocks():
    rows = [
        _row(
            "RC-9017",
            extra_defect="CLASS:ACTIVE",
            extra_fix="HARD_BLOCKER: DESTRUCTIVE_APPROVAL_REQUIRED assertion=drop_old_db operation=delete",
        ),
    ]
    ok, why = FIF.blocker_evidence_ok({
        "type": "DESTRUCTIVE_APPROVAL_REQUIRED",
        "assertion": "drop_old_db",
        "operation": "delete",
    }, repo=ROOT)
    assert ok is False
    assert "exact object" in why


def test_environment_turn_budget_rejected():
    rows = [
        _row(
            "RC-9018",
            extra_defect="CLASS:ACTIVE",
            extra_fix=(
                "HARD_BLOCKER: ENVIRONMENT_BLOCKED assertion=cannot_continue "
                "command=pytest observed_error=Error turn budget exhausted"
            ),
        ),
    ]
    ok, why = FIF.blocker_evidence_ok({
        "type": "ENVIRONMENT_BLOCKED",
        "assertion": "cannot_continue",
        "command": "pytest",
        "observed_error": "Error turn budget exhausted",
    }, repo=ROOT)
    assert ok is False
    assert "never" in why or "environment failure" in why


def test_nonexistent_command_blocks():
    rows = [
        _row(
            "RC-9019",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: renamed. VERIFIED: `tests/does_not_exist_rc9019.py`",
        ),
    ]
    ok, why = FIF.remediation_ok({
        "id": "RC-9019",
        "defect": "CLASS:ACTIVE",
        "why": "",
        "fix": "FIXED: renamed. VERIFIED: `tests/does_not_exist_rc9019.py`",
        "line": "",
    }, repo=ROOT)
    assert ok is False
    assert "do not exist" in why


def test_failed_execution_evidence_blocks():
    rows = [
        _row(
            "RC-9020",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    ok, why = FIF.remediation_ok({
        "id": "RC-9020",
        "defect": "CLASS:ACTIVE",
        "why": "",
        "fix": "FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        "line": "",
    }, repo=ROOT, payload={"fix_evidence": {"RC-9020": {"ran": True, "exit": 1}}})
    assert ok is False
    assert "failed" in why


def test_remaining_active_parent_defects_without_material_token_blocks_stop():
    """Exact RC-468 regression: remaining-active list, no MATERIAL_DEFECT, Stop BLOCK."""
    rows = [
        _row(
            "RC-9100",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    payload = {
        "last_assistant_text": (
            "Data/DB — QUEUED — not a stop\n\n"
            "REMAINING ACTIVE PARENT DEFECTS\n"
            "- OF_PARENT reconstructed L1 tape pressure limitations still unstated\n"
            "- LP-01 Chart surface incomplete\n"
        )
    }
    assert "MATERIAL_DEFECT" not in payload["last_assistant_text"]
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload=payload,
    )
    assert off, "remaining-active fixable defects without MATERIAL_DEFECT must BLOCK Stop"
    assert any(
        "REMAINING ACTIVE" in why or "QUEUED" in why
        for _, why in off
    )


def test_proof_state_not_queued_cannot_stop_active_unproven_parent():
    """Exact packet: ACTIVE parent NOT_PROVEN + unresolved children +
    'proof state, not queued' + no HARD_BLOCKER → Stop BLOCK.
    """
    tree = {
        "items": [
            {
                "id": "OF_PARENT",
                "proof": "NOT_PROVEN",
                "execution": "ACTIVE",
                "closable": False,
                "children": ["OF_CHILD_UNRESOLVED"],
            },
            {
                "id": "OF_CHILD_UNRESOLVED",
                "proof": "FAIL",
                "execution": "ACTIVE",
                "children": [],
            },
        ]
    }
    rows = [
        _row(
            "RC-9200",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    payload = {
        "_requirement_tree": tree,
        "last_assistant_text": (
            "Parents OF / P2 / LP-01 / UI truth stay NOT_PROVEN. "
            "That is proof state, not a QUEUED leftover."
        ),
    }
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload=payload,
    )
    assert off, (
        "ACTIVE NOT_PROVEN parent with unresolved children called "
        "'proof state, not queued' must BLOCK Stop"
    )
    assert any(
        "proof state" in why.lower() or "not queued" in why.lower()
        for _, why in off
    )


def test_active_unproven_parent_blocks_stop_without_proof_state_phrase():
    """Vocabulary is not the only detector — silence must still BLOCK."""
    tree = {
        "items": [
            {
                "id": "LP01_PARENT",
                "proof": "NOT_PROVEN",
                "execution": "ACTIVE",
                "children": [],
            },
        ]
    }
    rows = [
        _row(
            "RC-9201",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    payload = {
        "_requirement_tree": tree,
        "last_assistant_text": "Wrap-up. Parents remain NOT_PROVEN as parent status.",
    }
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload=payload,
    )
    assert off, "ACTIVE NOT_PROVEN parent with no HARD_BLOCKER must BLOCK Stop"
    assert any("LP01_PARENT" in why for _, why in off)


def test_commit_path_does_not_use_requirement_tree_as_permanent_block():
    """payload=None is the commit check — do not freeze every commit on the tree."""
    rows = [
        _row(
            "RC-9202",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload={"_skip_second_work_list": True},
    )
    assert off == [], off


def test_remaining_active_hard_blocked_items_do_not_block_from_disposition():
    rows = [
        _row(
            "RC-9100b",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: lock. VERIFIED: `tests/test_find_it_fix_it_lock_v1.py`",
        ),
    ]
    payload = {
        "last_assistant_text": (
            "REMAINING ACTIVE PARENT DEFECTS\n"
            "- retrain HARD_BLOCKER: ENVIRONMENT_BLOCKED assertion=retrain_models "
            "command=python observed_error=ModuleNotFoundError: pandas\n"
        )
    }
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=ROOT,
        payload=payload,
    )
    assert off == [], off


def test_unrelated_historical_server_edit_stays_passive():
    rows = [
        _row(
            "RC-9101",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE server.py stale comment rewrite",
            extra_fix="historical note",
        ),
    ]
    off = _offenders(rows, dirty_paths=["server.py"])
    assert off == [], "unrelated historical server.py RC + unrelated server edit must stay PASSIVE"


def test_explicitly_implicated_server_defect_is_not_rc_work_state():
    rows = [
        _row(
            "RC-9102",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE server.py reconnect freshness",
            extra_fix="historical note",
        ),
    ]
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=["server.py"],
        presented_ids=None,
        repo=ROOT,
        payload={
            "last_assistant_text": (
                "RC-9102 server.py reconnect freshness is implicated by this mission"
            ),
            "_skip_second_work_list": True,
        },
    )
    assert not any(rid == "RC-9102" for rid, _ in off)


def test_child_test_cannot_close_parent():
    ok, why = FIF.remediation_ok({
        "id": "RC-9021",
        "defect": "CLASS:ACTIVE end-to-end parent order flow",
        "why": "",
        "fix": "FIXED: one ticker. VERIFIED: `tests/test_order_flow_engine_chunk2_or_fallthrough.py`",
        "line": "",
    }, repo=ROOT)
    assert ok is False
    assert "child test" in why or "parent" in why


def test_second_work_list_clean_supported_tree_passes():
    off = FIF.second_work_list_violations({"_check_second_list": True})
    assert off == [], off


def test_second_work_list_flags_unresolved_mark_outside_master(tmp_path):
    (tmp_path / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md").write_text(
        "# master\n- [ ] stay here\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "UNRESOLVED_WORK_ITEM" + ": fake leftover\n", encoding="utf-8"
    )
    import subprocess
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    off = FIF.second_work_list_violations({"_check_second_list": True}, repo=tmp_path)
    assert off, "injected unresolved work outside the sole master must BLOCK"
    assert any("README.md" in rid for rid, _ in off)


def test_second_work_list_flags_queue_table_without_magic_marker(tmp_path):
    """Actual bypass: Operator NOW / standing-queue table, no UNRESOLVED_WORK_ITEM."""
    (tmp_path / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md").write_text(
        "# master\n- [ ] stay here\n", encoding="utf-8"
    )
    cols = " | ".join(["ID", "Status", "Work item"])
    row = " | ".join(["ZZ-99", "NEXT", "hidden second list"])
    body = "\n".join([
        "## Operator NOW",
        f"| {cols} |",
        "|---|---|---|",
        f"| {row} |",
        "",
    ])
    assert "UNRESOLVED_WORK_ITEM" not in body
    (tmp_path / "SECOND_QUEUE.md").write_text(body, encoding="utf-8")
    import subprocess
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    off = FIF.second_work_list_violations({"_check_second_list": True}, repo=tmp_path)
    assert off, "queue table without magic marker must BLOCK"
    assert any("SECOND_QUEUE.md" in rid for rid, _ in off)


def test_second_work_list_scans_python_source_comments(tmp_path):
    (tmp_path / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md").write_text(
        "# master\n- [ ] stay here\n", encoding="utf-8"
    )
    (tmp_path / "hidden_debt.py").write_text(
        "# " + "UNRESOLVED_WORK_ITEM" + ": sneak in a comment\nprint(1)\n",
        encoding="utf-8",
    )
    import subprocess
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    off = FIF.second_work_list_violations({"_check_second_list": True}, repo=tmp_path)
    assert off, "Python source comment work must BLOCK"
    assert any("hidden_debt.py" in rid for rid, _ in off)


def test_second_work_list_does_not_treat_test_assert_fail_as_work(tmp_path):
    (tmp_path / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md").write_text(
        "# master\n- [ ] stay here\n", encoding="utf-8"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_expected_fail.py").write_text(
        "def test_cell():\n    assert status == \"FAIL\"\n",
        encoding="utf-8",
    )
    import subprocess
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    off = FIF.second_work_list_violations({"_check_second_list": True}, repo=tmp_path)
    assert off == [], off
