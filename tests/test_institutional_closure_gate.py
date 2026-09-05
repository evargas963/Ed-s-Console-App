"""Institutional closure ledger — adversarial + positive fixtures (AMENDMENT
INSTITUTIONAL_CLOSURE_GATE_AND_DRIFT_RECOVERY_V1; RC-516 retired-lane and
cited-mechanism rules). Every negative fixture is an intentionally invalid closure packet
and MUST fail the validator."""

from __future__ import annotations

import copy
import json

from tools.check_institutional_closure_gate import (
    BLOCKED_VOCAB,
    CLOSED,
    RETIRED,
    SCHEMA_PATH,
    validate_ledger,
)
from tools.check_institutional_correctness import CHECKS

DIMS = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required_dimensions"]
REPO = SCHEMA_PATH.parent.parent


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


# TEST_SYSTEM_REHAB_V2 final remediation: `test_committed_ledger_is_coherent` was REMOVED --
# an exact live-tree duplicate of the enforced check that reads this SAME SCHEMA_PATH and
# calls this SAME validate_ledger on every run (RC-516: that check is
# `institutional_closure_ledger` inside tools/check_institutional_correctness.py, run by the
# required Hardening delta gate). Correct architecture: pytest fault/mutation-tests the
# validator's LOGIC against synthetic input; the gate runs it against the real repository.


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


def test_validator_is_the_enforced_check_of_the_one_gate():
    """Wiring lock (RC-516): the validator runs as the ENFORCED check
    `institutional_closure_ledger` inside the ONE institutional gate, which the required
    Hardening delta gate runs on every PR. There is no separate CI step — a second
    mechanism for the same question was exactly what the consolidation removed."""
    registered = {name: enforced for name, _fn, enforced in CHECKS}
    assert registered.get("institutional_closure_ledger") is True
    hardening = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert "check_institutional_closure_gate.py" not in hardening, (
        "the standalone step is back — two mechanisms for one question")
    assert "check_delta_adds_no_debt.py" in hardening


# ── RC-516: a closure may rest only on mechanisms that exist ─────────────────────────

def test_closed_lane_citing_a_missing_mechanism_fails(tmp_path):
    lane = _proven_lane()
    lane["evidence"] = {"engine": "tools/this_gate_was_deleted.py"}
    errs = validate_ledger(_doc(lane), root=tmp_path)
    assert len(errs) == 1 and "tools/this_gate_was_deleted.py" in errs[0] and "retire the lane" in errs[0]


def test_closed_lane_citing_an_existing_mechanism_passes(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "live_gate.py").write_text("x = 1\n", encoding="utf-8")
    lane = _proven_lane()
    lane["evidence"] = {"engine": "tools/live_gate.py"}
    assert validate_ledger(_doc(lane), root=tmp_path) == []


def test_open_lane_claiming_proven_enforcement_by_a_missing_mechanism_fails(tmp_path):
    lane = _proven_lane()
    lane["status"] = "NOT_CLOSED"
    lane["dimensions"]["END_TO_END_CORRECTNESS"] = "NOT_PROVEN"
    lane["evidence"] = {"engine": "tools/this_gate_was_deleted.py"}
    errs = validate_ledger(_doc(lane), root=tmp_path)
    assert any("MECHANICAL_ENFORCEMENT=PROVEN while citing" in e for e in errs), errs


def _retired_lane() -> dict:
    lane = _proven_lane("RETIRED-FIXTURE")
    lane["status"] = RETIRED
    lane["retired"] = {
        "date": "2026-09-04", "retired_in": "abc1234", "reason": "mechanism deleted",
        "current_owner": "tools/check_institutional_correctness.py",
        "historical_dimensions": lane.pop("dimensions"),
        "historical_record": {"final_sha": lane.pop("final_sha"),
                              "remote_ci_status": lane.pop("remote_ci_status"),
                              "engine": "tools/this_gate_was_deleted.py"},
    }
    return lane


def test_retired_lane_preserves_history_and_asserts_nothing(tmp_path):
    """History may name deleted mechanisms; a RETIRED lane is history, not a claim."""
    assert validate_ledger(_doc(_retired_lane()), root=tmp_path) == []


def test_retired_lane_requires_its_record():
    lane = _retired_lane()
    lane["retired"].pop("current_owner")
    errs = validate_ledger(_doc(lane))
    assert any("missing 'current_owner'" in e for e in errs), errs
    lane = _retired_lane()
    lane.pop("retired")
    assert any("without a `retired` record" in e for e in validate_ledger(_doc(lane)))


def test_retired_lane_may_not_keep_current_authority_fields():
    lane = _retired_lane()
    lane["dimensions"] = lane["retired"]["historical_dimensions"]
    lane["final_sha"] = "a" * 40
    errs = validate_ledger(_doc(lane))
    assert any("still carries `dimensions`" in e for e in errs)
    assert any("final_sha/remote_ci_status" in e for e in errs)


