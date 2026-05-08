"""Draft A2 options / 0DTE deterministic baseline adapter."""

from __future__ import annotations

import math
from typing import Any

from v2_decision.a2_eod_force_exit import derive_et_clock_from_decision_time_ms

from .a2_lifecycle_health import derive_a2_pin_risk_health, resolve_a2_option_right, select_a2_pin_risk_audit_row
from .a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES, build_a2_lifecycle_sidecar
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

A2_ADAPTER_GAP_REGISTRY = tuple(dict.fromkeys(REQUIRED_A2_GAPS + LIFECYCLE_GAP_NAMES))

# Per OPERATOR_DECISION_REGISTER.md O-20 (2026-05-05).
A2_QUOTE_STALENESS_THRESHOLD_MS = 2000

# Per OPERATOR_DECISION_REGISTER.md O-21 (2026-05-05).
A2_SPREAD_ABSOLUTE_THRESHOLD = 0.10
A2_SPREAD_RELATIVE_THRESHOLD_PCT = 0.10

HARD_GATE_CONTRACT_MAP = (
    {
        "contract_gate": "missing selected expiry",
        "status": "implemented",
        "gate_string": "missing_selected_expiry",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 159",
    },
    {
        "contract_gate": "selected expiry is not same-day when strict 0DTE",
        "status": "implemented",
        "gate_string": "non_same_day_expiry_strict_0dte",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 160",
    },
    {
        "contract_gate": "no option-chain archive / current chain rows for selected expiry",
        "status": "implemented",
        "gate_string": "missing_option_chain_selection_proof",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 161",
    },
    {
        "contract_gate": "no side-compatible contracts",
        "status": "implemented",
        "gate_string": "no_side_compatible_contracts",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 162",
    },
    {
        "contract_gate": "missing bid or ask for selected contract",
        "status": "implemented",
        "gate_string": "missing_bid_or_ask",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 163",
    },
    {
        "contract_gate": (
            "missing theta from chain row and Black" + "-" + "Scholes approximation inputs"
        ),
        "status": "implemented",
        "gate_string": "theta_unavailable",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md lines 119 and 164",
    },
    {
        "contract_gate": "invalid or stale quote timestamp",
        "status": "implemented",
        "gate_string": "missing_quote_timestamp|quote_stale_above_threshold",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 165; OPERATOR_DECISION_REGISTER.md O-20",
    },
    {
        "contract_gate": "spread exceeds governed hard threshold",
        "status": "implemented",
        "gate_string": "spread_exceeds_hard_threshold",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 166; OPERATOR_DECISION_REGISTER.md O-21",
    },
    {
        "contract_gate": "missing selected strike or option right",
        "status": "implemented",
        "gate_string": "missing_selected_strike|missing_option_right",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 167",
    },
    {
        "contract_gate": "Module A signal is WAIT or unavailable",
        "status": "implemented",
        "gate_string": "module_a_signal_wait_or_unavailable",
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 168",
    },
    {
        "contract_gate": "replay/live parity failing once validation status is available",
        "status": "deferred_slice_5",
        "gate_string": None,
        "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md line 169",
        "reason": "A2 live-vs-replay parity validation is not attached to runtime payloads until Slice 5.",
        "registered_gap": "a2_replay_live_parity_not_gating_runtime",
    },
)

HARD_GATE_ACTION_POLICY = {
    "hard_gate_action": "WAIT",
    "avoid_reserved_for": "future advisory-only soft-gate policy",
    "contract_ref": "PILOT_1B_A2_0DTE_CONTRACT.md lines 155-156",
}

