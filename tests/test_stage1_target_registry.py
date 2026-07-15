"""Stage 1 target registry invariants (research foundation, no production effect)."""
from __future__ import annotations

import copy

import pytest

from research.stage1_target_foundation.target_registry import (
    load_registry,
    targets_by_status,
    validate_registry,
)


def test_committed_registry_is_valid():
    reg = load_registry()
    errs = validate_registry(reg)
    assert errs == [], "committed target_registry_v1.json invalid:\n" + "\n".join(errs)


def test_no_target_is_production_approved():
    """HARD Stage 1 rule: nothing may be PRODUCTION_APPROVED."""
    reg = load_registry()
    by_status = targets_by_status(reg)
    assert by_status.get("PRODUCTION_APPROVED", []) == []
    # and every declared status is in the enum
    for st in by_status:
        assert st in {"CANDIDATE", "VALID_FOR_EXPERIMENT", "INVALID", "RETIRED"}


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


def test_valid_for_experiment_requires_proven_causal_contract():
    reg = copy.deepcopy(load_registry())
    for t in reg["targets"]:
        if t["promotion_status"] == "VALID_FOR_EXPERIMENT":
            t["causal_availability"] = "assumed fine"
            break
    errs = validate_registry(reg)
    assert any("VALID_FOR_EXPERIMENT requires causal_availability" in e for e in errs)


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
