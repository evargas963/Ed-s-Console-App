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
    return FIF.active_obligation_offenders(
        text,
        today=TODAY,
        mission=MISSION,
        dirty_paths=kwargs.pop("dirty_paths", []),
        presented_ids=kwargs.pop("presented_ids", None),
        repo=kwargs.pop("repo", ROOT),
    )


def test_omission_negative_control_incomplete_active_view_blocks():
    """Material defect in the RC log, omitted from the view the gate reads → BLOCK."""
    rows = [
        _row(
            "RC-9001",
            extra_defect="CLASS:ACTIVE mission_id: ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1",
            extra_fix="IN PROGRESS",
        ),
        _row(
            "RC-9002",
            extra_defect="CLASS:ACTIVE",
            extra_fix="IN PROGRESS",
        ),
    ]
    presented = ["RC-9001"]  # syntactically valid, incomplete
    off = _offenders(rows, presented_ids=presented)
    assert off, "incomplete active view must BLOCK"
    assert any(rid == "RC-9002" and "omitted" in why for rid, why in off)


def test_new_discovery_cannot_be_parked_as_passive():
    rows = [
        _row("RC-9003", extra_defect="CLASS:PASSIVE", extra_fix="queued for later"),
    ]
    off = _offenders(rows, presented_ids=None)
    assert any("NEW MATERIAL DISCOVERY" in why for _, why in off)


def test_passive_implicated_by_dirty_product_becomes_active():
    rows = [
        _row(
            "RC-9004",
            opened="2026-07-01",
            extra_defect="CLASS:PASSIVE order_flow_engine.py composite",
            extra_fix="historical note",
        ),
    ]
    off = _offenders(rows, dirty_paths=["order_flow_engine.py"], presented_ids=None)
    assert off, "implicated PASSIVE must become ACTIVE and then BLOCK until remediating"
    assert any(rid == "RC-9004" for rid, _ in off)


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


def test_fake_rth_blocker_without_probe_blocks():
    rows = [
        _row(
            "RC-9006",
            extra_defect="CLASS:ACTIVE",
            extra_fix="HARD_BLOCKER: RTH_ONLY assertion=tape_same_ms_loss probe=does_not_exist.py non_rth_complete=true rth_observation=live",
        ),
    ]
    off = _offenders(rows, presented_ids=None)
    assert any("RTH_ONLY" in why and "probe" in why for _, why in off)


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
    off = FIF.active_obligation_offenders(
        "\n".join(rows),
        today=TODAY,
        mission=MISSION,
        dirty_paths=[],
        presented_ids=None,
        repo=tmp_path,
    )
    assert any("not designed to test" in why for _, why in off)


def test_turn_budget_is_never_a_blocker():
    rows = [
        _row(
            "RC-9008",
            extra_defect="CLASS:ACTIVE",
            extra_fix="blocked by turn budget and next pass",
        ),
    ]
    off = _offenders(rows, presented_ids=None)
    assert any("never a blocker" in why for _, why in off)


def test_remediated_rc_plus_empty_command_blocks():
    rows = [
        _row(
            "RC-9009",
            extra_defect="CLASS:ACTIVE",
            extra_fix="FIXED: renamed the field. command: ``",
        ),
    ]
    off = _offenders(rows, presented_ids=None)
    assert off, "RC + empty command must not count as remediating"


def test_remediated_with_exercising_test_passes():
    rows = [
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
    assert off == [], off


def test_derived_active_defects_json_omission_blocks(tmp_path, monkeypatch):
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
    )
    assert any("omitted" in why for _, why in off)


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
