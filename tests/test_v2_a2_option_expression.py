from __future__ import annotations

from datetime import datetime

from v2_decision.a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES
import v2_decision.a2_option_expression as a2oe
from v2_decision.a2_option_expression import (
    A2_ADAPTER_GAP_REGISTRY,
    HARD_GATE_ACTION_POLICY,
    HARD_GATE_CONTRACT_MAP,
    _black_scholes_theta,
    _mins_to_close,
    build_a2_option_expression,
)
from v2_decision.module_a_adapter import build_module_a_a1_decision


from time_et import ET
def _epoch_ms_et(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _sample_a1() -> dict:
    return build_module_a_a1_decision(
        {
            "ticker": "SPY",
            "fusion_available": True,
            "canonical_provenance": "bayesian_fusion",
            "fusion_dominant_direction": "up",
            "fusion_dominant_prob": 0.64,
            "fusion_confidence": "high",
            "is_no_trade": False,
            "execution_mode": "STANDARD",
        }
    )


def _winner() -> dict:
    # institutional-synthetic-ok: v2 option-expression test needs a controlled winner row.
    return {
        "expression": "500 CALL",
        "strike": 500.0,
        "side": "CALL",
        "composite_score": 8.25,
        "chain_row": {
            "symbol": "SPY260505C00500000",
            "putCall": "CALL",
            "strikePrice": 500.0,
            "bid": 1.2,
            "ask": 1.3,
            "delta": 0.52,
            "gamma": 0.08,
            "theta": -0.18,
            "vega": 0.02,
            "volatility": 0.22,
            "totalVolume": 1200,
            "openInterest": 4300,
            "daysToExpiration": 0,
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
        "decision_time_ms": 1778018400000,
        "option_chain_selection_proof": {
            "status": "ok",
            "winner": _winner(),
            "liquidity_summary": {"any_candidate_passed_liq_gate": True},
        },
        "contract_context": "SPY 2026-05-05 500C · 0DTE · mid≈1.25",
    }
    base.update(overrides)
    return base


def test_a2_option_expression_emits_mid_and_spread_provenance_tags():
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    oe = a2["option_expression"]
    assert oe["mid"]["value"] == 1.25
    assert oe["mid_source"]["value"] == "derived_bid_ask_mid"
    assert oe["spread"]["value"] == 0.1
    assert oe["spread_source"]["value"] == "schwab_chain_bid_ask_pts"
    assert oe["underlying_spread_pts"]["value"] == 0.1


def test_a2_option_expression_prefers_schwab_chain_last_over_bid_ask_mid():
    w = _winner()
    w["chain_row"] = {**w["chain_row"], "mark": None, "last": 1.27}
    ms = _ms()
    ms["option_chain_selection_proof"] = {
        "status": "ok",
        "winner": w,
        "liquidity_summary": {"any_candidate_passed_liq_gate": True},
    }
    a2 = build_a2_option_expression(ms, _sample_a1())
    assert a2["option_expression"]["mid"]["value"] == 1.27
    assert a2["option_expression"]["mid_source"]["value"] == "schwab_chain_last"


def test_valid_a2_deterministic_baseline_has_source_indicators():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L237 - valid A2 baseline validates shape."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())

    assert a2["identity"]["expression_profile_id"] == {"value": "A2", "source": "v2_compliant"}
    # Schwab-direct identity leaves: ticker is the literal Schwab request /
    # chains.symbol echo; selected_expiry resolved from chain_row.expirationDate.
    assert a2["identity"]["underlying_ticker"] == {
        "value": "SPY",
        "source": "v2_compliant",
        "detail": "chains.symbol",
    }
    assert a2["identity"]["selected_expiry"] == {
        "value": "2026-05-05",
        "source": "v2_compliant",
        "detail": "schwab_chain_expirationDate",
    }
    assert a2["option_expression"]["option_action"] == {"value": "TRADE", "source": "v1_approximation"}
    # Schwab-direct option_right: chain_row.putCall wins over app-side aliases.
    assert a2["option_expression"]["option_right"] == {
        "value": "CALL",
        "source": "v2_compliant",
        "detail": "chains.*.putCall",
    }
    # Schwab-direct strike: chain_row.strikePrice is authoritative.
    assert a2["option_expression"]["strike"] == {
        "value": 500.0,
        "source": "v2_compliant",
        "detail": "schwab_chain_strikePrice",
    }
    assert a2["greeks"]["theta"] == {
        "value": -0.18,
        "source": "v2_compliant",
        "detail": "schwab_chain_theta",
    }
    assert a2["identity"]["dte"] == {
        "value": 0,
        "source": "v2_compliant",
        "detail": "schwab_chain_daysToExpiration",
    }
    assert a2["greeks"]["iv"] == {
        "value": 0.22,
        "source": "v2_compliant",
        "detail": "schwab_chain_volatility",
    }


def test_a2_iv_uses_schwab_theoretical_volatility_when_market_volatility_missing():
    winner = _winner()
    winner["chain_row"]["volatility"] = None
    winner["chain_row"]["theoreticalVolatility"] = 18.5

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["greeks"]["iv"] == {
        "value": 18.5,
        "source": "v2_compliant",
        "detail": "schwab_chain_theoreticalVolatility",
    }


def test_hard_gate_contract_map_accounts_for_every_contract_gate():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L157-L169 - gate crosswalk."""
    rows = list(HARD_GATE_CONTRACT_MAP)

    assert len(rows) == 11
    assert [row["contract_gate"] for row in rows] == [
        "missing selected expiry",
        "selected expiry is not same-day when strict 0DTE",
        "no option-chain archive / current chain rows for selected expiry",
        "no side-compatible contracts",
        "missing bid or ask for selected contract",
        "missing theta from chain row and Black-Scholes approximation inputs",
        "invalid or stale quote timestamp",
        "spread exceeds governed hard threshold",
        "missing selected strike or option right",
        "Module A signal is WAIT or unavailable",
        "replay/live parity failing once validation status is available",
    ]
    implemented = [row for row in rows if row["status"] == "implemented"]
    assert len(implemented) == 10
    assert rows[-1] == {
        "contract_gate": "replay/live parity failing once validation status is available",
        "status": "deferred_slice_5",
        "gate_string": None,
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 169",
        "reason": "A2 live-vs-replay parity validation is not attached to runtime payloads until Slice 5.",
        "registered_gap": "a2_replay_live_parity_not_gating_runtime",
    }


def test_hard_gate_action_policy_is_wait_only_and_avoid_reserved():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L155-L156 - WAIT/AVOID discipline."""
    assert HARD_GATE_ACTION_POLICY == {
        "hard_gate_action": "WAIT",
        "avoid_reserved_for": "future advisory-only soft-gate policy",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md lines 155-156",
    }


def test_a2_handoff_authority_is_contract_cited_advisory_record_only():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L149 - A2 cannot veto A1."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())

    assert "trade_impacting_veto" not in a2["handoff"]
    assert a2["handoff"]["a2_disagreement_authority"] == {
        "value": "advisory_record_only",
        "source": "v2_compliant",
        "detail": "PILOT_1B_A2_0DTE_CONTRACT.md line 149: A2 cannot veto A1 for trade-impacting purposes during Pilot 1B.",
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
    # The selected_contract_snapshot is the literal Schwab chain row passthrough.
    assert snapshot["source"] == "v2_compliant"
    assert snapshot["detail"] == "schwab_chain_row_snapshot"
    assert snapshot["value"]["quoteTimeInLong"] == 1778018400000
    assert snapshot["value"]["tradeTimeInLong"] == 1778018399000


def test_a2_emits_wait_when_quote_age_exceeds_o20_threshold():
    """Step 3.3 red: stale quote above O-20 threshold blocks A2."""
    winner = _winner()
    winner["chain_row"]["quoteTimeInLong"] = 1778018397000

    a2 = build_a2_option_expression(
        _ms(
            decision_time_ms=1778018400000,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["execution"]["quote_staleness_ms"] == {
        "value": 3000,
        "source": "v2_compliant",
    }
    assert "quote_stale_above_threshold" in a2["health"]["hard_gates_failed"]["value"]


def test_a2_proceeds_when_quote_age_within_o20_threshold():
    """Step 3.3 red: quote within O-20 threshold preserves normal A2 output."""
    winner = _winner()
    winner["chain_row"]["quoteTimeInLong"] = 1778018398500

    a2 = build_a2_option_expression(
        _ms(
            decision_time_ms=1778018400000,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert a2["execution"]["quote_staleness_ms"] == {
        "value": 1500,
        "source": "v2_compliant",
    }
    assert "quote_stale_above_threshold" not in a2["health"]["hard_gates_failed"]["value"]


def test_a2_emits_wait_when_quote_timestamp_missing():
    """Step 3.3 red: missing quote and trade timestamps blocks A2 before staleness gate."""
    winner = _winner()
    winner["chain_row"].pop("quoteTimeInLong", None)
    winner["chain_row"].pop("tradeTimeInLong", None)

    a2 = build_a2_option_expression(
        _ms(
            decision_time_ms=1778018400000,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["execution"]["quote_staleness_ms"]["source"] == "not_implemented"
    assert "missing_quote_timestamp" in a2["health"]["hard_gates_failed"]["value"]


def test_a2_quote_staleness_ms_source_is_v2_compliant_when_computed():
    """Step 3.3 red: computed quote staleness is a v2-compliant data-plane field."""
    winner = _winner()
    winner["chain_row"]["quoteTimeInLong"] = 1778018399000

    a2 = build_a2_option_expression(
        _ms(
            decision_time_ms=1778018400000,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["execution"]["quote_staleness_ms"]["value"] == 1000
    assert a2["execution"]["quote_staleness_ms"]["source"] == "v2_compliant"


def test_a2_emits_wait_when_spread_exceeds_absolute_threshold():
    """Step 3.4 red: O-21 absolute spread threshold blocks A2."""
    winner = _winner()
    winner["chain_row"]["bid"] = 1.0
    winner["chain_row"]["ask"] = 1.12

    a2 = build_a2_option_expression(
        _ms(spread=None, option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["option_expression"]["option_right"]["value"] == "NONE"
    assert a2["option_expression"]["strike"]["value"] is None
    assert "spread_exceeds_hard_threshold" in a2["health"]["hard_gates_failed"]["value"]


def test_a2_emits_wait_when_spread_exceeds_relative_threshold():
    """Step 3.4 red: O-21 relative spread threshold blocks low-mid contracts."""
    winner = _winner()
    winner["chain_row"]["bid"] = 0.45
    winner["chain_row"]["ask"] = 0.51

    a2 = build_a2_option_expression(
        _ms(spread=None, option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["option_expression"]["mid"]["value"] == 0.48
    assert "spread_exceeds_hard_threshold" in a2["health"]["hard_gates_failed"]["value"]


def test_a2_proceeds_when_spread_within_thresholds():
    """Step 3.4 red: spread within both O-21 thresholds remains eligible."""
    winner = _winner()
    winner["chain_row"]["bid"] = 1.0
    winner["chain_row"]["ask"] = 1.08

    a2 = build_a2_option_expression(
        _ms(spread=None, option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "spread_exceeds_hard_threshold" not in a2["health"]["hard_gates_failed"]["value"]


def test_a2_spread_gate_picks_tighter_of_absolute_or_relative():
    """Step 3.4 red: O-21 uses the tighter absolute vs relative threshold."""
    winner = _winner()
    winner["chain_row"]["bid"] = 0.95
    winner["chain_row"]["ask"] = 1.06

    a2 = build_a2_option_expression(
        _ms(spread=None, option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "spread_exceeds_hard_threshold" in a2["health"]["hard_gates_failed"]["value"]


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
    winner = _winner()
    winner["chain_row"].pop("expirationDate", None)
    a2 = build_a2_option_expression(
        _ms(
            selected_exp=None,
            call_option_expiry=None,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "missing_selected_expiry" in a2["health"]["hard_gates_failed"]["value"]


def test_schwab_chain_expiration_satisfies_selected_expiry_hard_gate():
    """Schwab-first: chain_row.expirationDate counts when ms_dict aliases are absent."""
    winner = _winner()
    a2 = build_a2_option_expression(
        _ms(
            selected_exp=None,
            call_option_expiry=None,
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )
    assert a2["identity"]["selected_expiry"]["source"] == "v2_compliant"
    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "missing_selected_expiry" not in a2["health"]["hard_gates_failed"]["value"]


def test_liquidity_gate_pass_withheld_when_liq_ok_missing():
    ms = _ms()
    ms.pop("liq_ok", None)
    a2 = build_a2_option_expression(ms, _sample_a1())
    assert a2["execution"]["liquidity_gate_pass"] == {
        "value": None,
        "source": "not_implemented",
    }
    assert a2["execution"]["spread_quality"]["value"] == "unknown"


def test_invalid_ask_blocks_spread_evaluation_fail_closed():
    winner = _winner()
    winner["chain_row"]["bid"] = 1.0
    winner["chain_row"]["ask"] = 0.0
    winner["chain_row"]["mark"] = None
    winner["chain_row"]["last"] = None
    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )
    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "missing_bid_or_ask" in a2["health"]["hard_gates_failed"]["value"]


def test_non_same_day_expiry_blocks_strict_0dte_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L160 - strict 0DTE requires same-day expiry."""
    winner = _winner()
    winner["chain_row"]["daysToExpiration"] = 1
    a2 = build_a2_option_expression(
        _ms(
            selected_exp="2026-05-06",
            call_option_expiry="2026-05-06",
            dte_warn="0DTE",
            option_chain_selection_proof={
                "status": "ok",
                "winner": winner,
                "liquidity_summary": {"any_candidate_passed_liq_gate": True},
            },
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "non_same_day_expiry_strict_0dte" in a2["health"]["hard_gates_failed"]["value"]


def test_missing_schwab_days_to_expiration_blocks_strict_0dte_even_if_text_says_0dte():
    """CSV-first S001: strict 0DTE uses chain_row.daysToExpiration, not dte_warn text."""
    winner = _winner()
    winner["chain_row"].pop("daysToExpiration")

    a2 = build_a2_option_expression(
        _ms(
            dte_warn="0DTE",
            option_chain_selection_proof={
                "status": "ok",
                "winner": winner,
                "liquidity_summary": {"any_candidate_passed_liq_gate": True},
            },
        ),
        _sample_a1(),
    )

    assert a2["identity"]["dte"] == {
        "value": None,
        "source": "not_implemented",
        "detail": "missing_schwab_daysToExpiration",
    }
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


def test_missing_winner_chain_row_blocks_trade_output():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L161 - missing current chain row blocks trade."""
    winner = _winner()
    winner.pop("chain_row")

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert a2["option_expression"]["option_right"]["value"] == "NONE"
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
    # Schwab-first precedence: chain_row.strikePrice and chain_row.putCall are
    # the authoritative sources, so the "missing" scenario must remove them
    # from the chain row too — not just the legacy app-side aliases.
    winner["chain_row"].pop("strikePrice", None)
    winner["chain_row"].pop("putCall", None)

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


def _wide_spread_ms(**overrides):
    winner = _winner()
    winner["chain_row"]["bid"] = 1.0
    winner["chain_row"]["ask"] = 1.50
    base = _ms(
        spread=None,
        liq_ok=False,
        option_chain_selection_proof={"status": "ok", "winner": winner},
    )
    base.update(overrides)
    return base


def test_wide_spread_records_hard_gate_after_policy_bound():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L240 - wide spread records gate state."""
    a2 = build_a2_option_expression(_wide_spread_ms(), _sample_a1())

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "spread_exceeds_hard_threshold" in a2["health"]["hard_gates_failed"]["value"]
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


def test_late_day_gamma_status_uses_derived_mins_to_close_when_explicit_absent():
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
        _ms(
            mins_to_close=None,
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 35),
            option_chain_selection_proof=proof,
        ),
        _sample_a1(),
    )

    assert a2["health"]["late_day_gamma"]["value"]["mins_to_close"] == 25.0
    assert a2["health"]["late_day_gamma"]["value"]["status"] == "elevated"
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
    a2 = build_a2_option_expression(_wide_spread_ms(), a1)

    assert a1["decision"]["action"]["value"] == "TRADE"
    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "spread_exceeds_hard_threshold" in a2["health"]["hard_gates_failed"]["value"]
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


def test_black_scholes_theta_returns_none_for_missing_or_invalid_inputs():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L119 - BS fallback must fail honestly."""
    valid = {
        "spot": 499.5,
        "strike": 500.0,
        "iv": 0.22,
        "option_right": "CALL",
        "time_to_expiry_years": 120.0 / (365.0 * 24.0 * 60.0),
    }

    for key in valid:
        payload = dict(valid)
        payload[key] = None
        assert _black_scholes_theta(**payload) is None

    assert _black_scholes_theta(**{**valid, "spot": 0}) is None
    assert _black_scholes_theta(**{**valid, "strike": 0}) is None
    assert _black_scholes_theta(**{**valid, "iv": 0}) is None
    assert _black_scholes_theta(**{**valid, "time_to_expiry_years": 0}) is None
    assert _black_scholes_theta(**{**valid, "option_right": "NONE"}) is None


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


def test_a2_falls_back_to_bs_only_when_schwab_theta_missing(monkeypatch):
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L119 - BS theta fallback is governed v1 approximation."""
    monkeypatch.setattr(a2oe, "_A2_THETA_BS_FALLBACK_GOVERNED", True)
    winner = _winner()
    winner["chain_row"].pop("theta")

    a2 = build_a2_option_expression(
        # RC-345 / F13: valuation T is now the canonical time_et intraday-to-close, so the
        # as-of must be a real pre-close trading moment (14:00 ET, 2h to the 16:00 close),
        # not the old fixture's 18:00 (post-close) paired with a mins_to_close=120 stub.
        _ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 14, 0),
            option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "theta_unavailable" not in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"]["source"] == "v1_approximation"
    assert a2["greeks"]["theta"]["detail"] == "black_scholes_approximation_governed"
    assert a2["greeks"]["theta"]["value"] < 0
    assert a2["greeks"]["theta"]["source"] != "v2_compliant"


def test_theta_bs_fallback_uses_derived_mins_to_close_when_explicit_absent(monkeypatch):
    monkeypatch.setattr(a2oe, "_A2_THETA_BS_FALLBACK_GOVERNED", True)
    winner = _winner()
    winner["chain_row"].pop("theta")

    a2 = build_a2_option_expression(
        _ms(
            mins_to_close=None,
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 35),
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert "theta_unavailable" not in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"]["source"] == "v1_approximation"
    assert a2["greeks"]["theta"]["detail"] == "black_scholes_approximation_governed"
    assert a2["greeks"]["theta"]["value"] < 0


def test_mins_to_close_helper_honors_explicit_value_over_derived():
    assert _mins_to_close({"mins_to_close": 120, "decision_time_ms": _epoch_ms_et(2026, 5, 5, 15, 35)}) == 120.0


def test_mins_to_close_helper_returns_none_when_both_absent():
    assert _mins_to_close({}) is None


def test_mins_to_close_helper_returns_zero_post_close():
    assert _mins_to_close({"decision_time_ms": _epoch_ms_et(2026, 5, 5, 18, 0)}) == 0.0


def test_required_a2_gap_list_is_named():
    """Contract: PILOT_1B_A2_0DTE_CONTRACT.md L219-L229 - required A2 gaps are named."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    gaps = {g["component"] for g in a2["conformance_gaps"]}

    assert "a2_contract_profit_labels_not_implemented" in gaps
    assert "a2_execution_model_not_implemented" in gaps
    assert "a2_pin_risk_handling_not_implemented" in gaps
    assert "a2_late_day_gamma_policy_pending" in gaps
    assert "a2_early_assignment_risk_not_implemented" in gaps


def test_a2_gap_registry_includes_lifecycle_child_gaps_without_duplicates():
    """Contract: parent L235 delegates lifecycle child gaps to lifecycle contract."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())
    gaps = [g["component"] for g in a2["conformance_gaps"]]

    assert gaps == list(A2_ADAPTER_GAP_REGISTRY)
    assert len(gaps) == len(set(gaps))
    for gap in LIFECYCLE_GAP_NAMES:
        assert gap in gaps


# ---------------------------------------------------------------------------
# Schwab-wire greek leaves (delta / gamma / vega) provenance + sentinel safety
# ---------------------------------------------------------------------------


def test_a2_greeks_delta_gamma_vega_are_v2_compliant_when_wire_present():
    """delta / gamma / vega are Schwab dictionary leaves; A2 must label them as
    v2_compliant with the schwab_chain_<name> detail when present, not v1_approximation."""
    a2 = build_a2_option_expression(_ms(), _sample_a1())

    assert a2["greeks"]["delta"] == {
        "value": 0.52,
        "source": "v2_compliant",
        "detail": "schwab_chain_delta",
    }
    assert a2["greeks"]["gamma"] == {
        "value": 0.08,
        "source": "v2_compliant",
        "detail": "schwab_chain_gamma",
    }
    assert a2["greeks"]["vega"] == {
        "value": 0.02,
        "source": "v2_compliant",
        "detail": "schwab_chain_vega",
    }


def test_a2_greeks_treat_missing_sentinel_as_not_implemented():
    """Schwab's -999.0 'missing' sentinel must not be advertised as a wire read."""
    winner = _winner()
    winner["chain_row"]["delta"] = -999.0
    winner["chain_row"]["gamma"] = -999.0
    winner["chain_row"]["vega"] = -999.0

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    for greek in ("delta", "gamma", "vega"):
        assert a2["greeks"][greek] == {"value": None, "source": "not_implemented"}


def test_a2_gamma_x_oi_does_not_propagate_missing_sentinel():
    """gamma_x_oi must be None when gamma is the -999 sentinel, never gamma * OI literally."""
    winner = _winner()
    winner["chain_row"]["gamma"] = -999.0
    winner["chain_row"]["openInterest"] = 4300

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["greeks"]["gamma_x_oi"] == {"value": None, "source": "not_implemented"}


def test_a2_gamma_x_oi_attaches_derived_detail_when_computed():
    a2 = build_a2_option_expression(_ms(), _sample_a1())

    assert a2["greeks"]["gamma_x_oi"] == {
        "value": round(0.08 * 4300, 4),
        "source": "v1_approximation",
        "detail": "derived_schwab_gamma_x_openInterest",
    }


def test_a2_theta_falls_back_to_bs_when_chain_theta_is_missing_sentinel(monkeypatch):
    """If Schwab returns theta=-999.0, treat it as missing and use governed BS approximation."""
    monkeypatch.setattr(a2oe, "_A2_THETA_BS_FALLBACK_GOVERNED", True)
    winner = _winner()
    winner["chain_row"]["theta"] = -999.0

    a2 = build_a2_option_expression(
        # RC-345 / F13: canonical T needs a real pre-close as-of (see sibling test).
        _ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 14, 0),
            option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert "theta_unavailable" not in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"]["source"] == "v1_approximation"
    assert a2["greeks"]["theta"]["detail"] == "black_scholes_approximation_governed"
    assert a2["greeks"]["theta"]["value"] < 0


def test_a2_theta_blocks_when_chain_theta_is_missing_sentinel_and_iv_unavailable():
    """Sentinel theta + no IV ladder => BS cannot run => theta_unavailable hard gate."""
    winner = _winner()
    winner["chain_row"]["theta"] = -999.0
    winner["chain_row"]["volatility"] = -999.0
    winner["chain_row"]["theoreticalVolatility"] = None

    a2 = build_a2_option_expression(
        _ms(option_chain_selection_proof={"status": "ok", "winner": winner}),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_action"]["value"] == "WAIT"
    assert "theta_unavailable" in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"] == {
        "value": None,
        "source": "not_implemented",
        "detail": "schwab_theta_missing",
    }


# ---------------------------------------------------------------------------
# Schwab Field Precedence Principle (encoded across this file's surface).
# Schwab canonical_field reads are primary; app-side aliases (ms_dict keys,
# winner.* aliases) are legacy fallbacks only when the Schwab field is absent.
# ---------------------------------------------------------------------------


def test_schwab_chain_row_putCall_wins_over_conflicting_app_side_aliases():
    """Schwab `chain_row.putCall` must override conflicting ms_dict aliases.

    All three legacy aliases (`call_option_right`, `rec_side`, `winner.side`)
    say PUT. The Schwab chain_row says CALL. The A2 surface MUST report CALL
    and label the leaf v2_compliant with detail `chains.*.putCall`.
    """
    winner = _winner()
    winner["chain_row"]["putCall"] = "CALL"
    winner["side"] = "PUT"  # conflicting legacy alias

    a2 = build_a2_option_expression(
        _ms(
            call_option_right="PUT",  # conflicting legacy alias
            rec_side="PUT",  # conflicting legacy alias
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["option_right"] == {
        "value": "CALL",
        "source": "v2_compliant",
        "detail": "chains.*.putCall",
    }


def test_schwab_chain_row_strikePrice_wins_over_conflicting_ms_rec_strike():
    """Schwab `chain_row.strikePrice` must override conflicting `ms.rec_strike`."""
    winner = _winner()
    winner["chain_row"]["strikePrice"] = 505.0
    winner["strike"] = 505.0  # winner.strike sourced from chain_row, kept consistent

    a2 = build_a2_option_expression(
        _ms(
            rec_strike=499.0,  # conflicting legacy alias
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["option_expression"]["strike"] == {
        "value": 505.0,
        "source": "v2_compliant",
        "detail": "schwab_chain_strikePrice",
    }


def test_schwab_chain_row_expirationDate_wins_over_conflicting_ms_selected_exp():
    """Schwab `chain_row.expirationDate` must override conflicting ms aliases."""
    winner = _winner()
    winner["chain_row"]["expirationDate"] = "2026-05-05"

    a2 = build_a2_option_expression(
        _ms(
            selected_exp="2026-05-06",  # conflicting legacy alias
            call_option_expiry="2026-05-06",  # conflicting legacy alias
            option_chain_selection_proof={"status": "ok", "winner": winner},
        ),
        _sample_a1(),
    )

    assert a2["identity"]["selected_expiry"] == {
        "value": "2026-05-05",
        "source": "v2_compliant",
        "detail": "schwab_chain_expirationDate",
    }


# ---------------------------------------------------------------------------
# CI gate: Schwab Field Precedence Principle.
#
# Every leaf on the A2 output that carries source="v1_approximation" MUST be
# a derived analytic that Schwab does not provide directly. If a v1_approx
# leaf is found whose value tracks a Schwab canonical_field, the test fails:
# that leaf should be labeled v2_compliant with the Schwab leaf cited.
# ---------------------------------------------------------------------------


# Allowlist of A2 output leaf paths (dotted) where source="v1_approximation"
# is honest because the value is a derived analytic that has no Schwab
# canonical_field equivalent. Each entry is paired with a brief reason.
A2_V1_APPROXIMATION_DERIVED_ALLOWLIST: dict[str, str] = {
    # identity: module/handoff identity strings that are app constants, not
    # Schwab leaves.
    "identity.module_id": "literal app constant 'A'; not a Schwab leaf",
    # handoff: A1 decision outputs (probability, direction) are derived
    # analytics, not Schwab passthroughs.
    "handoff.a1_action": "Module A/A1 derived action; not a Schwab leaf",
    "handoff.a1_direction": "Module A/A1 derived direction; not a Schwab leaf",
    "handoff.mapping": "app-side LONG_TO_CALL / SHORT_TO_PUT mapping",
    # option_expression: derived from Schwab inputs but NOT a Schwab leaf
    # itself.
    "option_expression.option_action": "internal TRADE/WAIT decision; not a Schwab leaf",
    "option_expression.option_right": "labeled v1_approximation only when resolved from a legacy app-side alias (chain_row.putCall absent)",
    "option_expression.strike": "labeled v1_approximation only when resolved from ms.rec_strike with no chain row",
    "option_expression.mid": "derived from mark/last/(bid+ask)/2; no Schwab single-leaf mid",
    "option_expression.spread": "derived from ask-bid; no Schwab single-leaf spread",
    "option_expression.breakeven": "derived from strike +/- mid; no Schwab leaf",
    "option_expression.selection_proof": "app-side selection_proof object; not a Schwab leaf",
    # probability_and_ev: A1 stack probability is derived, not Schwab.
    "probability_and_ev.P_underlying_entry_success": "A1 stack probability; not a Schwab leaf",
    # execution: gates/quality are policy-derived, not Schwab leaves.
    "execution.liquidity_gate_pass": "score_option_expression liq gate; not a Schwab leaf",
    "execution.spread_quality": "policy-derived spread quality; not a Schwab leaf",
    # greeks: ratios/products are derived from Schwab primitives, not leaves.
    "greeks.delta_gamma_ratio": "derived |delta|/|gamma|; no Schwab single-leaf ratio",
    "greeks.gamma_x_oi": "derived gamma * openInterest; no Schwab single-leaf product",
    "greeks.vol_oi_ratio": "derived volume/openInterest; no Schwab single-leaf ratio",
    # lifecycle: app-side trade plan / sidecar inputs (not Schwab leaves).
    "lifecycle.entry_policy": "app-side contract_context display; not a Schwab leaf",
    "lifecycle.stop_policy": "app-side stop geometry; not a Schwab leaf",
    "lifecycle.target_policy": "app-side target geometry; not a Schwab leaf",
    # health: app-side gate/health summaries.
    "health.hard_gates_failed": "app-side hard-gate decision list; not a Schwab leaf",
    "health.soft_gates": "app-side soft-gate list; not a Schwab leaf",
    "health.pin_risk": "derived pin-risk health (no Schwab equivalent)",
    "health.late_day_gamma": "derived late-day-gamma health (no Schwab equivalent)",
    # lifecycle sidecar derivation_inputs: derived analytics that are NOT
    # Schwab passthroughs (spot and vix_level are upgraded to v2_compliant
    # separately and do not appear here).
    "lifecycle.sidecar.projected_preview.derivation_inputs.mins_elapsed_since_open": (
        "derived from decision_time_ms / et clock; no Schwab leaf"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.risk_multiplier": (
        "vol regime risk multiplier; app-side derived, no Schwab leaf"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.entry": (
        "app-side trade plan entry price; no Schwab leaf"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.direction": (
        "app-side signal direction (long/short); no Schwab leaf"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.risk": (
        "derived stop distance * spot; no Schwab leaf"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.avg5": (
        "rolling 5c average points; derived analytic"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.avg15": (
        "rolling 15c average points; derived analytic"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.avg60": (
        "rolling 60c average points; derived analytic"
    ),
    "lifecycle.sidecar.projected_preview.derivation_inputs.structural_levels": (
        "derived structural levels (vwap, walls); no Schwab leaf"
    ),
}


def _walk_v1_approximation_leaves(obj, path):
    """Yield (dotted_path, leaf_dict) for every leaf with source=='v1_approximation'.

    A leaf is a dict containing both 'value' and 'source' keys (matches the
    schema-walker contract in v2_decision/schema.py).
    """
    if isinstance(obj, dict):
        if {"value", "source"}.issubset(obj.keys()):
            if obj.get("source") == "v1_approximation":
                yield path, obj
            return
        for key, value in obj.items():
            yield from _walk_v1_approximation_leaves(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            yield from _walk_v1_approximation_leaves(value, f"{path}[{idx}]")


def _comprehensive_ms_for_ci_gate() -> dict:
    """Build a richly-populated ms_dict so every potential A2 v1_approximation
    leaf is exercised (including all lifecycle sidecar derivation_inputs)."""
    return _ms(
        spot=499.5,
        entry=500.0,
        et_hour=10,
        et_minute=30,
        vix_level=21.0,
        vol_regime_risk_mult=1.0,
        avg_5c_pts=4.0,
        avg_15c_pts=6.0,
        avg_60c_pts=8.0,
        vwap=503.5,
        call_gamma_wall=505.0,
        call_oi_wall=506.0,
        mins_to_close=120.0,
        decision_time_ms=_epoch_ms_et(2026, 5, 5, 10, 30),
        entry_state="armed",
        stop=498.5,
        target=503.0,
        target2=505.0,
        contract_context="SPY 2026-05-05 500C - 0DTE - mid~1.25",
    )


def test_a2_no_v1_approximation_leaf_traces_to_a_schwab_canonical_field():
    """CI gate for the Schwab Field Precedence Principle.

    Every leaf on the A2 output with source='v1_approximation' MUST be a
    derived analytic that Schwab does not provide directly. If a new leaf
    is added that's labeled v1_approximation but actually traces to a
    Schwab canonical_field, this test fails — promote that leaf to
    v2_compliant with the Schwab leaf cited in `detail`, and add the path
    to A2_V1_APPROXIMATION_DERIVED_ALLOWLIST only if it really is derived.
    """
    a2 = build_a2_option_expression(_comprehensive_ms_for_ci_gate(), _sample_a1())

    found_paths = {path for path, _ in _walk_v1_approximation_leaves(a2, "")}
    unexpected = found_paths - set(A2_V1_APPROXIMATION_DERIVED_ALLOWLIST)

    assert not unexpected, (
        "Schwab Field Precedence violation: the following v1_approximation "
        "leaves on the A2 output may trace to a Schwab canonical_field. "
        "Promote each to v2_compliant with the Schwab leaf cited in `detail`, "
        "or add to A2_V1_APPROXIMATION_DERIVED_ALLOWLIST with a reason if it "
        f"truly is derived: {sorted(unexpected)}"
    )

