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
    assert c["canonical_session_authority"]["function"] == "time_et.is_rth_ts_utc"
    dims = {d["dim"] for d in c["cohort_dimensions"]}
    for required in ("session", "opening_window", "closing_window", "day_of_week",
                     "half_day_early_close", "volatility_regime", "liquidity_regime"):
        assert required in dims


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


def test_stage2_eligible_targets_match_registry_valid_for_experiment():
    from research.stage1_target_foundation.target_registry import load_registry, targets_by_status
    reg = load_registry()
    vfe = set(targets_by_status(reg).get("VALID_FOR_EXPERIMENT", []))
    contract = _load("stage2_experiment_contract_v1.json")
    assert set(contract["eligible_targets"]["currently_eligible"]) == vfe
