"""Adapter from existing Tier C MarketState payloads to draft Module A/A1 v2."""

from __future__ import annotations

from typing import Any

from .a2_option_expression import build_a2_option_expression
from .a1_conformal_promotion import derive_a1_conformal_bounds
from .a1_raw_probability import dominant_probability
from .schema import SCHEMA_VERSION, V2_STATUS, leaf, validate_v2_decision


PRODUCT_HORIZONS = ("1m", "5m", "15m", "60m")
HORIZON_SLUGS = {"1m": "1c", "5m": "5c", "15m": "15c", "60m": "60c"}


def build_module_a_a1_decision(ms_dict: dict[str, Any]) -> dict[str, Any]:
    """Build an advisory v2 decision object for Pilot 1A.

    The adapter intentionally uses source="v1_approximation" for current fields
    and source="not_implemented"/"policy_object_pending" for v2 surfaces that are
    structurally present but not yet governed implementations.
    """
    decision: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "v2_status": V2_STATUS,
        "authority": {
            "mode": "advisory_non_authoritative",
            "tier": "C_analytics_only",
            "changes_trade_behavior": False,
            "banner": "Draft v2 view only. Does not replace the locked v1.1 decision policy.",
        },
        "strategy_module": {
            "id": leaf("A", "v1_approximation", detail="Short-horizon directional signal module."),
            "name": leaf("Short-horizon directional", "v1_approximation"),
            "horizon_set": leaf(list(PRODUCT_HORIZONS), "v1_approximation"),
        },
        "expression_profile": {
            "id": leaf("A1", "v1_approximation", detail="Equity/ETF expression profile."),
            "instrument_family": leaf("equity_etf", "v1_approximation"),
            "options_overlay": leaf(False, "v1_approximation"),
        },
        "decision": _decision_block(ms_dict),
        "edge_domains": _edge_domains(ms_dict),
        "trace": _trace_block(ms_dict),
        "conformance_gaps": [
            {
                "component": "module_a_validation_contract",
                "source": "not_implemented",
                "detail": "Purged OOF module-level validation contract is not yet bound to this adapter.",
            },
            {
                "component": "net_ev_after_execution_costs",
                "source": "not_implemented",
                "detail": "Current payload has execution proxies but no validated net EV model.",
            },
            {
                "component": "fractional_kelly_policy",
                "source": "policy_object_pending",
                "detail": "Current sizing fields are v1.1 approximations, not the v2 policy object.",
            },
            {
                "component": "post_trade_attribution_loop",
                "source": "not_implemented",
                "detail": "No v2 close-out attribution record is attached to this live decision.",
            },
        ],
    }
    decision["expression_profiles"] = {
        "A2": build_a2_option_expression(ms_dict, decision),
    }
    validate_v2_decision(decision)
    return decision


def _decision_block(ms: dict[str, Any]) -> dict[str, Any]:
    direction = _direction(ms)
    action = "WAIT" if direction == "neutral" else "TRADE"
    if ms.get("is_no_trade") is True or str(ms.get("execution_mode") or "").upper() == "NO_TRADE":
        action = "WAIT"
    probability = dominant_probability(ms)
    p_low, p_high, conformal_status = derive_a1_conformal_bounds(ms)
    conformal_source = "v1_approximation" if p_low is not None and p_high is not None else "not_implemented"
    conformal_detail = f"a1_conformal_interval:{conformal_status}"

    return {
        "action": leaf(action, "v1_approximation"),
        "direction": leaf(direction, "v1_approximation"),
        "probability": leaf(probability, "v1_approximation"),
        "P_entry_success": leaf(
            probability,
            "v1_approximation",
            detail="Closest current analog is the dominant v1 stack/fusion probability.",
        ),
        "P_lifecycle_adjusted_success": leaf(
            None,
            "not_implemented",
            detail="Requires v2 lifecycle and calibration adjustment contract.",
        ),
        "p_low": leaf(p_low, conformal_source, detail=conformal_detail),
        "p_high": leaf(p_high, conformal_source, detail=conformal_detail),
        "confidence": leaf(
            _confidence(ms),
            "v1_approximation",
            detail="Desk aggregate: multi_horizon_decision.final_confidence when present.",
        ),
        "net_expected_value_r": leaf(None, "not_implemented", detail="Requires v2 execution-adjusted EV."),
        "EV_lower": leaf(None, "not_implemented", detail="Requires execution-adjusted EV using p_low."),
        "EV_upper": leaf(None, "not_implemented", detail="Requires execution-adjusted EV using p_high."),
        "position_size_fraction": leaf(_position_size_fraction(ms), "v1_approximation"),
        "entry": leaf(_first_present(ms, "entry", "entry_price", "rec_entry"), "v1_approximation"),
        "stop": leaf(ms.get("stop"), "v1_approximation"),
        "targets": leaf(_targets(ms), "v1_approximation"),
        "timeout": leaf(None, "policy_object_pending", detail="V2 timeout policy is not implemented."),
        "invalidation": leaf(ms.get("invalidation") or ms.get("risk_note") or "", "v1_approximation"),
        "decision_latency_budget_ms": leaf(None, "policy_object_pending"),
    }


