"""Hard laws 1-7: negative + mutation controls at the real Stop / completion boundaries."""

from __future__ import annotations

import io
import json
from pathlib import Path

import tools.find_it_fix_it_lock as FIF
import tools.hard_law_runtime as HLR
import tools.operating_process_lock as OPL
import tools.stop_guard as sg

REPO = Path(__file__).resolve().parent.parent

RTH_HB = (
    'HARD_BLOCKER: {"type":"RTH_ONLY","assertion":"is_trading_day_et",'
    '"probe":"tools/l1_source_contract_rth_v1.py","non_rth_complete":true,'
    '"rth_observation":"authenticated_levelone_receipts"}'
)


def _box(item_id: str, status: str, body: str, checked: bool = False) -> str:
    mark = "x" if checked else " "
    return f"- [{mark}] `{item_id}` — STATUS={status} — {body}\n"


def _pass_body(msg: str) -> str:
    return (
        f"{msg} (1) symptom (2) site (3) class (4) admission "
        f"(5) ROOT: second ledger. evidence in tests."
    )


def test_add_one_close_zero_blocks_stop():
    base = _box("OD-1", "NOT_PROVEN", "old defect")
    cur = base + _box("OD-NEW", "NOT_PROVEN", "brand new defect")
    bd = HLR.compute_burn_down(base, cur)
    assert bd.new_count == 1 and bd.closed_count == 0
    v = HLR.burn_down_ratio_violations(bd, remaining_all_legitimately_blocked=False)
    assert v
    payload = {
        "_master_text": cur,
        "_baseline_text": base,
        "_applicable_ids": ["OD-NEW"],
        "_include_p01b_cluster": False,
        "_skip_second_work_list": True,
    }
    off = FIF.fix_law_blockers(payload=payload)
    assert any("burn_down_5_to_1" in a or "5*" in b or "NEW_UNRESOLVED" in b for a, b in off), off


def test_add_one_close_four_blocks_ratio():
    base = "".join(_box(f"OD-{i}", "NOT_PROVEN", f"d{i}") for i in range(1, 6))
    cur = "".join(
        _box(f"OD-{i}", "PASS", _pass_body(f"closed {i}"), checked=True) for i in range(1, 5)
    ) + _box("OD-5", "NOT_PROVEN", "still open") + _box("OD-NEW", "NOT_PROVEN", "new")
    bd = HLR.compute_burn_down(base, cur)
    assert bd.new_count == 1 and bd.closed_count == 4
    assert HLR.burn_down_ratio_violations(bd, remaining_all_legitimately_blocked=False)


def test_add_one_close_five_satisfies_ratio():
    base = "".join(_box(f"OD-{i}", "NOT_PROVEN", f"d{i}") for i in range(1, 7))
    cur = "".join(
        _box(f"OD-{i}", "PASS", _pass_body(f"closed {i}"), checked=True) for i in range(1, 6)
    ) + _box("OD-6", "NOT_PROVEN", "still open") + _box("OD-NEW", "NOT_PROVEN", "new")
    bd = HLR.compute_burn_down(base, cur)
    assert bd.new_count == 1 and bd.closed_count == 5
    assert HLR.burn_down_ratio_violations(bd, remaining_all_legitimately_blocked=False) == []


def test_zero_burn_with_deterministic_debt_blocks_stop():
    """18-pass / leftover NOT_PROVEN / 0 added / 0 closed / one RTH + one deterministic."""
    base = (
        "".join(_box(f"P-{i}", "PASS", _pass_body("ok"), checked=True) for i in range(18))
        + _box("OS-RTH", "NOT_PROVEN", f"live only {RTH_HB}")
        + _box("OS-DET", "NOT_PROVEN", "deterministic debt no blocker")
    )
    bd = HLR.compute_burn_down(base, base)
    assert bd.new_count == 0 and bd.closed_count == 0
    items = HLR.parse_master_items(base)
    app = ["OS-RTH", "OS-DET"]
    safe = HLR.safely_fixable_ids(items, app, repo=REPO)
    assert "OS-DET" in safe
    assert HLR.idle_stop_violations(bd, safely_fixable_ids=safe, machine_active_work=False)
    loc = HLR.blocker_locality_violations(items, app, repo=REPO)
    assert loc
    off = HLR.stop_hard_law_violations(
        payload={
            "_master_text": base,
            "_baseline_text": base,
            "_applicable_ids": app,
            "_include_p01b_cluster": False,
        },
        repo=REPO,
    )
    assert any("idle_stop" in a or "blocker_locality" in a for a, _ in off), off


