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


def test_checker_wired_into_hardening():
    """Wiring lock: the gate must run in the required Hardening quality workflow.
    (objective-audit.yml was retired under the ED CONSOLE SLIMMING charter; the
    Hardening quality job is the surviving required governance workflow.)"""
    src = Path(".github/workflows/hardening.yml").read_text(encoding="utf-8")
    assert "check_institutional_closure_gate.py" in src, "gate not wired into hardening.yml"


def test_exec_identity_lane_recloses_on_rth_reproof_with_history_and_open_parents():
    """Records regression (EXEC_IDENTITY_RTH_REPROOF_RECORDS_CLOSURE_V1): the
    execution-identity lane and Item 4 close ONLY with the canonical RTH reproof
    evidence, the contradiction history stays permanent, and no parent closes."""
    repo = SCHEMA_PATH.parent.parent
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    by = {r["lane"]: r for r in doc["lanes"]}
    lane = by["ML-PIPE-EXECUTION-IDENTITY-V1"]
    assert lane["status"] == CLOSED
    assert lane["dimensions"]["RTH_PROOF"] == "PROVEN"
    assert lane["dimensions"]["RUNTIME_PROOF"] == "PROVEN"
    assert lane["final_sha"] == "9d2baf410bf42b9d64714209aefd0cb3a7b21ba7"
    assert lane["final_sha"][:7] in lane["remote_ci_status"]
    assert "rth_2026-07-13_canonical_reproof.json" in lane["evidence"]["rth_reproof"]
    labels = lane["acceptance_labels"]
    for k in (
        "PRODUCTION_DECISION_IDENTITY_LINKAGE",
        "COMPLETE_DECISION_CYCLE_PERSISTENCE",
        "DECISION_ID_SINGLE_OWNERSHIP",
        "ONE_CYCLE_ONE_DECISION",
        "ASYNC_RUNTIME_ORDERING",
        "RTH_PERSISTENCE_COHERENCE",
        "RTH_REPLAY_LINKAGE",
    ):
        assert labels[k] == "PROVEN", k
    assert labels["ML_PIPE_ITEM_4"] == CLOSED
    assert by["ML-PIPE-ITEM4-FLEET-MIGRATION-V1"]["acceptance_labels"]["ML_PIPE_ITEM_4"] == CLOSED
    # Contradiction history is permanent: reopen record + resolution both present.
    drift = lane["drift_recovery"]
    assert drift["prior_status"] == CLOSED
    assert drift["corrected_status"] == "NOT_CLOSED"
    assert drift["proven_sub_results_preserved"] is True
    assert drift["evidence_packet"].endswith("rth_2026-07-13_decision_surface_contradiction.json")
    assert (repo / drift["evidence_packet"]).is_file()
    assert drift["resolution"]["restored_status"] == CLOSED
    assert (repo / "reports/exec_identity/rth_2026-07-13_canonical_reproof.json").is_file()
    # Child closure closes no parent.
    pnc = lane["preserved_non_closure"]
    assert pnc["MODEL_VERSION_PINNING_PARENT"] == "NOT_CLOSED"
    assert pnc["FULL_MODEL_STACK"] == "NOT_CLOSED"
    assert pnc["PREDICTIVE_VALIDITY"] == "NOT_PROVEN"
    # The universal-fix lock was NOT closed by the Item 4 lane; it was reconciled
    # to PROVEN only after PR #38 merged with final-main proof, and the entry must
    # keep that pre-merge history scoped in place.
    assert pnc["REPO_WIDE_UNIVERSAL_FIX_LOCK"].startswith("PROVEN (not by this lane")
    assert "NOT_PROVEN when this lane closed" in pnc["REPO_WIDE_UNIVERSAL_FIX_LOCK"]
    assert "87213d3692bd" in pnc["REPO_WIDE_UNIVERSAL_FIX_LOCK"]
    assert pnc["REAL_MONEY_APPROVAL"] == "NOT_APPROVED"
    assert doc["real_money_approval"] == "NOT_APPROVED"
    # NOT_PROVEN matrix: the MODEL_VERSION_PINNING parent label stays open while
    # recording the Item 4 reclosure in its history chain.
    matrix = json.loads(
        (repo / "governance/ML_CORRECTNESS_NOT_PROVEN_MATRIX_V2.json").read_text(encoding="utf-8")
    )
    mvp = next(l for l in matrix["labels"] if l["label"] == "MODEL_VERSION_PINNING")
    assert mvp["final_status"] == "NOT_PROVEN"
    assert "ITEM_4_RECLOSED_WITH_EVIDENCE" in mvp["fix_status"]
    assert "ITEM_4_REOPENED" in mvp["fix_status"]


