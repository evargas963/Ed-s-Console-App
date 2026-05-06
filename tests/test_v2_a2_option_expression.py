from __future__ import annotations

from v2_decision.a2_option_expression import build_a2_option_expression
from v2_decision.module_a_adapter import build_module_a_a1_decision


def _sample_a1() -> dict:
    return build_module_a_a1_decision(
        {
            "ticker": "SPY",
            "fusion_available": True,
            "fusion_dominant_direction": "up",
            "fusion_dominant_prob": 0.64,
            "fusion_confidence": "high",
            "is_no_trade": False,
            "execution_mode": "STANDARD",
        }
    )


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
        },
    }


def _ms(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "selected_exp": "2026-05-05",
        "call_option_expiry": "2026-05-05",
        "dte_warn": "0DTE",
        "call_signal": "long",
        "is_no_trade": False,
        "rec_strike": 500.0,
        "rec_side": "CALL",
        "call_option_right": "CALL",
        "liq_ok": True,
        "spread": 0.1,
        "ratio": 6.5,
        "vol_oi": 0.279,
        "spot": 499.5,
        "mins_to_close": 120.0,
        "option_chain_selection_proof": {
            "status": "ok",
            "winner": _winner(),
            "liquidity_summary": {"any_candidate_passed_liq_gate": True},
        },
        "contract_context": "SPY 2026-05-05 500C · 0DTE · mid≈1.25",
    }
    base.update(overrides)
    return base


def test_valid_a2_deterministic_baseline_has_source_indicators():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L237 - valid A2 baseline validates shape."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())

    assert a2["identity"]["expression_profile_id"] == {"value": "A2", "source": "v2_compliant"}
    assert a2["option_expression"]["option_action"] == {"value": "TRADE", "source": "v1_approximation"}
    assert a2["option_expression"]["option_right"] == {"value": "CALL", "source": "v1_approximation"}
    assert a2["option_expression"]["strike"] == {"value": 500.0, "source": "v1_approximation"}
    assert a2["greeks"]["theta"] == {
        "value": -0.18,
        "source": "v2_compliant",
        "detail": "schwab_chain_theta",
    }


def test_selected_contract_snapshot_preserves_schwab_quote_timestamps():
    """Tier B: selected contract snapshot carries Schwab quote/trade timestamps."""
    winner = _winner()
    winner["chain_row"]["quoteTimeInLong"] = 1778018400000
    winner["chain_row"]["tradeTimeInLong"] = 1778018399000

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    snapshot = a2["option_expression"]["selected_contract_snapshot"]
    assert snapshot["source"] == "v1_approximation"
    assert snapshot["value"]["quoteTimeInLong"] == 1778018400000
    assert snapshot["value"]["tradeTimeInLong"] == 1778018399000


def test_wait_signal_emits_no_contract_and_records_gate():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L238 - WAIT signal emits no option contract."""
    a1 = _sample_a1()
    a1["decision"]["action"]["value"] = "WAIT"
    a1["decision"]["direction"]["value"] = "neutral"

    a2 = build_a2_option_expression(_ms(call_signal="wait", is_no_trade=True), a1)

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["option_expression"]["option_right"]["value"] == "NONE"
    assert "module_a_signal_wait_or_unavailable" in a2["health"]["hard_gates_failed"]["value"]


def test_missing_bid_ask_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L239 - missing bid/ask blocks trade output."""
    winner = _winner()
    winner["chain_row"]["bid"] = None
    winner["chain_row"]["ask"] = None

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "missing_bid_or_ask" in a2["health"]["hard_gates_failed"]["value"]


def test_missing_selected_expiry_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L159 - missing selected expiry blocks trade."""
    a2 = build_a2_option_expression(
        _ms(selected_exp=None, call_option_expiry=None),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "missing_selected_expiry" in a2["health"]["hard_gates_failed"]["value"]


def test_non_same_day_expiry_blocks_strict_0dte_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L160 - strict 0DTE requires same-day expiry."""
    a2 = build_a2_option_expression(
        _ms(selected_exp="2026-05-06", call_option_expiry="2026-05-06", dte_warn="1DTE"),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "non_same_day_expiry_strict_0dte" in a2["health"]["hard_gates_failed"]["value"]


def test_missing_option_chain_proof_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L161 - no option-chain proof rows blocks trade."""
    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof=None),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "missing_option_chain_selection_proof" in a2["health"]["hard_gates_failed"]["value"]


def test_no_side_compatible_contract_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L162 - no side-compatible contract blocks trade."""
    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "no_trade", "reason": "no_contracts_for_side"}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "no_side_compatible_contracts" in a2["health"]["hard_gates_failed"]["value"]


def test_missing_strike_or_right_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L167 - missing strike or right blocks trade."""
    winner = _winner()
    winner.pop("strike")
    winner.pop("side")

    a2 = build_a2_option_expression(
        _ms(
            rec_strike=None,
            rec_side=None,
            call_option_right=None,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    gates = a2["health"]["hard_gates_failed"]["value"]
    assert "missing_selected_strike" in gates
    assert "missing_option_right" in gates


def test_wide_spread_records_soft_gate_until_policy_bound():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L240 - wide spread records gate state."""
    a2 = build_a2_option_expression(_ms(spread=0.35, liq_ok=False), _sample_a1())

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "wide_spread_policy_pending" in a2["health"]["soft_gates"]["value"]