def test_unknown_status_is_refused():
    lane = _proven_lane()
    lane["status"] = "CLOSED"
    errs = validate_ledger(_doc(lane))
    assert any("unknown status 'CLOSED'" in e for e in errs)


def test_the_three_stale_lanes_are_retired_history_on_the_committed_ledger():
    """Records regression (RC-516): UNIVERSAL-FIX-IMPACT-GATE-V1, GOV-GATE-PARITY-01 and
    GOV-BRANCH-AUTHORIZATION-V1 cited enforcement that was deleted in the 2026-07 slimming
    while reading CLOSED_WITH_EVIDENCE / MECHANICAL_ENFORCEMENT=PROVEN. They are RETIRED:
    their historical dimensions and evidence are preserved verbatim, they name the current
    owner of the outcome, and every mechanism they name as CURRENT exists on the tree."""
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    by = {r["lane"]: r for r in doc["lanes"]}
    for lane_id in ("UNIVERSAL-FIX-IMPACT-GATE-V1", "GOV-GATE-PARITY-01",
                    "GOV-BRANCH-AUTHORIZATION-V1"):
        lane = by[lane_id]
        assert lane["status"] == RETIRED, lane_id
        rec = lane["retired"]
        assert rec["historical_dimensions"]["MECHANICAL_ENFORCEMENT"] == "PROVEN", (
            "history must be preserved verbatim, not rewritten")
        assert "dimensions" not in lane and "final_sha" not in lane
        assert rec["reason"] and rec["current_owner"]
    uf = by["UNIVERSAL-FIX-IMPACT-GATE-V1"]["retired"]
    assert uf["historical_record"]["final_sha"] == "87213d3692bdf95cb66c42d715c6e1bc7a2cbb4c"
    assert "check_universal_fix_impact_gate.py" in uf["historical_record"]["evidence"]["engine"]
    assert not (REPO / "tools" / "check_universal_fix_impact_gate.py").exists()
    for owner in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                  "institutional_closure_ledger"):
        assert owner in uf["current_owner"]
    registered = {name for name, _fn, enforced in CHECKS if enforced}
    assert {"no_superseded_path_survives", "changed_computation_leaves_no_twin",
            "institutional_closure_ledger"} <= registered
    # The execution-identity lane no longer asserts the deleted lock as PROVEN.
    ei = by["ML-PIPE-EXECUTION-IDENTITY-V1"]
    assert ei["status"] == CLOSED
    assert ei["preserved_non_closure"]["REPO_WIDE_UNIVERSAL_FIX_LOCK"].startswith("RETIRED")
    assert "87213d3692bd" in ei["preserved_non_closure"]["REPO_WIDE_UNIVERSAL_FIX_LOCK"]
    # And the committed ledger passes the real validator against the real tree.
    assert validate_ledger(doc, root=REPO) == []


def test_exec_identity_lane_recloses_on_rth_reproof_with_history_and_open_parents():
    """Records regression (EXEC_IDENTITY_RTH_REPROOF_RECORDS_CLOSURE_V1): the
    execution-identity lane and Item 4 close ONLY with the canonical RTH reproof
    evidence, the contradiction history stays permanent, and no parent closes."""
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
    assert (REPO / drift["evidence_packet"]).is_file()
    assert drift["resolution"]["restored_status"] == CLOSED
    assert (REPO / "reports/exec_identity/rth_2026-07-13_canonical_reproof.json").is_file()
    # Child closure closes no parent.
    pnc = lane["preserved_non_closure"]
    assert pnc["MODEL_VERSION_PINNING_PARENT"] == "NOT_CLOSED"
    assert pnc["FULL_MODEL_STACK"] == "NOT_CLOSED"
    assert pnc["PREDICTIVE_VALIDITY"] == "NOT_PROVEN"
    assert pnc["REAL_MONEY_APPROVAL"] == "NOT_APPROVED"
    assert doc["real_money_approval"] == "NOT_APPROVED"
    # NOT_PROVEN matrix: the MODEL_VERSION_PINNING parent label stays open while
    # recording the Item 4 reclosure in its history chain.
    matrix = json.loads(
        (REPO / "governance/ML_CORRECTNESS_NOT_PROVEN_MATRIX_V2.json").read_text(encoding="utf-8")
    )
    mvp = next(l for l in matrix["labels"] if l["label"] == "MODEL_VERSION_PINNING")
    assert mvp["final_status"] == "NOT_PROVEN"
    assert "ITEM_4_RECLOSED_WITH_EVIDENCE" in mvp["fix_status"]
    assert "ITEM_4_REOPENED" in mvp["fix_status"]
    # RC-516: the matrix no longer presents a deleted test file as a landed lock.
    assert "tests/test_check_fix_everything_we_touch.py" not in json.dumps(matrix)
