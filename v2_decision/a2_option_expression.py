"""Draft A2 options / 0DTE deterministic baseline adapter."""

from __future__ import annotations

import math
from typing import Any

from .schema import leaf


REQUIRED_A2_GAPS = (
    "a2_contract_profit_labels_not_implemented",
    "a2_execution_model_not_implemented",
    "a2_fill_probability_not_implemented",
    "a2_lifecycle_policy_pending",
    "a2_replay_live_parity_not_gating_runtime",
    "a2_options_native_provenance_not_bound",
    "a2_calibrated_probability_interval_not_implemented",
    "a2_contract_ev_not_implemented",
    "a2_pin_risk_handling_not_implemented",
    "a2_late_day_gamma_policy_pending",
    "a2_early_assignment_risk_not_implemented",
)


def build_a2_option_expression(ms_dict: dict[str, Any], a1_decision: dict[str, Any]) -> dict[str, Any]:
    """Build the Pilot 1B A2 deterministic baseline.

    This wraps existing option-selection payload fields. It does not claim trained
    A2 edge, calibrated contract EV, fill probability, or trade authority.
    """
    proof = ms_dict.get("option_chain_selection_proof")
    if not isinstance(proof, dict):
        proof = {}
    winner = proof.get("winner")
    if not isinstance(winner, dict):
        winner = {}
    chain_row = winner.get("chain_row")
    if not isinstance(chain_row, dict):
        chain_row = {}

    a1_action = _leaf_value(a1_decision, "decision", "action")
    a1_direction = _leaf_value(a1_decision, "decision", "direction")
    option_right = _option_right(ms_dict, winner)
    strike = _first_number(ms_dict.get("rec_strike"), winner.get("strike"))
    bid = _num(chain_row.get("bid"))
    ask = _num(chain_row.get("ask"))
    mid = round((bid + ask) / 2.0, 4) if bid is not None and ask is not None else None
    spread = _first_number(ms_dict.get("spread"), _spread_from_bid_ask(bid, ask))
    theta, theta_source, theta_detail = _theta(
        chain_row=chain_row,
        ms_dict=ms_dict,
        strike=strike,
        option_right=option_right,
    )

    selected_audit = _selected_audit_row(proof, winner, strike, option_right)
    pin_risk = _pin_risk_health(
        selected_audit=selected_audit,
        strike=strike,
    )
    late_day_gamma = _late_day_gamma_health(
        ms_dict=ms_dict,
        chain_row=chain_row,
        selected_audit=selected_audit,
    )
    hard_gates = _hard_gates(
        ms_dict=ms_dict,
        proof=proof,
        winner=winner,
        chain_row=chain_row,
        a1_action=a1_action,
        option_right=option_right,
        strike=strike,
        bid=bid,
        ask=ask,
        theta=theta,
    )
    soft_gates = _soft_gates(ms_dict, pin_risk=pin_risk, late_day_gamma=late_day_gamma)
    action = "TRADE" if not hard_gates else "WAIT"

    return {
        "identity": {
            "module_id": leaf("A", "v1_approximation"),
            "expression_profile_id": leaf("A2", "v2_compliant"),
            "instrument_family": leaf("options_0dte", "v2_compliant"),
            "underlying_ticker": leaf(_clean_str(ms_dict.get("ticker")), "v1_approximation"),
            "selected_expiry": leaf(
                _clean_str(ms_dict.get("call_option_expiry") or ms_dict.get("selected_exp")),
                "v1_approximation",
            ),
            "dte": leaf(_dte_value(ms_dict), "v1_approximation"),
            "decision_plane": leaf("Tier C", "v2_compliant"),
            "authority_mode": leaf("advisory_non_authoritative", "v2_compliant"),
        },
        "handoff": {
            "a1_action": leaf(a1_action, "v1_approximation"),
            "a1_direction": leaf(a1_direction, "v1_approximation"),
            "mapping": leaf(_handoff_mapping(a1_direction), "v1_approximation"),
            "trade_impacting_veto": leaf(False, "v2_compliant"),
        },
        "option_expression": {
            "option_action": leaf(action, "v1_approximation"),
            "option_right": leaf(option_right if action != "WAIT" else "NONE", "v1_approximation"),
            "strike": leaf(strike if action != "WAIT" else None, "v1_approximation"),
            "contract_symbol": leaf(chain_row.get("symbol"), "v1_approximation" if chain_row.get("symbol") else "not_implemented"),
            "bid": leaf(bid, "v1_approximation"),
            "ask": leaf(ask, "v1_approximation"),
            "mid": leaf(mid, "v1_approximation" if mid is not None else "not_implemented"),
            "spread": leaf(spread, "v1_approximation" if spread is not None else "not_implemented"),
            "max_loss": leaf(None, "policy_object_pending"),
            "breakeven": leaf(_breakeven(strike, option_right, mid), "v1_approximation" if mid is not None else "not_implemented"),
            "selected_contract_snapshot": leaf(chain_row or None, "v1_approximation" if chain_row else "not_implemented"),
            "selection_proof": leaf(proof or None, "v1_approximation" if proof else "not_implemented"),
        },
        "probability_and_ev": {
            "P_underlying_entry_success": leaf(_leaf_value(a1_decision, "decision", "P_entry_success"), "v1_approximation"),
            "P_contract_profit": leaf(None, "not_implemented"),
            "P_lifecycle_adjusted_profit": leaf(None, "not_implemented"),
            "p_low": leaf(None, "not_implemented"),
            "p_high": leaf(None, "not_implemented"),
            "EV_contract_mid": leaf(None, "not_implemented"),
            "EV_lower": leaf(None, "not_implemented"),
            "EV_upper": leaf(None, "not_implemented"),
            "execution_adjusted_EV": leaf(None, "not_implemented"),
        },
        "execution": {
            "liquidity_gate_pass": leaf(bool(ms_dict.get("liq_ok")), "v1_approximation"),
            "spread_quality": leaf(_spread_quality(spread, bool(ms_dict.get("liq_ok"))), "v1_approximation"),
            "fill_probability": leaf(None, "not_implemented"),
            "slippage_estimate": leaf(None, "not_implemented"),
            "adverse_selection_risk": leaf(None, "not_implemented"),
            "quote_staleness_ms": leaf(None, "not_implemented"),
            "capacity_size_cap": leaf(None, "policy_object_pending"),
        },
        "greeks": {
            "delta": leaf(_num(chain_row.get("delta")), "v1_approximation" if chain_row.get("delta") is not None else "not_implemented"),
            "gamma": leaf(_num(chain_row.get("gamma")), "v1_approximation" if chain_row.get("gamma") is not None else "not_implemented"),
            "vega": leaf(_num(chain_row.get("vega")), "v1_approximation" if chain_row.get("vega") is not None else "not_implemented"),
            "theta": leaf(
                theta,
                theta_source,
                detail=theta_detail,
            ),
            "iv": leaf(_num(chain_row.get("volatility")), "v1_approximation" if chain_row.get("volatility") is not None else "not_implemented"),
            "delta_gamma_ratio": leaf(ms_dict.get("ratio"), "v1_approximation" if ms_dict.get("ratio") is not None else "not_implemented"),
            "gamma_x_oi": leaf(_gamma_x_oi(chain_row), "v1_approximation" if _gamma_x_oi(chain_row) is not None else "not_implemented"),
            "vol_oi_ratio": leaf(ms_dict.get("vol_oi"), "v1_approximation" if ms_dict.get("vol_oi") is not None else "not_implemented"),
        },
        "lifecycle": {
            "entry_policy": leaf(ms_dict.get("contract_context"), "v1_approximation" if ms_dict.get("contract_context") else "policy_object_pending"),
            "stop_policy": leaf(ms_dict.get("stop") or ms_dict.get("stop_display_text"), "v1_approximation" if (ms_dict.get("stop") or ms_dict.get("stop_display_text")) else "policy_object_pending"),
            "target_policy": leaf(ms_dict.get("target") or ms_dict.get("targets_display"), "v1_approximation" if (ms_dict.get("target") or ms_dict.get("targets_display")) else "policy_object_pending"),
            "timeout_policy": leaf(None, "policy_object_pending"),
            "forced_exit_time": leaf(None, "policy_object_pending"),
            "allowed_actions": leaf(["hold", "exit", "tighten", "scale_out", "convert", "force_exit"], "policy_object_pending"),
            "lifecycle_policy_id": leaf(None, "policy_object_pending"),
        },
        "health": {
            "hard_gates_failed": leaf(hard_gates, "v1_approximation"),
            "soft_gates": leaf(soft_gates, "v1_approximation"),
            "pin_risk": leaf(pin_risk, "v1_approximation"),
            "late_day_gamma": leaf(late_day_gamma, "v1_approximation"),
            "threshold_policy_objects": leaf(
                {
                    "quote_staleness": "a2_quote_staleness_threshold_ms",
                    "spread_hard": "a2_spread_hard_threshold",
                },
                "policy_object_pending",
            ),
        },
        "conformance_gaps": [
            {
                "component": component,
                "source": "not_implemented" if not component.endswith("_pending") else "policy_object_pending",
            }
            for component in REQUIRED_A2_GAPS
        ],
    }