def test_rth_blocked_item_cannot_stop_deterministic_work():
    master = (
        _box("OS-RTH", "NOT_PROVEN", f"rth {RTH_HB}")
        + _box("OS-DET", "NOT_PROVEN", "fixable now")
    )
    items = HLR.parse_master_items(master)
    v = HLR.blocker_locality_violations(items, ["OS-RTH", "OS-DET"], repo=REPO)
    assert v and "OS-DET" in v[0][1]


def test_all_applicable_externally_blocked_permits_hard_law_stop():
    master = _box("OS-RTH", "NOT_PROVEN", f"rth {RTH_HB}")
    off = HLR.stop_hard_law_violations(
        payload={
            "_master_text": master,
            "_baseline_text": master,
            "_applicable_ids": ["OS-RTH"],
            "_include_p01b_cluster": False,
        },
        repo=REPO,
    )
    assert off == [], off


def test_fourth_equivalent_attempt_blocked():
    fp = HLR.approach_fingerprint(["tools/l1_source_contract_rth_v1.py"], ["OS-A1-001"])
    attempts = [{"stable_id": "OS-A1-001", "approach_fp": fp, "outcome": "fail"}] * 3
    v = HLR.method_pivot_violations(attempts, next_fingerprint=fp, stable_id="OS-A1-001")
    assert v and "CHANGING METHOD" in v[0][1]
    other = HLR.approach_fingerprint(["tests/test_other.py"], ["OS-A1-001"])
    assert HLR.method_pivot_violations(attempts, next_fingerprint=other, stable_id="OS-A1-001") == []
    off = FIF.fix_law_blockers(payload={
        "_method_attempts": attempts,
        "_next_approach_fp": fp,
        "_stable_failure_id": "OS-A1-001",
        "_master_text": _box("OS-A1-001", "NOT_PROVEN", f"x {RTH_HB}"),
        "_baseline_text": _box("OS-A1-001", "NOT_PROVEN", f"x {RTH_HB}"),
        "_applicable_ids": ["OS-A1-001"],
        "_include_p01b_cluster": False,
        "_skip_second_work_list": True,
    })
    assert any("method_pivot" in a or "CHANGING METHOD" in b for a, b in off), off


def test_required_ci_pending_and_red_and_wrong_sha_block_completion():
    text = "HARDENING_GATES = PASS and PYTEST_FULL = PASS — merge-ready."
    head = "aaa111"
    pending = HLR.required_ci_violations(
        text, head_sha=head, ci_status={"sha": head, "checks": {"hardening": "SUCCESS", "pytest-full": "PENDING"}},
    )
    assert pending
    red = HLR.required_ci_violations(
        text, head_sha=head, ci_status={"sha": head, "checks": {"hardening": "FAILURE", "pytest-full": "SUCCESS"}},
    )
    assert red
    prior = HLR.required_ci_violations(
        text, head_sha=head, ci_status={"sha": "bbb222", "checks": {"hardening": "SUCCESS", "pytest-full": "SUCCESS"}},
    )
    assert prior
    none = HLR.required_ci_violations(text, head_sha=head, ci_status=None)
    assert none
    v = OPL.completion_claim_violations(
        text, REPO, ci_status={"sha": head, "checks": {"hardening": "PENDING", "pytest-full": "SUCCESS"}},
    )
    assert any("required CI" in x for x in v)