_RTH_CLOSE_MINUTE_TOTAL = 16 * 60


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
    mid = _num(chain_row.get("mark"))
    if mid is None and bid is not None and ask is not None:
        b_leg, a_leg = bid, ask
        mid = round((b_leg + a_leg) / 2.0, 4)
    spread = _first_number(ms_dict.get("spread"), _spread_from_bid_ask(bid, ask))
    theta, theta_source, theta_detail = _theta(
        chain_row=chain_row,
        ms_dict=ms_dict,
        strike=strike,
        option_right=option_right,
    )
    quote_staleness_ms, quote_staleness_source = _quote_staleness_ms(
        ms_dict=ms_dict,
        chain_row=chain_row,
    )
    dte = _dte_value(ms_dict, chain_row)

    selected_audit = select_a2_pin_risk_audit_row(
        proof=proof,
        winner=winner,
        strike=strike,
        option_right=option_right,
    )
    pin_risk = derive_a2_pin_risk_health(
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
        mid=mid,
        spread=spread,
        theta=theta,
        quote_staleness_ms=quote_staleness_ms,
    )
    soft_gates = _soft_gates(ms_dict, pin_risk=pin_risk, late_day_gamma=late_day_gamma)
    # Slice 2 policy: hard readiness gates always suppress option recommendations
    # with WAIT. AVOID is reserved for a later advisory-only soft-gate policy.
    action = "TRADE" if not hard_gates else HARD_GATE_ACTION_POLICY["hard_gate_action"]

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
            "dte": leaf(
                dte,
                "v2_compliant" if dte is not None else "not_implemented",
                detail="schwab_chain_daysToExpiration" if dte is not None else "missing_schwab_daysToExpiration",
            ),
            "decision_plane": leaf("Tier C", "v2_compliant"),
            "authority_mode": leaf("advisory_non_authoritative", "v2_compliant"),
        },
        "handoff": {
            "a1_action": leaf(a1_action, "v1_approximation"),
            "a1_direction": leaf(a1_direction, "v1_approximation"),
            "mapping": leaf(_handoff_mapping(a1_direction), "v1_approximation"),
            "a2_disagreement_authority": leaf(
                "advisory_record_only",
                "v2_compliant",
                detail="PILOT_1B_A2_0DTE_CONTRACT.md line 149: A2 cannot veto A1 for trade-impacting purposes during Pilot 1B.",
            ),
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
            "quote_staleness_ms": leaf(quote_staleness_ms, quote_staleness_source),
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
            "sidecar": build_a2_lifecycle_sidecar(ms_dict),
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
            for component in A2_ADAPTER_GAP_REGISTRY
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
    mid: float | None,
    spread: float | None,
    theta: float | None,
    quote_staleness_ms: float | None,
) -> list[str]:
    gates: list[str] = []
    if str(a1_action or "").upper() != "TRADE":
        gates.append("module_a_signal_wait_or_unavailable")
    selected_expiry = _clean_str(ms_dict.get("call_option_expiry") or ms_dict.get("selected_exp"))
    if not selected_expiry:
        gates.append("missing_selected_expiry")
    elif _dte_value(ms_dict, chain_row) != 0:
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
    elif _spread_exceeds_hard_threshold(spread=spread, mid=mid):
        gates.append("spread_exceeds_hard_threshold")
    if theta is None:
        gates.append("theta_unavailable")
    if quote_staleness_ms is None:
        gates.append("missing_quote_timestamp")
    elif quote_staleness_ms > A2_QUOTE_STALENESS_THRESHOLD_MS:
        gates.append("quote_stale_above_threshold")
    return gates


def _spread_exceeds_hard_threshold(*, spread: float | None, mid: float | None) -> bool:
    if spread is None or mid is None or mid <= 0:
        return False
    threshold = min(A2_SPREAD_ABSOLUTE_THRESHOLD, A2_SPREAD_RELATIVE_THRESHOLD_PCT * mid)
    return spread > threshold


def _quote_staleness_ms(
    *,
    ms_dict: dict[str, Any],
    chain_row: dict[str, Any],
) -> tuple[int | None, str]:
    decision_time = _first_number(
        ms_dict.get("decision_time_ms"),
        ms_dict.get("server_time_ms"),
        ms_dict.get("timestamp_ms"),
    )
    quote_time = _first_number(chain_row.get("quoteTimeInLong"), _raw_value(chain_row, "quoteTimeInLong"))
    if decision_time is None or quote_time is None:
        return None, "not_implemented"
    return max(0, int(round(decision_time - quote_time))), "v2_compliant"


def _raw_value(chain_row: dict[str, Any], key: str) -> Any:
    raw = chain_row.get("raw")
    if isinstance(raw, dict):
        return raw.get(key)
    return None


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


def _late_day_gamma_health(
    *,
    ms_dict: dict[str, Any],
    chain_row: dict[str, Any],
    selected_audit: dict[str, Any],
) -> dict[str, Any]:
    mins_to_close = _mins_to_close(ms_dict)
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
    return resolve_a2_option_right(ms_dict, winner)


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
    mins = _mins_to_close(ms_dict)
    if mins is not None and mins > 0:
        return mins / (365.0 * 24.0 * 60.0)
    hours = _num(ms_dict.get("hours_to_expiry"))
    if hours is not None and hours > 0:
        return hours / (365.0 * 24.0)
    return None


def _dte_value(ms_dict: dict[str, Any], chain_row: dict[str, Any] | None = None) -> int | None:
    if isinstance(chain_row, dict):
        schwab_dte = _num(chain_row.get("daysToExpiration"))
        if schwab_dte is not None and schwab_dte >= 0:
            return int(schwab_dte)
    return None


def _spread_from_bid_ask(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    a_leg, b_leg = ask, bid
    return round(a_leg - b_leg, 4)


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


def _mins_to_close(ms_dict: dict) -> float | None:
    """Resolve minutes-to-close from explicit fields or decision timestamp."""
    explicit = _first_number(ms_dict.get("mins_to_close"), ms_dict.get("minutes_to_close"))
    if explicit is not None:
        return explicit

    decision_time_ms = ms_dict.get("decision_time_ms")
    if decision_time_ms is None:
        return None

    clock = derive_et_clock_from_decision_time_ms(decision_time_ms)
    if clock is None:
        return None
    et_hour, et_minute, _ = clock
    et_minute_total = et_hour * 60 + et_minute
    return max(0.0, float(_RTH_CLOSE_MINUTE_TOTAL - et_minute_total))


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