def _hard_gates(
    *,
    ms_dict: dict[str, Any],
    proof: dict[str, Any],
    winner: dict[str, Any],
    chain_row: dict[str, Any],
    a1_action: Any,
    option_right: str,
    strike: float | None,
    bid: float | None,
    ask: float | None,
    theta: float | None,
) -> list[str]:
    gates: list[str] = []
    if str(a1_action or "").upper() != "TRADE":
        gates.append("module_a_signal_wait_or_unavailable")
    selected_expiry = _clean_str(ms_dict.get("call_option_expiry") or ms_dict.get("selected_exp"))
    if not selected_expiry:
        gates.append("missing_selected_expiry")
    elif _dte_value(ms_dict) != 0:
        gates.append("non_same_day_expiry_strict_0dte")
    if not proof:
        gates.append("missing_option_chain_selection_proof")
    elif proof.get("reason") == "no_contracts_for_side":
        gates.append("no_side_compatible_contracts")
    elif not winner or not chain_row:
        gates.append("missing_option_chain_selection_proof")
    if option_right not in ("CALL", "PUT"):
        gates.append("missing_option_right")
    if strike is None:
        gates.append("missing_selected_strike")
    if bid is None or ask is None:
        gates.append("missing_bid_or_ask")
    if theta is None:
        gates.append("theta_unavailable")
    return gates