def test_agent_env_off_does_not_disable_without_operator_go(monkeypatch):
    monkeypatch.setenv("ED_STOP_GUARD", "off")
    monkeypatch.setenv("ED_PROCESS_LOCK_GUARD", "off")
    assert HLR.env_guard_is_disabled("ED_STOP_GUARD") is False
    assert HLR.env_guard_is_disabled("ED_PROCESS_LOCK_GUARD") is False
    monkeypatch.setattr(HLR, "operator_guard_escape_granted", lambda name, repo=None: True)
    assert HLR.env_guard_is_disabled("ED_STOP_GUARD") is True


def test_stop_reentry_does_not_bypass_hard_laws():
    assert HLR.stop_reentry_bypasses_hard_laws({"stop_hook_active": True}) is False
    master = (
        _box("OS-RTH", "NOT_PROVEN", f"rth {RTH_HB}")
        + _box("OS-DET", "NOT_PROVEN", "deterministic")
    )
    payload = {
        "stop_hook_active": True,
        "_master_text": master,
        "_baseline_text": master,
        "_applicable_ids": ["OS-RTH", "OS-DET"],
        "_include_p01b_cluster": False,
        "last_assistant_text": "wrapping up",
    }
    first = FIF.fix_law_blockers(payload=payload)
    second = FIF.fix_law_blockers(payload=payload)
    assert first and second
    assert any("idle_stop" in a or "blocker_locality" in a for a, _ in first)
    assert any("idle_stop" in a or "blocker_locality" in a for a, _ in second)


def test_stop_guard_reentry_still_blocks_when_hard_law_persists(monkeypatch):
    master = (
        _box("OS-RTH", "NOT_PROVEN", f"rth {RTH_HB}")
        + _box("OS-DET", "NOT_PROVEN", "deterministic")
    )
    payload = {
        "stop_hook_active": True,
        "_master_text": master,
        "_baseline_text": master,
        "_applicable_ids": ["OS-RTH", "OS-DET"],
        "_include_p01b_cluster": False,
        "last_assistant_text": "wrapping up",
    }
    monkeypatch.setattr(sg, "faucet_violations", lambda: [])
    monkeypatch.setattr(sg, "freshness_blockers", lambda: [])
    monkeypatch.setattr(sg, "close_contract_blockers", lambda: [])
    monkeypatch.setattr(sg.sys, "stdin", io.StringIO(json.dumps(payload)))
    assert sg.main() == 2


def test_mutation_removing_ratio_lets_illegal_burn_through(monkeypatch):
    base = _box("OD-1", "NOT_PROVEN", "old")
    cur = base + _box("OD-NEW", "NOT_PROVEN", "new")
    bd = HLR.compute_burn_down(base, cur)
    assert HLR.burn_down_ratio_violations(bd, remaining_all_legitimately_blocked=False)
    monkeypatch.setattr(HLR, "BURN_DOWN_RATIO", 0)
    assert HLR.burn_down_ratio_violations(
        bd, remaining_all_legitimately_blocked=False, ratio=HLR.BURN_DOWN_RATIO
    ) == []
    # restore is automatic; prove the Stop boundary uses the live ratio
    monkeypatch.undo()
    off = FIF.fix_law_blockers(payload={
        "_master_text": cur,
        "_baseline_text": base,
        "_applicable_ids": ["OD-NEW"],
        "_include_p01b_cluster": False,
        "_skip_second_work_list": True,
    })
    assert any("NEW_UNRESOLVED" in b or "burn_down" in a for a, b in off), off


def test_rename_and_na_do_not_count_as_closes():
    base = _box("OD-OLD", "NOT_PROVEN", "same body text here")
    renamed = _box("OD-NEWNAME", "NOT_PROVEN", "same body text here")
    bd = HLR.compute_burn_down(base, renamed)
    assert bd.closed_count == 0
    assert bd.rename_launder
    na = _box("OD-OLD", "NOT_APPLICABLE", "same body text here", checked=True)
    bd2 = HLR.compute_burn_down(base, na)
    assert bd2.closed_count == 0
    assert bd2.na_inflation


def test_parent_close_from_child_only_is_blocked():
    old = _box("OD-P", "NOT_PROVEN", "parent defect")
    new = _box("OD-P", "PASS", "child fixture passed on SPY only", checked=True)
    assert FIF.master_closure_missing_root_cause(old, new)
