"""Draft A2 options / 0DTE deterministic baseline adapter."""

from __future__ import annotations

import math
from typing import Any

from v2_decision.a2_eod_force_exit import derive_et_clock_from_decision_time_ms

from .a2_lifecycle_health import (
    derive_a2_pin_risk_health,
    resolve_a2_option_right_with_source,
    select_a2_pin_risk_audit_row,
)
from .a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES, build_a2_lifecycle_sidecar
from .a2_price_precedence import (
    resolve_a2_contract_mid,
    resolve_a2_contract_spread,
    resolve_a2_underlying_spread_pts,
)
from math_exposure import MISSING_GREEK_SENTINEL

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

# OP-008: Black-Scholes theta residual disabled unless explicitly governed on.
_A2_THETA_BS_FALLBACK_GOVERNED = False

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
    # Schwab-first precedence: chain_row.putCall is the authoritative source;
    # app-side aliases (call_option_right, rec_side, winner.side) are legacy
    # fallbacks only when the Schwab field is absent. Per
    # SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1 OP-011.
    option_right, option_right_source = resolve_a2_option_right_with_source(ms_dict, winner)
    # strike is Schwab-direct (chains.*.strikePrice) when read off the
    # selected chain row via the winner. The ms_dict alias `rec_strike` is a
    # legacy app-side fallback; check the Schwab leaf first via the winner's
    # chain row, then winner.strike (from selection), then ms.rec_strike.
    chain_row_strike = _num(chain_row.get("strikePrice"))
    strike = _first_number(chain_row_strike, winner.get("strike"), ms_dict.get("rec_strike"))
    if chain_row_strike is not None:
        strike_source: str | None = "schwab_chain_strikePrice"
    elif _num(winner.get("strike")) is not None:
        strike_source = "schwab_chain_strikePrice"  # winner.strike is sourced from the chain row
    elif _num(ms_dict.get("rec_strike")) is not None:
        strike_source = None  # legacy app-side fallback
    else:
        strike_source = None
    bid = _num(chain_row.get("bid"))
    ask = _num(chain_row.get("ask"))

    mid, mid_source = resolve_a2_contract_mid(chain_row=chain_row)
    spread, spread_source = resolve_a2_contract_spread(bid=bid, ask=ask)
    underlying_spread_pts, underlying_spread_source = resolve_a2_underlying_spread_pts(
        ms_dict=ms_dict
    )

    iv_val: float | None = None
    iv_detail = None
    iv_raw = _num(chain_row.get("volatility"))
    if iv_raw is not None and iv_raw > 0 and iv_raw != MISSING_GREEK_SENTINEL and math.isfinite(iv_raw):
        iv_val = float(iv_raw)
        iv_detail = "schwab_chain_volatility"
    if iv_val is None:
        tv_raw = _num(chain_row.get("theoreticalVolatility"))
        if tv_raw is not None and tv_raw > 0 and tv_raw != MISSING_GREEK_SENTINEL and math.isfinite(tv_raw):
            iv_val = float(tv_raw)
            iv_detail = "schwab_chain_theoreticalVolatility"

    delta_raw = _num(chain_row.get("delta"))
    if delta_raw is not None and delta_raw != MISSING_GREEK_SENTINEL and math.isfinite(delta_raw):
        delta_val: float | None = float(delta_raw)
        delta_detail = "schwab_chain_delta"
    else:
        delta_val = None
        delta_detail = None

    gamma_raw = _num(chain_row.get("gamma"))
    if gamma_raw is not None and gamma_raw != MISSING_GREEK_SENTINEL and math.isfinite(gamma_raw):
        gamma_val: float | None = float(gamma_raw)
        gamma_detail = "schwab_chain_gamma"
    else:
        gamma_val = None
        gamma_detail = None

    vega_raw = _num(chain_row.get("vega"))
    if vega_raw is not None and vega_raw != MISSING_GREEK_SENTINEL and math.isfinite(vega_raw):
        vega_val: float | None = float(vega_raw)
        vega_detail = "schwab_chain_vega"
    else:
        vega_val = None
        vega_detail = None

    theta, theta_source, theta_detail = _theta(
        chain_row=chain_row,
        ms_dict=ms_dict,
        strike=strike,
        option_right=option_right,
        iv_for_bs=iv_val,
    )
    gamma_x_oi_val = _gamma_x_oi(chain_row)
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
    liq_ok_val = _liq_ok_value(ms_dict)

    # Schwab-first selected_expiry: chain_row.expirationDate is the
    # authoritative source (the selected contract's Schwab-native expiry).
    # ms_dict aliases are legacy fallbacks only when the chain row is absent.
    selected_expiry_value, selected_expiry_source, selected_expiry_detail = _resolve_selected_expiry(
        ms_dict, chain_row
    )

    underlying_ticker_value = _clean_str(ms_dict.get("ticker"))
    return {
        "identity": {
            "module_id": leaf("A", "v1_approximation"),
            "expression_profile_id": leaf("A2", "v2_compliant"),
            "instrument_family": leaf("options_0dte", "v2_compliant"),
            "underlying_ticker": leaf(
                underlying_ticker_value,
                "v2_compliant" if underlying_ticker_value else "not_implemented",
                detail="chains.symbol" if underlying_ticker_value else None,
            ),
            "selected_expiry": leaf(
                selected_expiry_value,
                selected_expiry_source if selected_expiry_value else "not_implemented",
                detail=selected_expiry_detail,
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
            "option_right": leaf(
                option_right if action != "WAIT" else "NONE",
                # Schwab-direct read of chains.*.putCall when source is the
                # chain row; legacy app-side aliases keep v1_approximation.
                "v2_compliant" if (action != "WAIT" and option_right_source == "chains.*.putCall") else "v1_approximation",
                detail=option_right_source if (action != "WAIT" and option_right_source == "chains.*.putCall") else None,
            ),
            "strike": leaf(
                strike if action != "WAIT" else None,
                # strike comes from the Schwab chain row (strikePrice). It is
                # only labeled v1_approximation when the value resolved purely
                # from the legacy ms.rec_strike alias with no chain row.
                "v2_compliant" if (action != "WAIT" and strike_source == "schwab_chain_strikePrice") else "v1_approximation",
                detail=strike_source if (action != "WAIT" and strike_source == "schwab_chain_strikePrice") else None,
            ),
            "contract_symbol": leaf(
                chain_row.get("symbol"),
                "v2_compliant" if chain_row.get("symbol") else "not_implemented",
                detail="schwab_chain_symbol" if chain_row.get("symbol") else None,
            ),
            "bid": leaf(
                bid,
                "v2_compliant" if bid is not None else "not_implemented",
                detail="schwab_chain_bid" if bid is not None else None,
            ),
            "ask": leaf(
                ask,
                "v2_compliant" if ask is not None else "not_implemented",
                detail="schwab_chain_ask" if ask is not None else None,
            ),
            "mid": leaf(mid, "v1_approximation" if mid is not None else "not_implemented"),
            "mid_source": leaf(mid_source, "v2_compliant" if mid_source else "not_implemented"),
            "spread": leaf(spread, "v1_approximation" if spread is not None else "not_implemented"),
            "spread_source": leaf(
                spread_source, "v2_compliant" if spread_source else "not_implemented"
            ),
            "underlying_spread_pts": leaf(
                underlying_spread_pts,
                "v2_compliant" if underlying_spread_source else "not_implemented",
            ),
            "underlying_spread_source": leaf(
                underlying_spread_source,
                "v2_compliant" if underlying_spread_source else "not_implemented",
            ),
            "max_loss": leaf(None, "policy_object_pending"),
            "breakeven": leaf(_breakeven(strike, option_right, mid), "v1_approximation" if mid is not None else "not_implemented"),
            # selected_contract_snapshot is the literal Schwab chain row
            # passthrough — every field on it is a Schwab wire leaf.
            "selected_contract_snapshot": leaf(
                chain_row or None,
                "v2_compliant" if chain_row else "not_implemented",
                detail="schwab_chain_row_snapshot" if chain_row else None,
            ),
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
            "liquidity_gate_pass": leaf(
                liq_ok_val,
                "v1_approximation" if liq_ok_val is not None else "not_implemented",
            ),
            "spread_quality": leaf(_spread_quality(spread, liq_ok_val), "v1_approximation"),
            "fill_probability": leaf(None, "not_implemented"),
            "slippage_estimate": leaf(None, "not_implemented"),
            "adverse_selection_risk": leaf(None, "not_implemented"),
            "quote_staleness_ms": leaf(quote_staleness_ms, quote_staleness_source),
            "capacity_size_cap": leaf(None, "policy_object_pending"),
        },
        "greeks": {
            "delta": leaf(
                delta_val,
                "v2_compliant" if delta_detail else "not_implemented",
                detail=delta_detail,
            ),
            "gamma": leaf(
                gamma_val,
                "v2_compliant" if gamma_detail else "not_implemented",
                detail=gamma_detail,
            ),
            "vega": leaf(
                vega_val,
                "v2_compliant" if vega_detail else "not_implemented",
                detail=vega_detail,
            ),
            "theta": leaf(
                theta,
                theta_source,
                detail=theta_detail,
            ),
            "iv": leaf(
                iv_val,
                "v2_compliant" if iv_detail else "not_implemented",
                detail=iv_detail,
            ),
            "delta_gamma_ratio": leaf(ms_dict.get("ratio"), "v1_approximation" if ms_dict.get("ratio") is not None else "not_implemented"),
            "gamma_x_oi": leaf(
                gamma_x_oi_val,
                "v1_approximation" if gamma_x_oi_val is not None else "not_implemented",
                detail="derived_schwab_gamma_x_openInterest" if gamma_x_oi_val is not None else None,
            ),
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
    selected_expiry, _, _ = _resolve_selected_expiry(ms_dict, chain_row)
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
    elif spread is None or mid is None:
        # Fail-closed: cannot evaluate O-21 spread policy without contract mid + spread.
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


def _parse_schwab_time_ms(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        ts_f = float(raw)
        if math.isfinite(ts_f):
            return int(ts_f)
    except (TypeError, ValueError):
        return None
    return None


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
    qt_raw = chain_row.get("quoteTimeInLong")
    if qt_raw is None:
        raw = chain_row.get("raw")
        if isinstance(raw, dict):
            qt_raw = raw.get("quoteTimeInLong")
    quote_time = _parse_schwab_time_ms(qt_raw)
    source = "v2_compliant"
    if quote_time is None:
        tt_raw = chain_row.get("tradeTimeInLong")
        if tt_raw is None and isinstance(chain_row.get("raw"), dict):
            tt_raw = chain_row["raw"].get("tradeTimeInLong")
        trade_time = _parse_schwab_time_ms(tt_raw)
        if trade_time is not None:
            quote_time = trade_time
            source = "v2_compliant_tradeTimeInLong_governed_fallback"
    if decision_time is None or quote_time is None:
        return None, "not_implemented"
    return max(0, int(round(decision_time - quote_time))), source


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
    chain_gamma_raw = _num(chain_row.get("gamma"))
    if (chain_gamma_raw is not None and chain_gamma_raw != MISSING_GREEK_SENTINEL
            and math.isfinite(chain_gamma_raw)):
        chain_gamma: float | None = float(chain_gamma_raw)
    else:
        chain_gamma = None
    gamma = _first_number(chain_gamma, selected_audit.get("gamma"))
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
    iv_for_bs: float | None = None,
) -> tuple[float | None, str, str | None]:
    theta_raw = _num(chain_row.get("theta"))
    if theta_raw is not None and theta_raw != MISSING_GREEK_SENTINEL and math.isfinite(theta_raw):
        return float(theta_raw), "v2_compliant", "schwab_chain_theta"

    raw = chain_row.get("raw")
    if isinstance(raw, dict):
        raw_theta = _num(raw.get("theta"))
        if raw_theta is not None and raw_theta != MISSING_GREEK_SENTINEL and math.isfinite(raw_theta):
            return float(raw_theta), "v2_compliant", "schwab_raw_theta"

    if not _A2_THETA_BS_FALLBACK_GOVERNED:
        return None, "not_implemented", "schwab_theta_missing"
    bs_theta = _black_scholes_theta(
        spot=_num(ms_dict.get("spot")),
        strike=strike,
        iv=iv_for_bs,
        option_right=option_right,
        time_to_expiry_years=_time_to_expiry_years(ms_dict, chain_row),
    )
    if bs_theta is None:
        return None, "not_implemented", None
    return bs_theta, "v1_approximation", "black_scholes_approximation_governed"


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
    # RC-345 / F13: the Black-Scholes valuation year-fraction has ONE authority,
    # time_et.time_to_expiry_years (intraday ACT/365 to session close). Vendor
    # daysToExpiration stays an INPUT (it supplies the expiry DATE); the as-of is the
    # decision timestamp so replay is priced at its own moment, not the wall clock. T is NOT
    # re-derived here as a local whole-day dte/365 — that was a second valuation-T authority
    # disagreeing with the charm/gamma/vanna clock near expiry.
    from datetime import datetime
    from time_et import time_to_expiry_years as _tte, ET

    exp = str(chain_row.get("expirationDate") or "")[:10]
    decision_time_ms = ms_dict.get("decision_time_ms")
    ref = None
    if decision_time_ms is not None:
        try:
            ref = datetime.fromtimestamp(float(decision_time_ms) / 1000.0, tz=ET)
        except (TypeError, ValueError, OSError, OverflowError):
            ref = None
    if len(exp) == 10 and ref is not None:
        # Canonical authority (returns None at/after settlement — itself fail-closed).
        return _tte(exp, now=ref)
    # RC-345 / F13: the expiry DATE or the decision as-of is unavailable, so the ONE BS-T
    # authority (time_et.time_to_expiry_years) cannot be evaluated. FAIL CLOSED. A local
    # minutes/year or hours/year fraction here would be a second valuation-T producer of the
    # same semantic — exactly what the one-producer law forbids — so it is deleted, not kept
    # as a "governed" substitute. No greeks without the canonical clock.
    return None


def _dte_value(ms_dict: dict[str, Any], chain_row: dict[str, Any] | None = None) -> int | None:
    if isinstance(chain_row, dict):
        schwab_dte = _num(chain_row.get("daysToExpiration"))
        if schwab_dte is not None and schwab_dte >= 0:
            return int(schwab_dte)
    return None


# RC-345 / F23: _spread_from_bid_ask was RETIRED — it was a dead helper (no live caller). The
# live spread authority is a2_price_precedence.contract_spread_pts_from_bid_ask (used by
# resolve_a2_contract_spread at line ~175), which withholds crossed quotes. Fixing the dead
# helper was theater; the real authority carries the invariant.


def _breakeven(strike: float | None, option_right: str, mid: float | None) -> float | None:
    if strike is None or mid is None:
        return None
    if option_right == "CALL":
        return round(strike + mid, 4)
    if option_right == "PUT":
        return round(strike - mid, 4)
    return None


def _resolve_selected_expiry(
    ms_dict: dict[str, Any],
    chain_row: dict[str, Any],
) -> tuple[str | None, str, str | None]:
    """Schwab-first expiry: chain_row.expirationDate, then ms_dict legacy aliases."""
    chain_row_exp = _clean_str(chain_row.get("expirationDate")) if isinstance(chain_row, dict) else None
    if chain_row_exp:
        return chain_row_exp, "v2_compliant", "schwab_chain_expirationDate"
    legacy = _clean_str(ms_dict.get("call_option_expiry") or ms_dict.get("selected_exp"))
    if legacy:
        return legacy, "v1_approximation", None
    return None, "not_implemented", None


def _liq_ok_value(ms_dict: dict[str, Any]) -> bool | None:
    if "liq_ok" not in ms_dict:
        return None
    raw = ms_dict.get("liq_ok")
    if raw is None:
        return None
    return bool(raw)


def _spread_quality(spread: float | None, liq_ok: bool | None) -> str:
    if spread is None or liq_ok is None:
        return "unknown"
    return "tight" if liq_ok else "wide_policy_pending"


def _gamma_x_oi(chain_row: dict[str, Any]) -> float | None:
    gamma_raw = _num(chain_row.get("gamma"))
    if gamma_raw is None or gamma_raw == MISSING_GREEK_SENTINEL or not math.isfinite(gamma_raw):
        return None
    gamma = float(gamma_raw)
    oi = _num(chain_row.get("openInterest"))
    if oi is None:
        return None
    return round(gamma * oi, 4)


def _mins_to_close(ms_dict: dict) -> float | None:
    """Resolve minutes-to-close from explicit fields or decision timestamp."""
    # RC-381 slice 3: the `minutes_to_close` alias that used to sit beside this was dead.
    # `mins_to_close` IS written in production Python; `git log --all -S '"minutes_to_close":'
    # -- '*.py'` finds ZERO non-test commits writing it as a payload key, so the alias could
    # never contribute a value and only widened the surface for a silent None (RC-15/RC-20).
    explicit = _first_number(ms_dict.get("mins_to_close"))
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
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None