def _soft_gates(
    ms_dict: dict[str, Any],
    *,
    pin_risk: dict[str, Any],
    late_day_gamma: dict[str, Any],
) -> list[str]:
    gates = [
        "a2_early_assignment_risk_not_implemented",
    ]
    if pin_risk.get("status") == "elevated":
        gates.append("pin_risk_near_strike")
    elif pin_risk.get("status") == "watch":
        gates.append("pin_risk_watch")
    if late_day_gamma.get("status") == "elevated":
        gates.append("late_day_gamma_acceleration")
    elif late_day_gamma.get("status") == "watch":
        gates.append("late_day_gamma_watch")
    if ms_dict.get("liq_ok") is False:
        gates.append("wide_spread_policy_pending")
    return gates


def _selected_audit_row(
    proof: dict[str, Any],
    winner: dict[str, Any],
    strike: float | None,
    option_right: str,
) -> dict[str, Any]:
    if strike is None:
        return dict(winner)
    side = str(option_right or "").upper()
    candidates = []
    for key in ("chain_rows_scored", "ranked_candidates_top5"):
        rows = proof.get(key)
        if isinstance(rows, list):
            candidates.extend(row for row in rows if isinstance(row, dict))
    for row in candidates:
        row_strike = _num(row.get("strike"))
        row_side = str(row.get("side") or "").upper()
        if row_strike is not None and abs(row_strike - strike) < 0.01 and (not side or row_side == side):
            return row
    return dict(winner)


