from __future__ import annotations

from lifecycle_rule_core import LIFECYCLE_RULE_CORE_VERSION
from v2_decision.a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES
from v2_decision.module_a_adapter import build_module_a_a1_decision


def _winner() -> dict:
    return {
        "expression": "500 CALL",
        "strike": 500.0,
        "side": "CALL",
        "composite_score": 8.25,
        "chain_row": {
            "symbol": "SPY260505C00500000",
            "bid": 1.2,
            "ask": 1.3,
            "delta": 0.52,
            "gamma": 0.08,
            "theta": -0.18,
            "vega": 0.02,
            "volatility": 0.22,
            "totalVolume": 1200,
            "openInterest": 4300,
            "expirationDate": "2026-05-05",
            "quoteTimeInLong": 1778018399000,
            "tradeTimeInLong": 1778018398500,
        },
    }


def _ms(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "selected_exp": "2026-05-05",
        "call_option_expiry": "2026-05-05",
        "dte_warn": "0DTE",
        "call_signal": "long",
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.64,
        "fusion_confidence": "high",
        "is_no_trade": False,
        "execution_mode": "STANDARD",
        "rec_strike": 500.0,
        "rec_side": "CALL",
        "call_option_right": "CALL",
        "liq_ok": True,
        "spread": 0.1,
        "ratio": 6.5,
        "vol_oi": 0.279,
        "spot": 499.5,
        "mins_to_close": 120.0,
        "decision_time_ms": 1778018400000,
        "option_chain_selection_proof": {
            "status": "ok",
            "winner": _winner(),
            "liquidity_summary": {"any_candidate_passed_liq_gate": True},
        },
        "contract_context": "SPY 2026-05-05 500C - 0DTE - mid~1.25",
        "stop": 498.5,
        "target": 503.0,
        "target2": 505.0,
    }
    base.update(overrides)
    return base


def _a2(ms: dict | None = None) -> dict:
    decision = build_module_a_a1_decision(ms or _ms())
    return decision["expression_profiles"]["A2"]


def test_a2_lifecycle_sidecar_is_nested_under_lifecycle():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 148 - sidecar output exists."""
    a2 = _a2()

    assert "sidecar" in a2["lifecycle"]


def test_a2_lifecycle_sidecar_emits_all_contract_fields():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 148-163 - 12-field shape."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert set(sidecar) == {
        "schema_version",
        "module_id",
        "expression_profile_id",
        "authority",
        "static_rule_core_version",
        "lifecycle_action",
        "lifecycle_conflict_state",
        "event_sources",
        "threshold_policy_objects",
        "named_gaps",
        "source_classification",
        "promotion_state",
    }
    assert sidecar["schema_version"] == "v2.0"
    assert sidecar["module_id"] == "A"
    assert sidecar["expression_profile_id"] == "A2"


def test_a2_lifecycle_sidecar_uses_honest_entry_time_posture_alpha():
    """Operator posture alpha: no projected lifecycle action before an active position exists."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_action"] == "no_active_position"
    assert sidecar["event_sources"] == []


def test_a2_lifecycle_sidecar_conflict_defaults_to_warning_only():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 97-100 - advisory default."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_conflict_state"] == "lifecycle_warning_only"


def test_a2_lifecycle_sidecar_static_rule_core_version_matches_constant():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 155 - static rule version."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["static_rule_core_version"] == LIFECYCLE_RULE_CORE_VERSION


def test_a2_lifecycle_sidecar_named_gaps_match_contract_verbatim():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 117-136 - named gaps."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["named_gaps"] == list(LIFECYCLE_GAP_NAMES)
    assert len(sidecar["named_gaps"]) == 13
    assert sidecar["named_gaps"] == [
        "a2_lifecycle_policy_pending",
        "a2_lifecycle_static_rule_core_pending",
        "a2_lifecycle_legacy_exit_logic_divergence_audit_pending",
        "a2_lifecycle_eod_force_exit_logic_not_implemented",
        "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
        "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
        "a2_lifecycle_iv_crush_handler_not_implemented",
        "a2_lifecycle_pin_risk_handler_not_implemented",
        "a2_lifecycle_gamma_spike_handler_not_implemented",
        "a2_lifecycle_assignment_risk_handler_not_implemented",
        "a2_lifecycle_spread_widening_exit_not_implemented",
        "a2_lifecycle_partial_fill_handler_not_implemented",
        "a2_lifecycle_dynamic_policy_not_implemented",
    ]


def test_a2_lifecycle_sidecar_authority_matches_contract_block():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 14-22 - authority block."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["authority"] == {
        "mode": "advisory_non_authoritative",
        "tier": "C_analytics_only",
        "changes_trade_behavior": False,
    }


def test_a2_lifecycle_sidecar_policy_objects_and_source_classification_are_explicit():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 26-34 and 148-163."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["threshold_policy_objects"] == [
        {
            "id": "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
            "source": "policy_object_pending",
        },
        {
            "id": "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
            "source": "policy_object_pending",
        },
    ]
    assert sidecar["source_classification"] == {
        "inputs": "schwab_native_normalized",
        "decision": "derived_because_schwab_does_not_provide",
        "thresholds": "policy_object_pending",
    }


def test_a2_lifecycle_sidecar_promotion_state_marks_all_criteria_unsatisfied():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 176-188 - promotion criteria."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert set(sidecar["promotion_state"]) == {
        "replay_live_parity_passing",
        "bound_threshold_policies",
        "empirical_improvement_over_static_baseline",
        "uncertainty_disclosure",
        "a2_replay_label_validation",
        "post_trade_attribution_coherence",
        "operator_decision_register_approval",
    }
    for state in sidecar["promotion_state"].values():
        assert state["satisfied"] is False
        assert isinstance(state["reason"], str)
        assert state["reason"]


def test_existing_lifecycle_leaves_remain_unchanged_when_sidecar_is_added():
    """Regression: existing A2 lifecycle leaves remain byte-identical except the new sidecar key."""
    lifecycle = _a2()["lifecycle"]

    existing = {key: value for key, value in lifecycle.items() if key != "sidecar"}
    assert existing == {
        "entry_policy": {"value": "SPY 2026-05-05 500C - 0DTE - mid~1.25", "source": "v1_approximation"},
        "stop_policy": {"value": 498.5, "source": "v1_approximation"},
        "target_policy": {"value": 503.0, "source": "v1_approximation"},
        "timeout_policy": {"value": None, "source": "policy_object_pending"},
        "forced_exit_time": {"value": None, "source": "policy_object_pending"},
        "allowed_actions": {
            "value": ["hold", "exit", "tighten", "scale_out", "convert", "force_exit"],
            "source": "policy_object_pending",
        },
        "lifecycle_policy_id": {"value": None, "source": "policy_object_pending"},
    }


def test_a2_lifecycle_crosswalk_source_indicators_remain_unchanged():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 172 - crosswalk leaves unchanged."""
    a2 = _a2()

    assert a2["probability_and_ev"]["P_lifecycle_adjusted_profit"]["source"] == "not_implemented"
    assert a2["lifecycle"]["timeout_policy"]["source"] == "policy_object_pending"
    assert a2["lifecycle"]["lifecycle_policy_id"]["source"] == "policy_object_pending"
