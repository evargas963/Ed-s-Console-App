"""validate_v2_decision must reject a V2 decision missing a required leaf field
(fusion_available, tradable canonical_provenance, etc.) rather than silently
accepting a partial decision as complete."""
from __future__ import annotations

import pytest

from v2_decision import build_module_a_a1_decision, validate_v2_decision
from v2_decision.schema import V2DecisionSchemaError, leaf


def _sample_market_state() -> dict:
    # Fusion authority requires fusion_available, tradable canonical_provenance,
    # and the transported producer verdict stack_directional_authorized=True.
    return {
        "ticker": "SPY",
        "fusion_available": True,
        "canonical_provenance": "bayesian_fusion",
        "stack_directional_authorized": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.64,
        "fusion_confidence": "high",
        "fusion_summary": "Fusion supports continuation",
        "dominant_dir": "down",
        "is_no_trade": False,
        "execution_mode": "STANDARD",
        "r_units": 0.25,
        "entry": 500.0,
        "stop": 498.5,
        "target": 503.0,
        "target2": 505.0,
        "decision_generation_id": 12,
        "_server_build_ts": 1_777_777.0,
        "stack_runtime": {"fusion_active": True},
        "stack_governance": {"available": True},
        "signal_chain": {"authoritative": "fusion"},
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": "med", "role": "entry"},
            {"horizon": "5c", "call": "LONG", "confidence": "high", "role": "confirm"},
        ],
    }


def test_module_a_a1_decision_is_complete_and_advisory():
    decision = build_module_a_a1_decision(_sample_market_state())

    validate_v2_decision(decision)
    assert decision["schema_version"] == "v2.0-draft"
    assert decision["v2_status"] == "target_architecture_pending_governance_binding"
    assert decision["authority"]["mode"] == "advisory_non_authoritative"
    assert decision["authority"]["tier"] == "C_analytics_only"
    assert decision["authority"]["changes_trade_behavior"] is False


def test_module_a_a1_maps_current_stack_as_v1_approximation():
    decision = build_module_a_a1_decision(_sample_market_state())

    assert decision["strategy_module"]["id"] == {
        "value": "A",
        "source": "v1_approximation",
        "detail": "Short-horizon directional signal module.",
    }
    assert decision["expression_profile"]["id"]["value"] == "A1"
    assert decision["decision"]["direction"] == {"value": "long", "source": "v1_approximation"}
    assert decision["decision"]["probability"] == {"value": 0.64, "source": "v1_approximation"}
    assert decision["edge_domains"]["implementation"]["slippage_model"]["source"] == "not_implemented"
    assert decision["edge_domains"]["portfolio"]["correlation_adjusted_size"]["source"] == "policy_object_pending"
    post_trade = decision["edge_domains"]["lifecycle"]["post_trade_attribution"]
    assert post_trade["source"] == "not_implemented"
    assert post_trade["value"]["status"] == "schema_and_log_sink_available"
    assert post_trade["value"]["live_close_out_record_attached"] is False
    assert post_trade["value"]["learning_enabled"] is False


def test_section_18_named_probability_and_ev_fields_are_explicit_leaves():
    decision = build_module_a_a1_decision(_sample_market_state())
    dec = decision["decision"]

    assert dec["P_entry_success"] == {
        "value": 0.64,
        "source": "v1_approximation",
        "detail": "Closest current analog is the dominant v1 stack/fusion probability.",
    }
    assert dec["P_lifecycle_adjusted_success"]["source"] == "not_implemented"
    assert dec["p_low"]["source"] == "not_implemented"
    assert dec["p_high"]["source"] == "not_implemented"
    assert dec["EV_lower"]["source"] == "not_implemented"
    assert dec["EV_upper"]["source"] == "not_implemented"


def test_wait_when_existing_payload_blocks_trade():
    ms = _sample_market_state()
    ms["is_no_trade"] = True

    decision = build_module_a_a1_decision(ms)

    assert decision["decision"]["action"] == {"value": "WAIT", "source": "v1_approximation"}


def test_leaf_rejects_unknown_source_indicator():
    with pytest.raises(V2DecisionSchemaError):
        leaf("x", "made_up_source")


def test_validate_rejects_authoritative_v2_payload():
    decision = build_module_a_a1_decision(_sample_market_state())
    decision["authority"]["changes_trade_behavior"] = True

    with pytest.raises(V2DecisionSchemaError):
        validate_v2_decision(decision)