def _pin_risk_health(
    *,
    selected_audit: dict[str, Any],
    strike: float | None,
) -> dict[str, Any]:
    detail = selected_audit.get("wall_contribution_detail")
    if not isinstance(detail, dict):
        detail = {}
    proximity = detail.get("proximity_detail")
    if not isinstance(proximity, list):
        proximity = []

    nearest_wall = None
    if strike is not None:
        for item in proximity:
            if not isinstance(item, dict):
                continue
            wall_strike = _num(item.get("strike"))
            if wall_strike is None:
                continue
            distance = abs(wall_strike - strike)
            candidate = {
                "level": item.get("level"),
                "strike": wall_strike,
                "distance": round(distance, 4),
                "contrib": _num(item.get("contrib")),
            }
            if nearest_wall is None or distance < nearest_wall["distance"]:
                nearest_wall = candidate

    wall_score = _num(selected_audit.get("wall_score_component"))
    wall_proximity = _num(selected_audit.get("wall_proximity_component"))
    wall_bias = _num(selected_audit.get("wall_bias_component"))
    reasons: list[str] = []
    status = "not_detected"

    if nearest_wall and nearest_wall["distance"] <= 1.0:
        status = "elevated"
        reasons.append("selected_strike_near_gamma_or_oi_wall")
    elif wall_score is not None and wall_score >= 1.0:
        status = "watch"
        reasons.append("material_wall_contribution")
    elif wall_proximity is not None and wall_proximity >= 0.75:
        status = "watch"
        reasons.append("material_wall_proximity")

    return {
        "status": status,
        "selected_strike": strike,
        "nearest_wall": nearest_wall,
        "wall_score_component": wall_score,
        "wall_proximity_component": wall_proximity,
        "wall_bias_component": wall_bias,
        "bias_notes": detail.get("bias_notes") if isinstance(detail.get("bias_notes"), list) else [],
        "reasons": reasons,
    }


def _late_day_gamma_health(
    *,
    ms_dict: dict[str, Any],
    chain_row: dict[str, Any],
    selected_audit: dict[str, Any],
) -> dict[str, Any]:
    mins_to_close = _first_number(ms_dict.get("mins_to_close"), ms_dict.get("minutes_to_close"))
    gamma = _first_number(chain_row.get("gamma"), selected_audit.get("gamma"))
    gamma_x_oi = _first_number(_gamma_x_oi(chain_row), selected_audit.get("gamma_x_oi"))
    gamma_is_max = bool(selected_audit.get("gamma_is_max"))
    reasons: list[str] = []

    if mins_to_close is None:
        status = "unknown"
        reasons.append("missing_minutes_to_close")
    elif mins_to_close > 30:
        status = "not_detected"
    elif gamma_is_max or (gamma_x_oi is not None and abs(gamma_x_oi) >= 100):
        status = "elevated"
        reasons.append("final_30_minutes_with_material_gamma")
        if gamma_is_max:
            reasons.append("selected_strike_is_max_gamma")
    elif gamma is not None and abs(gamma) >= 0.05:
        status = "watch"
        reasons.append("final_30_minutes_with_elevated_contract_gamma")
    else:
        status = "not_detected"

    return {
        "status": status,
        "mins_to_close": mins_to_close,
        "gamma": gamma,
        "gamma_x_oi": gamma_x_oi,
        "gamma_is_max": gamma_is_max,
        "reasons": reasons,
    }


def _leaf_value(obj: dict[str, Any], *path: str) -> Any:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if isinstance(cur, dict) and "value" in cur:
        return cur.get("value")
    return cur


def _option_right(ms_dict: dict[str, Any], winner: dict[str, Any]) -> str:
    raw = ms_dict.get("call_option_right") or ms_dict.get("rec_side") or winner.get("side")
    right = str(raw or "").upper().strip()
    return right if right in ("CALL", "PUT") else "NONE"


