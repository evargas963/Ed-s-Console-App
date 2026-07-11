"""Institutional closure gate — adversarial + positive fixtures (AMENDMENT
INSTITUTIONAL_CLOSURE_GATE_AND_DRIFT_RECOVERY_V1). Every negative fixture is an
intentionally invalid closure packet and MUST fail the checker."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.check_institutional_closure_gate import (
    BLOCKED_VOCAB,
    CLOSED,
    SCHEMA_PATH,
    validate_ledger,
)

DIMS = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required_dimensions"]


def _proven_lane(lane_id: str = "LANE-X") -> dict:
    return {
        "lane": lane_id,
        "parent_lane": None,
        "status": CLOSED,
        "dimensions": {d: "PROVEN" for d in DIMS},
        "material_limitations": [],
        "final_sha": "a" * 40,
        "remote_ci_status": "4/4 success at cited tip",
        "next_blocker": None,
    }


def _doc(*lanes: dict) -> dict:
    return {
        "required_dimensions": DIMS,
        "lanes": list(lanes),
        "real_money_approval": "NOT_APPROVED",
    }


def test_committed_ledger_is_coherent():
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert validate_ledger(doc) == [], "committed ledger must pass its own gate"


def test_committed_ledger_backtracks_the_three_inflated_closures():
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    by = {r["lane"]: r for r in doc["lanes"]}
    for lane_id in ("ECON-01", "DOM_GUEST_SWITCH_SENTINEL", "UI-05_GUEST_COLD_FUSION_SLA"):
        row = by[lane_id]
        assert row["status"] == "NOT_CLOSED"
        drift = row["drift_recovery"]
        assert drift["prior_status"] == CLOSED
        assert drift["corrected_status"] == "NOT_CLOSED"
        assert drift["proven_sub_results_preserved"] is True
        assert row["sub_lanes"], "preserved sub-lane facts required"
    assert doc["real_money_approval"] == "NOT_APPROVED"


def test_positive_fixture_full_proof_closes():
    assert validate_ledger(_doc(_proven_lane())) == []


def test_closed_with_calibration_not_proven():
    lane = _proven_lane()
    lane["dimensions"]["CALIBRATION_VERSION_PINNING"] = "NOT_PROVEN"
    assert validate_ledger(_doc(lane))


def test_closed_with_rth_pending():
    lane = _proven_lane()
    lane["dimensions"]["RTH_PROOF"] = "RTH_REPROOF_PENDING"
    assert validate_ledger(_doc(lane))


def test_closed_with_missing_render_milestones():
    lane = _proven_lane("DOM-SENTINEL-FIXTURE")
    lane["dimensions"]["OBSERVABILITY"] = "PARTIAL"
    lane["material_limitations"] = ["cards_first_render_ms not stamped"]
    errs = validate_ledger(_doc(lane))
    assert any("OBSERVABILITY=PARTIAL" in e for e in errs)
    assert any("material_limitations" in e for e in errs)


def test_closed_parent_with_only_sub_lane_proven():
    lane = _proven_lane("PARENT-FIXTURE")
    lane["dimensions"]["END_TO_END_CORRECTNESS"] = "NOT_PROVEN"
    lane["sub_lanes"] = [{"sub_lane": "PARENT-FIXTURE-SUB", "status": CLOSED}]
    errs = validate_ledger(_doc(lane))
    assert any("sub-lane" in e for e in errs)


def test_closed_with_old_sha_ci():
    lane = _proven_lane()
    lane["final_sha"] = "b" * 40
    lane["remote_ci_status"] = "4/4 success at " + "c" * 40
    errs = validate_ledger(_doc(lane))
    assert any("does not cite the declared final SHA" in e for e in errs)


def test_closed_with_material_limitation():
    lane = _proven_lane()
    lane["material_limitations"] = ["untested correctness limitation"]
    assert validate_ledger(_doc(lane))


def test_closed_with_observed_none_but_no_prevention_lock():
    lane = _proven_lane("CONTAMINATION-FIXTURE")
    # Observation of zero incidents without a prevention lock = enforcement gap.
    lane["dimensions"]["MECHANICAL_ENFORCEMENT"] = "NOT_PROVEN"
    lane["material_limitations"] = ["contamination observed NONE but no prevention lock"]
    assert validate_ledger(_doc(lane))


def test_closed_with_representative_ticker_only():
    lane = _proven_lane()
    lane["dimensions"]["TICKER_UNIVERSALITY"] = "PARTIAL"
    assert validate_ledger(_doc(lane))


def test_not_applicable_requires_rationale():
    lane = _proven_lane()
    lane["dimensions"]["MODEL_VERSION_PINNING"] = {"status": "NOT_APPLICABLE", "rationale": ""}
    errs = validate_ledger(_doc(lane))
    assert any("NOT_APPLICABLE without" in e for e in errs)


def test_real_money_never_inferred_from_component_closure():
    doc = _doc(_proven_lane())
    doc["real_money_approval"] = "APPROVED"
    errs = validate_ledger(doc)
    assert any("real-money" in e for e in errs)


def test_blocked_vocabulary_is_complete():
    assert BLOCKED_VOCAB == {
        "NOT_PROVEN", "FAIL", "PENDING", "PARTIAL", "UNKNOWN", "NOT_AUDITED",
        "RTH_REPROOF_PENDING",
    }


def test_every_blocked_status_blocks_closure():
    for bad in sorted(BLOCKED_VOCAB):
        lane = copy.deepcopy(_proven_lane())
        lane["dimensions"]["END_TO_END_CORRECTNESS"] = bad
        assert validate_ledger(_doc(lane)), f"{bad} must block CLOSED_WITH_EVIDENCE"


def test_checker_wired_into_objective_audit_and_hardening():
    """Wiring lock: the gate must run in both required governance workflows."""
    for wf in (".github/workflows/objective-audit.yml", ".github/workflows/hardening.yml"):
        src = Path(wf).read_text(encoding="utf-8")
        assert "check_institutional_closure_gate.py" in src, f"gate not wired into {wf}"
