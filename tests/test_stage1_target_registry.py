"""Stage 1 target registry invariants (research foundation, no production effect).

Locks the SEPARATED status model (schema_version 2): causal reconstructability
(CAUSAL_CONTRACT_PROVEN) does NOT confer Stage 2 eligibility; EXPERIMENT_ELIGIBLE
requires every applicable readiness gate to pass; LEGACY_BASELINE_ONLY is the
deployed label and may never be eligible; the Stage 2 selection is fail-closed.
"""
from __future__ import annotations

import copy

import pytest

from research.stage1_target_foundation.target_registry import (
    STATUS_ENUM,
    compute_eligible,
    load_registry,
    stage2_eligible_targets,
    targets_by_status,
    validate_registry,
)


def test_committed_registry_is_valid():
    reg = load_registry()
    errs = validate_registry(reg)
    assert errs == [], "committed target_registry_v1.json invalid:\n" + "\n".join(errs)


def test_schema_version_is_2_separated_model():
    reg = load_registry()
    assert reg["schema_version"] == 2
    assert set(reg["status_enum"]) == STATUS_ENUM


def test_no_target_is_production_approved():
    """HARD Stage 1 rule: nothing may be PRODUCTION_APPROVED."""
    reg = load_registry()
    by_status = targets_by_status(reg)
    assert by_status.get("PRODUCTION_APPROVED", []) == []
    for st in by_status:
        assert st in STATUS_ENUM


def test_zero_targets_are_experiment_eligible():
    """Truthful Stage 1 classification: NOTHING is experiment-eligible."""
    reg = load_registry()
    assert targets_by_status(reg).get("EXPERIMENT_ELIGIBLE", []) == []
    assert stage2_eligible_targets(reg) == []


def test_legacy_label_is_baseline_only_not_eligible():
    reg = load_registry()
    t = next(t for t in reg["targets"] if t["target_id"] == "outcome_H_ternary_legacy")
    assert t["promotion_status"] == "LEGACY_BASELINE_ONLY"
    assert compute_eligible(t["experiment_readiness"]) is False


def test_movement_and_conditional_are_not_eligible():
    reg = load_registry()
    for tid in ("outcome_move_H_binary", "outcome_dir_H_conditional"):
        t = next(t for t in reg["targets"] if t["target_id"] == tid)
        assert t["promotion_status"] == "CAUSAL_CONTRACT_PROVEN"
        assert compute_eligible(t["experiment_readiness"]) is False


def test_causal_proven_does_not_imply_eligible():
    """The core redesign: a causally-proven target with a failing gate is NOT
    eligible, and the validator rejects mislabelling it EXPERIMENT_ELIGIBLE."""
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["target_id"] == "outcome_H_pts_raw")
    assert t["experiment_readiness"]["causal_contract_proven"] is True
    assert compute_eligible(t["experiment_readiness"]) is False
    t["promotion_status"] = "EXPERIMENT_ELIGIBLE"  # lie: gates still fail
    errs = validate_registry(reg)
    assert any("EXPERIMENT_ELIGIBLE requires all readiness gates" in e for e in errs)


def test_eligible_target_must_carry_experiment_eligible_status():
    """If all gates pass but the status is understated, the validator rejects it
    (no silently-eligible target hiding under a lesser status)."""
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["target_id"] == "outcome_H_pts_raw")
    for g in t["experiment_readiness"]["gates"].values():
        if g.get("applicable") is not False:
            g["ok"] = True
    t["experiment_readiness"]["eligible"] = True
    # status left at CAUSAL_CONTRACT_PROVEN -> must be rejected
    errs = validate_registry(reg)
    assert any("MUST carry EXPERIMENT_ELIGIBLE" in e for e in errs)


def test_eligible_declared_flag_must_match_computed():
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["target_id"] == "outcome_H_pts_raw")
    t["experiment_readiness"]["eligible"] = True  # gates still fail
    errs = validate_registry(reg)
    assert any("disagrees with computed eligibility" in e for e in errs)