def _handoff_mapping(a1_direction: Any) -> str:
    direction = str(a1_direction or "").lower()
    if direction == "long":
        return "LONG_TO_CALL"
    if direction == "short":
        return "SHORT_TO_PUT"
    return "NO_OPTION_EXPRESSION"


def _theta(
    *,
    chain_row: dict[str, Any],
    ms_dict: dict[str, Any],
    strike: float | None,
    option_right: str,
) -> tuple[float | None, str, str | None]:
    theta = _num(chain_row.get("theta"))
    if theta is not None:
        return theta, "v2_compliant", "schwab_chain_theta"

    raw = chain_row.get("raw")
    if isinstance(raw, dict):
        raw_theta = _num(raw.get("theta"))
        if raw_theta is not None:
            return raw_theta, "v2_compliant", "schwab_raw_theta"

    bs_theta = _black_scholes_theta(
        spot=_num(ms_dict.get("spot")),
        strike=strike,
        iv=_num(chain_row.get("volatility")),
        option_right=option_right,
        time_to_expiry_years=_time_to_expiry_years(ms_dict, chain_row),
    )
    if bs_theta is None:
        return None, "not_implemented", None
    return bs_theta, "v1_approximation", "black_scholes_approximation"


def _black_scholes_theta(
    *,
    spot: float | None,
    strike: float | None,
    iv: float | None,
    option_right: str,
    time_to_expiry_years: float | None,
    risk_free_rate: float = 0.05,
) -> float | None:
    if spot is None or strike is None or iv is None or time_to_expiry_years is None:
        return None
    if spot <= 0 or strike <= 0 or iv <= 0 or time_to_expiry_years <= 0:
        return None
    sigma = iv / 100.0 if iv > 3 else iv
    if sigma <= 0:
        return None
    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * sigma * sigma) * time_to_expiry_years
    ) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    first = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t)
    discount = math.exp(-risk_free_rate * time_to_expiry_years)
    if option_right == "CALL":
        annual_theta = first - risk_free_rate * strike * discount * _norm_cdf(d2)
    elif option_right == "PUT":
        annual_theta = first + risk_free_rate * strike * discount * _norm_cdf(-d2)
    else:
        return None
    return round(annual_theta / 365.0, 6)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _time_to_expiry_years(ms_dict: dict[str, Any], chain_row: dict[str, Any]) -> float | None:
    dte = _num(chain_row.get("daysToExpiration"))
    if dte is not None and dte > 0:
        return dte / 365.0
    mins = _num(ms_dict.get("mins_to_close"))
    if mins is not None and mins > 0:
        return mins / (365.0 * 24.0 * 60.0)
    hours = _num(ms_dict.get("hours_to_expiry"))
    if hours is not None and hours > 0:
        return hours / (365.0 * 24.0)
    return None


def _dte_value(ms_dict: dict[str, Any]) -> int | None:
    raw = str(ms_dict.get("dte_warn") or "")
    if "0DTE" in raw.upper():
        return 0
    return None


def _spread_from_bid_ask(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return round(ask - bid, 4)


def _breakeven(strike: float | None, option_right: str, mid: float | None) -> float | None:
    if strike is None or mid is None:
        return None
    if option_right == "CALL":
        return round(strike + mid, 4)
    if option_right == "PUT":
        return round(strike - mid, 4)
    return None


def _spread_quality(spread: float | None, liq_ok: bool) -> str:
    if spread is None:
        return "unknown"
    return "tight" if liq_ok else "wide_policy_pending"


def _gamma_x_oi(chain_row: dict[str, Any]) -> float | None:
    gamma = _num(chain_row.get("gamma"))
    oi = _num(chain_row.get("openInterest"))
    if gamma is None or oi is None:
        return None
    return round(gamma * oi, 4)


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _num(value)
        if parsed is not None:
            return parsed
    return None


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None

