"""A2 lifecycle advisory sidecar.

At entry time there is no active position to manage, so the root sidecar state
remains posture alpha. ``projected_preview`` is a pre-entry projection only and
never claims active lifecycle decision authority.
"""

from __future__ import annotations

from typing import Any

from lifecycle_rule_core import (
    LIFECYCLE_RULE_CORE_VERSION,
    derive_stop_distance_pct,
    derive_target_levels,
)


LIFECYCLE_GAP_NAMES = (
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
    "a2_lifecycle_promotion_to_runtime_authority_not_authorized",
)

THRESHOLD_POLICY_OBJECTS = (
    "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
    "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
)

PREVIEW_BLOCKING_GAPS = (
    "a2_lifecycle_eod_force_exit_logic_not_implemented",
    "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
    "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
)

PROMOTION_CRITERIA = (
    (
        "replay_live_parity_passing",
        "Replay/live parity exists for the static rule core, but lifecycle sidecar behavior is not validated as a promoted runtime authority.",
    ),
    (
        "bound_threshold_policies",
        "Lifecycle threshold policy objects remain unbound.",
    ),
    (
        "empirical_improvement_over_static_baseline",
        "No dynamic lifecycle candidate has demonstrated improvement over the static baseline.",
    ),
    (
        "uncertainty_disclosure",
        "No conformal or uncertainty disclosure exists for lifecycle decisions.",
    ),
    (
        "a2_replay_label_validation",
        "A2 replay labels exist as a scaffold but are not validated as a lifecycle label source.",
    ),
    (
        "post_trade_attribution_coherence",
        "Lifecycle sidecar outcomes are not reconciled to realized PnL through post-trade attribution.",
    ),
    (
        "operator_decision_register_approval",
        "No operator decision register entry promotes lifecycle behavior to runtime authority.",
    ),
)