def test_legacy_cannot_be_eligible():
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["promotion_status"] == "LEGACY_BASELINE_ONLY")
    for g in t["experiment_readiness"]["gates"].values():
        if g.get("applicable") is not False:
            g["ok"] = True
    t["experiment_readiness"]["eligible"] = True
    errs = validate_registry(reg)
    assert any("LEGACY_BASELINE_ONLY must not be experiment-eligible" in e for e in errs)


def test_candidate_cannot_be_eligible():
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["target_id"] == "cost_adjusted_forward_return")
    t["experiment_readiness"]["causal_contract_proven"] = True
    for g in t["experiment_readiness"]["gates"].values():
        if g.get("applicable") is not False:
            g["ok"] = True
    t["experiment_readiness"]["eligible"] = True
    errs = validate_registry(reg)
    assert any("cannot be experiment-eligible" in e for e in errs)


def test_causal_status_requires_causal_proven_flag():
    reg = copy.deepcopy(load_registry())
    t = next(t for t in reg["targets"] if t["promotion_status"] == "CAUSAL_CONTRACT_PROVEN")
    t["experiment_readiness"]["causal_contract_proven"] = False
    errs = validate_registry(reg)
    assert any("requires causal_contract_proven=true" in e for e in errs)


def test_production_approved_entry_is_rejected():
    reg = copy.deepcopy(load_registry())
    reg["targets"][0]["promotion_status"] = "PRODUCTION_APPROVED"
    errs = validate_registry(reg)
    assert any("FORBIDDEN in Stage 1" in e for e in errs)


def test_economic_target_without_cost_model_is_rejected():
    reg = copy.deepcopy(load_registry())
    for t in reg["targets"]:
        if "cost_adjusted" in t["target_id"] or "cost_threshold" in t.get("family", ""):
            t["cost_model_version"] = "NONE"
            break
    errs = validate_registry(reg)
    assert any("must name a versioned cost model" in e for e in errs)


def test_undeclared_cost_or_barrier_version_is_rejected():
    reg = copy.deepcopy(load_registry())
    reg["targets"][0]["cost_model_version"] = "COST_VNONEXISTENT"
    errs = validate_registry(reg)
    assert any("not declared in cost_model_versions" in e for e in errs)


def test_non_canonical_horizon_is_rejected():
    reg = copy.deepcopy(load_registry())
    for t in reg["targets"]:
        if t["allowed_horizons"]:
            t["allowed_horizons"] = t["allowed_horizons"] + ["3c"]
            break
    errs = validate_registry(reg)
    assert any("non-canonical" in e for e in errs)


def test_horizon_span_must_be_n_plus_one(monkeypatch):
    """Objective E: nominal Nc realizes N+1 minutes; a wrong span is rejected."""
    reg = copy.deepcopy(load_registry())
    reg["horizon_span_semantics"]["realized_span_minutes_by_horizon"]["60c"] = 60
    errs = validate_registry(reg)
    assert any("realized span must be 61 minutes" in e for e in errs)


def test_per_target_span_mismatch_is_rejected():
    reg = copy.deepcopy(load_registry())
    for t in reg["targets"]:
        if "60c" in (t.get("allowed_horizons") or []):
            t["realized_span_minutes_by_horizon"]["60c"] = 60
            break
    errs = validate_registry(reg)
    assert any("realized_span_minutes_by_horizon[60c] must be 61" in e for e in errs)


def test_registry_covers_the_four_existing_production_and_movement_targets():
    reg = load_registry()
    ids = {t["target_id"] for t in reg["targets"]}
    for required in (
        "outcome_H_ternary_legacy",
        "outcome_dir_H_conditional",
        "outcome_move_H_binary",
        "outcome_H_pts_raw",
    ):
        assert required in ids, f"registry missing existing target {required}"


@pytest.mark.parametrize("target_id", [
    "outcome_H_ternary_legacy", "outcome_dir_H_conditional", "outcome_move_H_binary",
])
def test_existing_labels_disclose_not_approved(target_id):
    """Existing/deployed labels must carry a truthful NOT_APPROVED limitation."""
    reg = load_registry()
    t = next(t for t in reg["targets"] if t["target_id"] == target_id)
    lim = " ".join(t["known_limitations"]).upper()
    assert "NOT_APPROVED" in lim or "FAIL" in lim or "PLACEHOLDER" in lim