def _edge_domains(ms: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal": {
            "status": leaf("approximated_from_v1_stack", "v1_approximation"),
            "primary_evidence": leaf(
                [
                    _compact_none(ms.get("fusion_summary")),
                    _compact_none(ms.get("rules_headline")),
                    _compact_none(ms.get("micro_5m_headline")),
                ],
                "v1_approximation",
            ),
            "horizon_alignment": leaf(_horizon_alignment(ms), "v1_approximation"),
        },
        "implementation": {
            "status": leaf("not_v2_validated", "not_implemented"),
            "spread": leaf(ms.get("spread"), "v1_approximation"),
            "slippage_model": leaf(None, "not_implemented"),
            "fill_probability": leaf(None, "not_implemented"),
            "adverse_selection": leaf(None, "not_implemented"),
        },
        "portfolio": {
            "status": leaf("policy_pending", "policy_object_pending"),
            "cross_sectional_rank": leaf(None, "not_implemented"),
            "correlation_adjusted_size": leaf(None, "policy_object_pending"),
            "risk_budget_state": leaf(ms.get("execution_mode"), "v1_approximation"),
        },
        "lifecycle": {
            "status": leaf("partially_available", "v1_approximation"),
            "calibration_state": leaf(ms.get("calibration_state"), "not_implemented"),
            "drift_state": leaf(ms.get("drift_state"), "not_implemented"),
            "post_trade_attribution": leaf(
                {
                    "status": "schema_and_log_sink_available",
                    "live_close_out_record_attached": False,
                    "learning_enabled": False,
                },
                "not_implemented",
                detail="Log-only scaffold exists; no live close-out hook, replay binding, or learning loop is attached.",
            ),
        },
    }


def _trace_block(ms: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_payload": leaf("Tier C MarketState", "v1_approximation"),
        "decision_generation_id": leaf(ms.get("decision_generation_id"), "v1_approximation"),
        "server_build_ts": leaf(ms.get("_server_build_ts"), "v1_approximation"),
        "stack_runtime": leaf(ms.get("stack_runtime"), "v1_approximation"),
        "stack_governance": leaf(ms.get("stack_governance"), "v1_approximation"),
        "signal_chain": leaf(ms.get("signal_chain"), "v1_approximation"),
        "counterfactual_sensitivity": leaf(
            None,
            "not_implemented",
            detail="Generalized 'what would change the answer' trace is pending.",
        ),
    }


def _direction(ms: dict[str, Any]) -> str:
    raw = (
        ms.get("fusion_dominant_direction")
        if ms.get("fusion_available")
        else ms.get("dominant_dir")
    ) or ms.get("prediction_dir") or ms.get("final_bias")
    s = str(raw or "").strip().lower()
    if s in ("up", "long", "bull", "bullish", "call"):
        return "long"
    if s in ("down", "short", "bear", "bearish", "put"):
        return "short"
    return "neutral"


def _desk_confidence_value(ms: dict[str, Any]) -> float | None:
    """Desk aggregate from multi_horizon_decision (Pilot 1 A1 headline)."""
    fc = ms.get("final_confidence")
    if fc is None:
        return None
    try:
        return round(float(fc), 4)
    except (TypeError, ValueError):
        return None


def _confidence(ms: dict[str, Any]) -> float | None:
    """Advisory v2 confidence leaf — same numeric as Decision Command desk headline."""
    return _desk_confidence_value(ms)


def _position_size_fraction(ms: dict[str, Any]) -> float | None:
    r_units = ms.get("r_units")
    try:
        if r_units is not None:
            return round(float(r_units), 4)
    except (TypeError, ValueError):
        return None
    return None


def _targets(ms: dict[str, Any]) -> list[Any]:
    values = []
    for key in ("target", "target2"):
        if ms.get(key) is not None:
            values.append(ms.get(key))
    return values


def _horizon_alignment(ms: dict[str, Any]) -> dict[str, Any]:
    rows = ms.get("mhap_rows")
    if not isinstance(rows, list):
        rows = []
    by_horizon = {
        str(row.get("horizon") or "").lower(): row
        for row in rows
        if isinstance(row, dict)
    }
    out: dict[str, Any] = {}
    for label, slug in HORIZON_SLUGS.items():
        row = by_horizon.get(slug, {})
        out[label] = {
            "call": row.get("call"),
            "confidence": row.get("confidence"),
            "role": row.get("role"),
        }
    return out


def _first_present(ms: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = ms.get(key)
        if value is not None:
            return value
    return None


def _compact_none(value: Any) -> Any:
    return None if value is None or value == "" else value

