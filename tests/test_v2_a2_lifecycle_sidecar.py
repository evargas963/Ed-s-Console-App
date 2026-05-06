from __future__ import annotations

from lifecycle_rule_core import LIFECYCLE_RULE_CORE_VERSION
from v2_decision.a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES, PREVIEW_BLOCKING_GAPS
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
        "entry": 500.0,
        "et_hour": 10,
        "et_minute": 30,
        "vix_level": 21.0,
        "avg_5c_pts": 4.0,
        "avg_15c_pts": 6.0,
        "avg_60c_pts": 8.0,
        "vwap": 503.5,
        "call_gamma_wall": 505.0,
        "call_oi_wall": 506.0,
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


def test_a2_lifecycle_sidecar_projected_preview_exists():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 193 - projected_preview exists."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["projected_preview"]


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
        "projected_preview",
    }
    assert sidecar["schema_version"] == "v2.0"
    assert sidecar["module_id"] == "A"
    assert sidecar["expression_profile_id"] == "A2"


def test_projected_preview_status_policy_pending_when_entry_candidate_derivable():
    """Contract: lifecycle contract L215-220 - policy_pending field-fill mapping."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "policy_pending"
    assert preview["projected_stop"]["value"] == 498.98
    assert preview["projected_target"]["value"] == 503.5
    assert preview["projected_target2"]["value"] == 506.0


def test_projected_preview_status_no_entry_candidate_when_a2_has_no_trade_candidate():
    """Contract: lifecycle contract L218 - no candidate means projected fields are None."""
    ms = _ms(is_no_trade=True)
    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "not_available_no_entry_candidate"
    assert _projected_values(preview) == {
        "projected_stop": None,
        "projected_target": None,
        "projected_target2": None,
        "projected_max_hold_bars": None,
        "projected_eod_force_exit_time": None,
    }


def test_projected_preview_status_missing_inputs_when_required_inputs_absent():
    """Contract: lifecycle contract L219 - missing required inputs are enumerated."""
    ms = _ms(entry=None)
    ms.pop("entry", None)
    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "not_available_missing_inputs"
    assert preview["derivation_inputs"]["entry"]["value"] is None
    assert preview["derivation_inputs"]["entry"]["source"] == "not_implemented"
    assert preview["derivation_inputs"]["entry"]["source_classification"] == "missing_from_ms_dict"
    assert preview["derivation_inputs"]["entry"]["detail"] == "missing_required_preview_input"
    assert _projected_values(preview)["projected_stop"] is None


def test_projected_preview_available_is_currently_unreachable_until_eod_gap_closes():
    """Contract: lifecycle contract L244 - EOD force-exit gap blocks fully available preview."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert "a2_lifecycle_eod_force_exit_logic_not_implemented" in preview["preview_named_gaps"]
    assert preview["projected_eod_force_exit_time"]["source"] == "policy_object_pending"
    assert preview["preview_status"] != "available"
    assert PREVIEW_BLOCKING_GAPS


def test_projected_preview_policy_fields_remain_policy_object_pending():
    """Contract: lifecycle contract L243-244 - max-hold and EOD fields remain policy pending."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["projected_max_hold_bars"] == {
        "value": None,
        "source": "policy_object_pending",
        "source_classification": "policy_object_pending",
    }
    assert preview["projected_eod_force_exit_time"] == {
        "value": None,
        "source": "policy_object_pending",
        "source_classification": "policy_object_pending",
    }


def test_projected_preview_derivation_inputs_enumerate_all_contract_keys():
    """Contract: lifecycle contract L245 - derivation_inputs enumerates attempted inputs."""
    inputs = _a2()["lifecycle"]["sidecar"]["projected_preview"]["derivation_inputs"]

    assert set(inputs) == {
        "spot",
        "vix_level",
        "mins_elapsed_since_open",
        "risk_multiplier",
        "entry",
        "direction",
        "risk",
        "avg5",
        "avg15",
        "avg60",
        "structural_levels",
    }
    for payload in inputs.values():
        assert {"value", "source", "source_classification"}.issubset(payload)
    assert inputs["spot"]["value"] == 499.5
    assert inputs["spot"]["source"] == "v1_approximation"
    assert inputs["spot"]["source_classification"] == "schwab_native_normalized"
    assert inputs["mins_elapsed_since_open"]["value"] == 60.0
    assert inputs["risk_multiplier"]["value"] is None
    assert inputs["risk_multiplier"]["source_classification"] == "missing_from_ms_dict"


def test_projected_preview_metadata_source_module_and_timestamp():
    """Contract: lifecycle contract L246-247 - source module and timestamp are explicit."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["derivation_source_module"] == "lifecycle_rule_core"
    assert preview["would_apply_if_entered_at_time"] == 1778018400000