def build_a2_lifecycle_sidecar(ms_dict: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the advisory lifecycle sidecar for A2."""
    ms = ms_dict if isinstance(ms_dict, dict) else {}
    return {
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
            {"id": policy_id, "source": "policy_object_pending"}
            for policy_id in THRESHOLD_POLICY_OBJECTS
        ],
        "named_gaps": list(LIFECYCLE_GAP_NAMES),
        "source_classification": {
            "inputs": "schwab_native_normalized",
            "decision": "derived_because_schwab_does_not_provide",
            "thresholds": "policy_object_pending",
        },
        "promotion_state": {
            criterion: {"satisfied": False, "reason": reason}
            for criterion, reason in PROMOTION_CRITERIA
        },
        "projected_preview": _build_projected_preview(ms),
    }


def _build_projected_preview(ms: dict[str, Any]) -> dict[str, Any]:
    inputs = _derivation_inputs(ms)
    none_fields = _projected_fields(
        stop=None,
        target=None,
        target2=None,
        max_hold_bars=None,
        eod_force_exit_time=None,
        source="not_implemented",
    )

    if not _has_entry_candidate(ms, inputs):
        return _preview(
            status="not_available_no_entry_candidate",
            projected_fields=none_fields,
            derivation_inputs=inputs,
            timestamp=_decision_timestamp(ms),
            gaps=[],
        )

    missing_required = [
        key
        for key in ("spot", "mins_elapsed_since_open", "entry", "direction", "risk")
        if inputs[key]["value"] is None
    ]
    if missing_required:
        for key in missing_required:
            inputs[key]["detail"] = "missing_required_preview_input"
        return _preview(
            status="not_available_missing_inputs",
            projected_fields=none_fields,
            derivation_inputs=inputs,
            timestamp=_decision_timestamp(ms),
            gaps=[],
        )

    direction = str(inputs["direction"]["value"])
    entry = float(inputs["entry"]["value"])
    risk = float(inputs["risk"]["value"])
    stop_distance = derive_stop_distance_pct(
        spot=float(inputs["spot"]["value"]),
        vix_level=_float_or_none(inputs["vix_level"]["value"]),
        mins_elapsed_since_open=float(inputs["mins_elapsed_since_open"]["value"]),
        risk_multiplier=_float_or_none(inputs["risk_multiplier"]["value"]),
    )
    stop_offset = stop_distance.final_pct * float(inputs["spot"]["value"])
    stop = entry - stop_offset if direction == "long" else entry + stop_offset
    targets = derive_target_levels(
        entry=entry,
        direction=direction,
        risk=risk,
        avg5=_float_or_none(inputs["avg5"]["value"]),
        avg15=_float_or_none(inputs["avg15"]["value"]),
        avg60=_float_or_none(inputs["avg60"]["value"]),
        structural_levels=inputs["structural_levels"]["value"] or [],
    )

    # `available` is unreachable in v1 while EOD force-exit logic remains a
    # named gap; required stop/target geometry can be projected, but the preview
    # is still policy_pending until the EOD/time-stop blockers close.
    return _preview(
        status="policy_pending",
        projected_fields=_projected_fields(
            stop=round(stop, 2),
            target=targets.target,
            target2=targets.target2,
            max_hold_bars=None,
            eod_force_exit_time=None,
            source="v2_compliant",
        ),
        derivation_inputs=inputs,
        timestamp=_decision_timestamp(ms),
        gaps=list(PREVIEW_BLOCKING_GAPS),
    )


def _preview(
    *,
    status: str,
    projected_fields: dict[str, dict[str, Any]],
    derivation_inputs: dict[str, dict[str, Any]],
    timestamp: Any,
    gaps: list[str],
) -> dict[str, Any]:
    return {
        "preview_status": status,
        "preview_named_gaps": gaps,
        **projected_fields,
        "derivation_inputs": derivation_inputs,
        "derivation_source_module": "lifecycle_rule_core",
        "would_apply_if_entered_at_time": timestamp,
        "preview_authority": {
            "mode": "advisory_non_authoritative",
            "tier": "C_analytics_only",
            "changes_trade_behavior": False,
            "projection_not_decision": True,
            "text": "Projected lifecycle preview only; not an active lifecycle decision. Future lifecycle action may differ.",
        },
    }


def _projected_fields(
    *,
    stop: float | None,
    target: float | None,
    target2: float | None,
    max_hold_bars: int | None,
    eod_force_exit_time: Any,
    source: str,
) -> dict[str, dict[str, Any]]:
    fields = {
        "projected_stop": _classified_leaf(stop, source, "derived_because_schwab_does_not_provide"),
        "projected_target": _classified_leaf(target, source, "derived_because_schwab_does_not_provide"),
        "projected_target2": _classified_leaf(target2, source, "derived_because_schwab_does_not_provide"),
        "projected_max_hold_bars": _classified_leaf(max_hold_bars, "policy_object_pending", "policy_object_pending"),
        "projected_eod_force_exit_time": _classified_leaf(eod_force_exit_time, "policy_object_pending", "policy_object_pending"),
    }
    if source == "not_implemented":
        fields["projected_max_hold_bars"] = _classified_leaf(None, "not_implemented", "policy_object_pending")
        fields["projected_eod_force_exit_time"] = _classified_leaf(None, "not_implemented", "policy_object_pending")
    return fields


def _derivation_inputs(ms: dict[str, Any]) -> dict[str, dict[str, Any]]:
    direction = _direction(ms)
    spot = _first_number(ms, "spot")
    entry = _first_number(ms, "entry", "rec_entry")
    mins_elapsed = _mins_elapsed_since_open(ms)
    risk = _risk(ms=ms, entry=entry, direction=direction, spot=spot, mins_elapsed=mins_elapsed)
    structural_levels = _structural_levels(ms, direction)
    values = {
        "spot": spot,
        "vix_level": _first_number(ms, "vix_level", "vix"),
        "mins_elapsed_since_open": mins_elapsed,
        "risk_multiplier": _first_number(ms, "vol_regime_risk_multiplier", "risk_multiplier"),
        "entry": entry,
        "direction": direction,
        "risk": risk,
        "avg5": _first_number(ms, "avg_5c_pts", "avg5"),
        "avg15": _first_number(ms, "avg_15c_pts", "avg15"),
        "avg60": _first_number(ms, "avg_60c_pts", "avg60"),
        "structural_levels": structural_levels,
    }
    return {
        key: _input_leaf(value, "missing_from_ms_dict" if value is None else "schwab_native_normalized")
        for key, value in values.items()
    }


def _input_leaf(value: Any, source_classification: str) -> dict[str, Any]:
    if source_classification == "missing_from_ms_dict":
        return {
            "value": None,
            "source": "not_implemented",
            "source_classification": source_classification,
        }
    return {
        "value": value,
        "source": "v1_approximation",
        "source_classification": source_classification,
    }


def _classified_leaf(value: Any, source: str, source_classification: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "source_classification": source_classification,
    }


def _has_entry_candidate(ms: dict[str, Any], inputs: dict[str, dict[str, Any]]) -> bool:
    if ms.get("is_no_trade") is True or str(ms.get("execution_mode") or "").upper() == "NO_TRADE":
        return False
    proof = ms.get("option_chain_selection_proof")
    if not isinstance(proof, dict):
        return False
    winner = proof.get("winner")
    if not isinstance(winner, dict):
        return False
    chain_row = winner.get("chain_row")
    if not isinstance(chain_row, dict) or not chain_row:
        return False
    return inputs["direction"]["value"] in ("long", "short")


def _direction(ms: dict[str, Any]) -> str | None:
    raw = ms.get("call_signal") or ms.get("final_signal") or ms.get("direction")
    s = str(raw or "").strip().lower()
    if s in ("long", "up", "bull", "bullish", "call"):
        return "long"
    if s in ("short", "down", "bear", "bearish", "put"):
        return "short"
    return None


def _mins_elapsed_since_open(ms: dict[str, Any]) -> float | None:
    explicit = _first_number(ms, "mins_elapsed_since_open", "minutes_since_open")
    if explicit is not None:
        return max(0.0, explicit)
    et_hour = _first_number(ms, "et_hour")
    et_minute = _first_number(ms, "et_minute")
    if et_hour is None or et_minute is None:
        return None
    return max(0.0, et_hour * 60 + et_minute - 570)


def _risk(
    *,
    ms: dict[str, Any],
    entry: float | None,
    direction: str | None,
    spot: float | None,
    mins_elapsed: float | None,
) -> float | None:
    existing_stop = _first_number(ms, "stop", "rec_stop")
    if entry is not None and existing_stop is not None:
        risk = abs(entry - existing_stop)
        return round(risk, 4) if risk > 0 else None
    if entry is None or direction not in ("long", "short") or spot is None or mins_elapsed is None:
        return None
    stop_distance = derive_stop_distance_pct(
        spot=spot,
        vix_level=_first_number(ms, "vix_level", "vix"),
        mins_elapsed_since_open=mins_elapsed,
        risk_multiplier=_first_number(ms, "vol_regime_risk_multiplier", "risk_multiplier"),
    )
    risk = stop_distance.final_pct * spot
    return round(risk, 4) if risk > 0 else None


def _structural_levels(ms: dict[str, Any], direction: str | None) -> list[float]:
    spot = _first_number(ms, "spot")
    if spot is None:
        return []
    if direction == "long":
        keys = ("vwap", "call_gamma_wall", "kl_call_gamma_wall", "call_oi_wall")
        return [value for key in keys if (value := _first_number(ms, key)) is not None and value > spot]
    if direction == "short":
        keys = ("vwap", "put_gamma_wall", "kl_put_gamma_wall", "put_oi_wall")
        return [value for key in keys if (value := _first_number(ms, key)) is not None and value < spot]
    return []


def _decision_timestamp(ms: dict[str, Any]) -> Any:
    return (
        ms.get("decision_time_ms")
        or ms.get("decision_timestamp_utc")
        or ms.get("_server_build_ts")
        or ms.get("refresh_ts_utc")
    )


def _first_number(ms: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(ms.get(key))
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