def test_universal_fix_lock_closes_only_after_final_main_proof_with_open_parents():
    """Records regression (UNIVERSAL_FIX_LOCK_RECORDS_CLOSURE_AND_MISSION_RETIREMENT_V1):
    the universal-fix lock is PROVEN only against the PR #38 merge SHA with final-main
    CI cited; implementation-only or PR-only proof never suffices; no broader parent
    closes with it; the pre-merge NOT_PROVEN period stays recorded as history."""
    repo = SCHEMA_PATH.parent.parent
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    by = {r["lane"]: r for r in doc["lanes"]}
    lane = by["UNIVERSAL-FIX-IMPACT-GATE-V1"]
    assert lane["status"] == CLOSED
    # Closure is bound to the MERGE SHA (final main), not the PR head: PR-only or
    # implementation-only proof is structurally insufficient.
    assert lane["final_sha"] == "87213d3692bdf95cb66c42d715c6e1bc7a2cbb4c"
    assert lane["final_sha"] == lane["merge_sha"]
    assert lane["implementation_pr_head"] != lane["final_sha"]
    assert lane["final_sha"][:7] in lane["remote_ci_status"]
    assert "push-event" in lane["remote_ci_status"]
    labels = lane["acceptance_labels"]
    for k in (
        "STATIC_UNIVERSAL_FIX_ENFORCEMENT",
        "PREPUSH_UNIVERSAL_FIX_ENFORCEMENT",
        "CI_UNIVERSAL_FIX_ENFORCEMENT",
        "NARROW_FIX_REJECTION",
        "REPRESENTATIVE_ONLY_CLOSURE_REJECTION",
        "PARENT_FROM_CHILD_CLOSURE_REJECTION",
        "CONNECTED_PATH_INVENTORY",
        "FUTURE_OMISSION_LOCK",
        "PREPUSH_TIER_PARITY",
        "REPO_WIDE_UNIVERSAL_FIX_LOCK",
    ):
        assert labels[k] == "PROVEN", k
    # Broader parents stay open; unrelated closures stay unchanged.
    pnc = lane["preserved_non_closure"]
    assert pnc["MODEL_VERSION_PINNING_PARENT"] == "NOT_CLOSED"
    assert pnc["FULL_MODEL_STACK"] == "NOT_CLOSED"
    assert pnc["PREDICTIVE_VALIDITY"] == "NOT_PROVEN"
    assert pnc["REAL_MONEY_APPROVAL"] == "NOT_APPROVED"
    assert pnc["SCHWAB_V4_REGISTER_CLOSURE_PARENT"] == "NOT_CLOSED"
    assert by["ML-PIPE-EXECUTION-IDENTITY-V1"]["status"] == CLOSED
    assert by["ML-PIPE-EXECUTION-IDENTITY-V1"]["acceptance_labels"]["ML_PIPE_ITEM_4"] == CLOSED
    assert doc["real_money_approval"] == "NOT_APPROVED"
    # Pre-merge NOT_PROVEN history is preserved, scoped, and not rewritten.
    notes = " ".join(lane["preserved_notes"])
    assert "NOT_PROVEN throughout the pre-merge period" in notes
    assert "closure earned only after final-main proof" in notes
    # CRLF/LF determinism disclosure stays honest.
    det = lane["determinism_disclosure"]
    assert det["cross_platform_raw_byte_determinism"].startswith("NOT_PROVEN")
    # Mission-lifecycle assertions removed: the mission-authorization system
    # (governance/mission_authorization/**) was retired under the ED CONSOLE
    # SLIMMING charter (2a-mission-auth); the closure-ledger truths above stand
    # independent of that process machinery.