def test_projected_preview_authority_blocks_runtime_interpretation():
    """Contract: lifecycle contract L250-258 - preview_authority is projection-not-decision."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_authority"] == {
        "mode": "advisory_non_authoritative",
        "tier": "C_analytics_only",
        "changes_trade_behavior": False,
        "projection_not_decision": True,
        "text": "Projected lifecycle preview only; not an active lifecycle decision. Future lifecycle action may differ.",
    }


def test_projected_preview_named_gaps_are_preview_blocking_subset_only():
    """Contract: lifecycle contract L226-234 - preview_named_gaps are preview-blocking only."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_named_gaps"] == list(PREVIEW_BLOCKING_GAPS)
    assert preview["preview_named_gaps"] == [
        "a2_lifecycle_eod_force_exit_logic_not_implemented",
        "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
        "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
    ]


def test_projected_preview_no_silent_partial_fills_when_unavailable():
    """Contract: lifecycle contract L272-274 - unavailable preview fields disclose absence."""
    preview = _a2(_ms(entry=None))["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] != "available"
    for key, value in _projected_values(preview).items():
        assert value is None, f"{key} must not contain a stale/default value"


def test_projected_preview_does_not_mutate_ms_dict_or_manage_active_position_data():
    """Implementation rule: preview remains pre-entry projection and does not mutate ms_dict."""
    ms = _ms(active_position={"entry": 1.0, "stop": 0.5}, position_state="open")
    before = dict(ms)

    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert ms == before
    assert preview["preview_status"] == "policy_pending"
    assert preview["preview_authority"]["projection_not_decision"] is True


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
    # Static rule core gap is retired by this A-gap retirement commit.
    assert len(sidecar["named_gaps"]) == 13
    assert sidecar["named_gaps"] == [
        "a2_lifecycle_policy_pending",
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
        "a2_lifecycle_promotion_to_runtime_authority_not_authorized",
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


def test_v0_sidecar_fields_remain_backward_compatible_with_v1_preview():
    """Contract: lifecycle contract L278-280 - v0 fields remain unchanged when preview is added."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    current = {key: value for key, value in sidecar.items() if key != "projected_preview"}
    assert current == {
        "schema_version": "v2.0",
        "module_id": "A",
        "expression_profile_id": "A2",
        "authority": {
            "mode": "advisory_non_authoritative",
            "tier": "C_analytics_only",
            "changes_trade_behavior": False,
        },
        "static_rule_core_version": LIFECYCLE_RULE_CORE_VERSION,
        "lifecycle_action": "no_active_position",
        "lifecycle_conflict_state": "lifecycle_warning_only",
        "event_sources": [],
        "threshold_policy_objects": [
            {
                "id": "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
                "source": "policy_object_pending",
            },
            {
                "id": "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
                "source": "policy_object_pending",
            },
        ],
        "named_gaps": list(LIFECYCLE_GAP_NAMES),
        "source_classification": {
            "inputs": "schwab_native_normalized",
            "decision": "derived_because_schwab_does_not_provide",
            "thresholds": "policy_object_pending",
        },
        "promotion_state": sidecar["promotion_state"],
    }


def _projected_values(preview: dict) -> dict:
    return {
        key: preview[key]["value"]
        for key in (
            "projected_stop",
            "projected_target",
            "projected_target2",
            "projected_max_hold_bars",
            "projected_eod_force_exit_time",
        )
    }