def test_pin_risk_near_strike_is_advisory_soft_health():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L178 - pin risk is advisory."""
    proof = {
        "status": "ok",
        "winner": _winner(),
        "chain_rows_scored": [
            {
                "strike": 500.0,
                "side": "CALL",
                "wall_score_component": 1.4,
                "wall_proximity_component": 1.1,
                "wall_bias_component": 0.3,
                "wall_contribution_detail": {
                    "proximity_detail": [
                        {"level": "dom_gamma_wall", "strike": 500.5, "contrib": 1.1},
                    ],
                    "bias_notes": ["dom_gamma_call_confluence"],
                },
            }
        ],
    }

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof=proof),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert a2["health"]["pin_risk"]["source"] == "v1_approximation"
    assert a2["health"]["pin_risk"]["value"]["status"] == "elevated"
    assert a2["health"]["pin_risk"]["value"]["nearest_wall"]["level"] == "dom_gamma_wall"
    assert "pin_risk_near_strike" in a2["health"]["soft_gates"]["value"]


def test_late_day_gamma_acceleration_is_advisory_soft_health():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L179 - late-day gamma is advisory."""
    proof = {
        "status": "ok",
        "winner": _winner(),
        "chain_rows_scored": [
            {
                "strike": 500.0,
                "side": "CALL",
                "gamma": 0.08,
                "open_interest": 4300,
                "gamma_x_oi": 344.0,
                "gamma_is_max": True,
            }
        ],
    }

    a2 = build_a2_option_expression(
        _ms(mins_to_close=20.0, option_chain_selection_proof=proof),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert a2["health"]["late_day_gamma"]["source"] == "v1_approximation"
    assert a2["health"]["late_day_gamma"]["value"]["status"] == "elevated"
    assert a2["health"]["late_day_gamma"]["value"]["gamma_is_max"] is True
    assert "late_day_gamma_acceleration" in a2["health"]["soft_gates"]["value"]


def test_required_probability_ev_placeholders_are_present():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L242 - probability/EV placeholders exist."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    prob = a2["probability_and_ev"]

    assert prob["P_underlying_entry_success"]["value"] == 0.64
    assert prob["P_contract_profit"]["source"] == "not_implemented"
    assert prob["P_lifecycle_adjusted_profit"]["source"] == "not_implemented"
    assert prob["p_low"]["source"] == "not_implemented"
    assert prob["p_high"]["source"] == "not_implemented"
    assert prob["EV_lower"]["source"] == "not_implemented"
    assert prob["EV_upper"]["source"] == "not_implemented"
    assert prob["execution_adjusted_EV"]["source"] == "not_implemented"


def test_a2_named_v2_18_fields_are_explicit_leaves():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L88-L98 - named A2 v2 §18 leaves exist."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    prob = a2["probability_and_ev"]
    required = (
        "P_underlying_entry_success",
        "P_contract_profit",
        "P_lifecycle_adjusted_profit",
        "p_low",
        "p_high",
        "EV_contract_mid",
        "EV_lower",
        "EV_upper",
        "execution_adjusted_EV",
    )

    for field in required:
        assert field in prob
        assert set(("value", "source")).issubset(prob[field].keys())


def test_a2_output_is_nested_under_v2_decision():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L243 - A2 remains nested under v2_decision."""
    v2 = _sample_a1()
    v2["expression_profiles"] = {"A2": build_a2_option_expression(_ms(), v2)}

    assert v2["expression_profiles"]["A2"]["identity"]["expression_profile_id"]["value"] == "A2"
    assert "A2" not in v2["decision"]


def test_action_coherence_records_a1_a2_disagreement():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L244 - A2 action is coherent with A1."""
    a1 = _sample_a1()
    a2 = build_a2_option_expression(_ms(liq_ok=False, spread=0.5), a1)

    assert a1["decision"]["action"]["value"] == "TRADE"
    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "wide_spread_policy_pending" in a2["health"]["soft_gates"]["value"]


def test_theta_is_hard_gate_when_unavailable():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L119 and L164 - theta is a hard gate."""
    winner = _winner()
    winner["chain_row"].pop("theta")
    winner["chain_row"].pop("volatility")

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "theta_unavailable" in a2["health"]["hard_gates_failed"]["value"]


def test_a2_prefers_schwab_theta_over_bs_approximation():
    """Regression: Schwab theta is primary; BS is not the default path."""
    winner = _winner()
    winner["chain_row"]["volatility"] = 500.0

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert a2["greeks"]["theta"] == {
        "value": -0.18,
        "source": "v2_compliant",
        "detail": "schwab_chain_theta",
    }


def test_a2_uses_raw_schwab_theta_as_transitional_bridge():
    """Raw theta remains a temporary bridge if normalization misses it."""
    winner = _winner()
    winner["chain_row"]["raw"] = {"theta": -0.21}
    winner["chain_row"].pop("theta")

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert a2["greeks"]["theta"] == {
        "value": -0.21,
        "source": "v2_compliant",
        "detail": "schwab_raw_theta",
    }


def test_a2_falls_back_to_bs_only_when_schwab_theta_missing():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L119 - BS theta fallback is v1 approximation."""
    winner = _winner()
    winner["chain_row"].pop("theta")

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "theta_unavailable" not in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"]["source"] == "v1_approximation"
    assert a2["greeks"]["theta"]["detail"] == "black_scholes_approximation"
    assert a2["greeks"]["theta"]["value"] < 0


def test_required_a2_gap_list_is_named():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L219-L229 - required A2 gaps are named."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    gaps = {g["component"] for g in a2["conformance_gaps"]}

    assert "a2_contract_profit_labels_not_implemented" in gaps
    assert "a2_execution_model_not_implemented" in gaps
    assert "a2_pin_risk_handling_not_implemented" in gaps
    assert "a2_late_day_gamma_policy_pending" in gaps
    assert "a2_early_assignment_risk_not_implemented" in gaps

