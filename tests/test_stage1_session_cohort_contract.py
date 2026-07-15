"""Stage 1 session/cohort + cost-model + Stage 2 contract locks (research-only)."""
from __future__ import annotations

import json
from pathlib import Path

from research.stage1_target_foundation.rth_integrity_audit import audit

GOV = Path(__file__).resolve().parents[1] / "governance" / "research" / "stage1_target_label_foundation"


def _load(name: str) -> dict:
    return json.loads((GOV / name).read_text(encoding="utf-8"))


def test_session_cohort_contract_wellformed():
    c = _load("session_cohort_contract_v1.json")
    assert c["schema"] == "STAGE1_SESSION_COHORT_CONTRACT"
    # canonical authority is the CT + calendar module, not the ET helper
    assert c["canonical_session_authority"]["function"] == \
        "research/stage1_target_foundation/ct_session.py::classify_session"
    assert c["canonical_time_binding"]["application_timezone"].startswith("America/Chicago")
    assert "08:30-15:00 Central" in c["canonical_time_binding"]["rth_label_ct"]
    dims = {d["dim"] for d in c["cohort_dimensions"]}
    for required in ("session", "opening_window", "closing_window", "day_of_week",
                     "half_day_early_close", "volatility_regime", "liquidity_regime"):
        assert required in dims


def test_session_cohort_contract_marks_et_helper_insufficient():
    """time_et.is_rth_ts_utc must be disclosed as INSUFFICIENT (no holiday/half-day)."""
    c = _load("session_cohort_contract_v1.json")
    assert "INSUFFICIENT" in c["canonical_session_authority"]["helper_sufficiency"]


def test_rth_integrity_contradiction_is_detected_and_disclosed():
    """The detector must find the live stored-clock RTH cohort sites AND the
    contract must disclose them; both must agree the contradiction is OPEN."""
    a = audit()
    assert a["canonical_ts_utc_authority_present"] is True
    assert a["contradiction_present"] is True
    assert a["live_cohort_stored_clock_rth_sites"], "expected live stored-clock RTH sites"
    # both db.py and audit_model_readiness.py must appear
    joined = " ".join(a["live_cohort_stored_clock_rth_sites"])
    assert "db.py" in joined and "audit_model_readiness.py" in joined
    contract = _load("session_cohort_contract_v1.json")
    assert contract["rth_integrity_contradiction"]["status"].startswith("OPEN")


def test_cost_model_registry_wellformed_and_economic_rule():
    c = _load("cost_model_registry_v1.json")
    assert c["schema"] == "STAGE1_COST_MODEL_REGISTRY"
    assert "NONE" in c["models"]
    assert "COST_V1_UNDERLYING_SPY" in c["models"]
    # every non-NONE model declares a cost kind
    for mid, m in c["models"].items():
        assert "kind" in m, mid


def test_stage2_contract_design_only_and_names_missing_pieces():
    c = _load("stage2_experiment_contract_v1.json")
    assert c["schema"] == "STAGE1_STAGE2_EXPERIMENT_CONTRACT"
    assert "NOT EXECUTED" in c["authority"]
    # leakage discipline must require purge + embargo and flag they are missing
    sl = c["splits_and_leakage_control"]
    assert "REQUIRED" in sl["purge"] and "REQUIRED" in sl["embargo"]
    assert "NOT implemented" in sl["MISSING_TODAY"]
    # shuffle control and always-WAIT baselines are mandatory
    assert any("shuffle" in b for b in c["baselines_required"])
    assert any("always_WAIT" in b for b in c["baselines_required"])
    # stop if nothing beats baselines after costs
    assert any("after costs" in s.lower() for s in c["stop_conditions"])


def test_stage2_embargo_uses_true_61_minute_span():
    """Objective E: embargo must use the true (N+1)-minute span, 61 min for 60c."""
    c = _load("stage2_experiment_contract_v1.json")
    assert c["label_span_semantics"]["realized_span_minutes_by_horizon"]["60c"] == 61
    assert "61" in c["splits_and_leakage_control"]["embargo"]
    assert "NOT 60 bars" in c["splits_and_leakage_control"]["embargo"]


def test_stage2_multiple_comparison_controls_present():
    """Objective F: FWER/FDR, White/Hansen SPA, deflated Sharpe, seeds, MCC,
    class-imbalance policy, model-selection log, no post-hoc switching."""
    c = _load("stage2_experiment_contract_v1.json")
    mcc = c["multiple_comparison_control"]
    assert "Holm" in mcc["fwer_or_fdr"] or "Benjamini" in mcc["fwer_or_fdr"]
    assert "Reality Check" in mcc["data_snooping_tests"] or "SPA" in mcc["data_snooping_tests"]
    assert "Deflated Sharpe" in mcc["deflated_sharpe"]
    assert "seeds" in mcc and "SMOTE" in mcc["class_imbalance_policy"]
    assert "model_selection_log" in mcc
    pm = c["preregistered_primary_metric"]
    assert "MCC" in pm["classification"]
    assert "FORBIDDEN" in pm["no_post_hoc_switching"]
    # nested walk-forward + untouched final holdout
    assert "NESTED" in c["splits_and_leakage_control"]["temporal_split"].upper()
    assert "final_holdout" in c["splits_and_leakage_control"]
    assert "ONCE" in c["splits_and_leakage_control"]["final_holdout"].upper()


def test_stage2_eligibility_is_experiment_eligible_and_empty(monkeypatch):
    """Objective I: Stage 2 eligibility == registry EXPERIMENT_ELIGIBLE via the
    fail-closed selection function; currently empty; contract agrees."""
    from research.stage1_target_foundation.target_registry import (
        load_registry, stage2_eligible_targets, targets_by_status,
    )
    reg = load_registry()
    eligible = stage2_eligible_targets(reg)
    assert eligible == []
    assert targets_by_status(reg).get("EXPERIMENT_ELIGIBLE", []) == []
    contract = _load("stage2_experiment_contract_v1.json")
    assert contract["eligible_targets"]["currently_eligible"] == eligible
    # the rule must name the fail-closed selection function
    assert "stage2_eligible_targets" in contract["eligible_targets"]["selection_function"]


def test_stage2_forbids_non_eligible_entrant_mechanically():
    """A causally-proven-but-not-eligible target must be rejected by the selection
    function even if a caller tries to force it in (fail-closed)."""
    import copy
    from research.stage1_target_foundation.target_registry import (
        load_registry, stage2_eligible_targets,
    )
    reg = copy.deepcopy(load_registry())
    # promote a CAUSAL_CONTRACT_PROVEN target's STATUS only (gates still fail)
    for t in reg["targets"]:
        if t["target_id"] == "outcome_H_pts_raw":
            t["promotion_status"] = "EXPERIMENT_ELIGIBLE"
            break
    # selection recomputes eligibility from gates -> still excluded
    assert "outcome_H_pts_raw" not in stage2_eligible_targets(reg)
