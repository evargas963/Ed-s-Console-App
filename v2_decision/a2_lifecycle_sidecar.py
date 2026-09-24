"""A2 lifecycle advisory sidecar.

At entry time there is no active position to manage, so the root sidecar state
remains posture alpha. ``projected_preview`` is a pre-entry projection only and
never claims active lifecycle decision authority.
"""

from __future__ import annotations

from typing import Any

from lifecycle_rule_core import LIFECYCLE_RULE_CORE_VERSION
from v2_decision.a2_eod_force_exit import evaluate_a2_eod_force_exit
from v2_decision.a2_lifecycle_health import (
    build_a2_pin_risk_event_source,
    derive_a2_pin_risk_health,
    resolve_a2_option_right,
    select_a2_pin_risk_audit_row,
)
from v2_decision.a2_session_calendar import get_session_info, load_a2_session_calendar


LIFECYCLE_GAP_NAMES = (
    "a2_lifecycle_policy_pending",
    "a2_lifecycle_legacy_exit_logic_divergence_audit_pending",
    "a2_lifecycle_iv_crush_handler_not_implemented",
    "a2_lifecycle_gamma_spike_handler_not_implemented",
    "a2_lifecycle_assignment_risk_handler_not_implemented",
    "a2_lifecycle_spread_widening_exit_not_implemented",
    "a2_lifecycle_partial_fill_handler_not_implemented",
    "a2_lifecycle_dynamic_policy_not_implemented",
    "a2_lifecycle_promotion_to_runtime_authority_not_authorized",
)

THRESHOLD_POLICY_OBJECTS = ()

PREVIEW_BLOCKING_GAPS = ()

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
    lifecycle_action, cadence_observation_mode = evaluate_a2_eod_force_exit(ms)
    event_sources = _build_event_sources(ms)
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
        "lifecycle_action": lifecycle_action,
        "cadence_observation_mode": cadence_observation_mode,
        "lifecycle_conflict_state": "lifecycle_warning_only",
        "event_sources": event_sources,
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


def _build_event_sources(ms: dict[str, Any]) -> list[dict[str, Any]]:
    event_sources: list[dict[str, Any]] = []
    pin_risk_event = _build_pin_risk_event_source(ms)
    if pin_risk_event is not None:
        event_sources.append(pin_risk_event)
    return event_sources


def _build_pin_risk_event_source(ms: dict[str, Any]) -> dict[str, Any] | None:
    try:
        proof = ms.get("option_chain_selection_proof")
        if not isinstance(proof, dict):
            proof = {}
        winner = proof.get("winner")
        if not isinstance(winner, dict):
            winner = {}
        option_right = resolve_a2_option_right(ms, winner)
        strike = _selected_strike(ms, winner)
        selected_audit = select_a2_pin_risk_audit_row(
            proof=proof,
            winner=winner,
            strike=strike,
            option_right=option_right,
        )
        pin_risk = derive_a2_pin_risk_health(selected_audit=selected_audit, strike=strike)
        return build_a2_pin_risk_event_source(
            pin_risk_health=pin_risk,
            session_type=_session_type(ms),
        )
    except Exception:
        return None


def _session_type(ms: dict[str, Any]) -> str:
    try:
        calendar = load_a2_session_calendar()
        if calendar is None:
            return "calendar_unavailable"
        decision_time_ms = ms.get("decision_time_ms")
        if decision_time_ms is None:
            return "calendar_unavailable"
        session_info = get_session_info(decision_time_ms=int(decision_time_ms), calendar=calendar)
        if session_info is None:
            return "calendar_unavailable"
        return session_info.session_type
    except Exception:
        return "calendar_unavailable"


def _build_projected_preview(ms: dict[str, Any]) -> dict[str, Any]:
    """Pre-entry projection of THE CALL's plan (entry / stop / T1 / T2), carried verbatim.

    ONE FAUCET (audit 2026-09-24): this used to RE-DERIVE the plan -- a VIX/clock percentage
    stop (the fallback removed from The Call), a risk recomputed from it, T1/T2 snapped to
    VWAP / gamma walls (The Call never snaps), and the 60c / 2R / T1+1R target fallbacks. The
    contract's own fixture showed the two producers disagreeing (Call stop 498.5 vs preview
    498.98; Call T1 503.0 vs preview 503.5). The preview now carries The Call's values; a
    missing one is missing, never re-derived.
    """
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
        key for key in ("entry", "direction", "stop", "target") if inputs[key]["value"] is None
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

    # `available` is unreachable in v1 while EOD force-exit logic remains a
    # named gap; the plan geometry is The Call's, but the preview is still
    # policy_pending until the EOD/time-stop blockers close.
    return _preview(
        status="policy_pending",
        projected_fields=_projected_fields(
            stop=inputs["stop"]["value"],
            target=inputs["target"]["value"],
            target2=inputs["target2"]["value"],   # None when The Call has no T2
            max_hold_bars=None,
            eod_force_exit_time=None,
            source="v1_approximation",   # schema's label for values carried from the live v1 Call
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
    """The Call's plan fields as carried on the state dict (MarketState.entry / stop /
    target / target2 are set from TheCall) -- no aliases, no re-derivation."""
    inputs: dict[str, dict[str, Any]] = {
        "direction": _call_leaf(_direction(ms), "TheCall.signal (call_signal)"),
    }
    for key in ("entry", "stop", "target", "target2"):
        inputs[key] = _call_leaf(_first_number(ms, key), f"TheCall.{key}")
    return inputs


def _call_leaf(value: Any, detail: str) -> dict[str, Any]:
    if value is None:
        return _missing_leaf()
    return {"value": value, "source": "v1_approximation", "source_classification": "the_call_plan",
            "detail": detail}


def _missing_leaf() -> dict[str, Any]:
    return {
        "value": None,
        "source": "not_implemented",
        "source_classification": "missing_from_ms_dict",
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
    """The Call's signal only (call_signal) -- final_signal / direction aliases no longer
    stand in for it."""
    s = str(ms.get("call_signal") or "").strip().lower()
    return s if s in ("long", "short") else None


def _selected_strike(ms: dict[str, Any], winner: dict[str, Any]) -> float | None:
    return _first_number(ms, "rec_strike", "strike", "call_strike", "selected_strike") or _float_or_none(winner.get("strike"))


#: RC-337 — the unit of each accepted source, proven from its PRODUCER, not from magnitude.
#: A magnitude heuristic ("> 1e11 means ms") is forbidden: it guesses, and it silently
#: reclassifies the value the day the epoch or the field changes.
_DECISION_TS_SOURCE_UNITS: tuple[tuple[str, str], ...] = (
    ("decision_time_ms", "ms"),          # server.py:7763  int(_refresh_ts_utc * 1000)
    ("decision_timestamp_utc", "s"),     # live_decision_bundle.py:122  float(time.time())
    ("_server_build_ts", "s"),           # server.py:7764 / :9480  time.time()
    ("refresh_ts_utc", "s"),             # server.py:7627  _utc_ts_refresh()
)


def _decision_timestamp(ms: dict[str, Any]) -> Any:
    """The decision instant as INTEGER EPOCH MILLISECONDS, or None.

    RC-337. This was a bare `or` chain returning whichever source was first non-falsy, in
    that source's own unit — so `would_apply_if_entered_at_time` (:251, a pass-through)
    emitted epoch-ms when `decision_time_ms` was present and epoch-SECONDS when it was not.
    MEASURED on one live SPY state: 1786383424954 against 1786383424.2295866 for the same
    instant. The canonical unit is epoch-ms, proven three ways — the assertion at
    tests/test_v2_a2_lifecycle_sidecar.py:242 (`_epoch_ms_et`), PILOT_1B_A2_LIFECYCLE_
    CONTRACT.md:277, and ~70 historical payloads in reports/ui_transport/, every one
    13-digit.

    This function is the normalization authority because it is the only place that both
    SELECTS the source and therefore KNOWS which unit arrived; line 251 receives a number
    with no provenance and could only guess. Fixing there would mask the mixed-unit
    producer rather than remove it, and would not cover a future fifth source.

    Source precedence is unchanged, including its falsy-skip semantics, so this is a pure
    unit fix. (A source valued exactly 0 still falls through to the next; epoch 0 is not a
    real decision instant, and changing that is a separate question this row does not open.)
    """
    for field, unit in _DECISION_TS_SOURCE_UNITS:
        raw = ms.get(field)
        if not raw:                       # preserve the original `or` precedence exactly
            continue                      # (None / 0 / 0.0 / False / "" skip to next source)
        # A clock is an int or float from the producers proven above — never a bool
        # (True is `1`, not an instant) and never a string (no producer emits one).
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        # NaN, +/-inf and negatives are not instants. Zero already skipped as falsy.
        if raw != raw or raw in (float("inf"), float("-inf")) or raw <= 0:
            continue
        if unit == "ms":
            # Canonical positive integer epoch-ms passes through UNTOUCHED — no float
            # round-trip, so values above 2**53 cannot lose precision.
            if isinstance(raw, int):
                return raw
            try:
                return int(raw)           # float ms: truncate, same convention as below
            except (OverflowError, ValueError):
                continue
        # TRUNCATE, not round. The repository's established seconds->epoch-ms convention,
        # proven from 12 `int(seconds * 1000)` sites against 1 `round(...)` — and that one
        # is a display latency metric, not an epoch conversion. The three that bind this
        # field directly: server.py:7763 `int(_refresh_ts_utc * 1000)` produces
        # decision_time_ms itself; calibration/v2_advisory_backfill.py:129 does the same
        # for the same field; the contract test's `_epoch_ms_et` (tests/test_v2_a2_
        # lifecycle_sidecar.py:12) is `int(... * 1000)`. Rounding would let a seconds-
        # sourced value disagree with the ms-sourced one by up to 1ms for one instant.
        # Overflow/unrepresentability is decided by Python's own arithmetic (float
        # overflow -> inf -> int() raises OverflowError), not by an invented bound.
        try:
            return int(raw * 1000)
        except (OverflowError, ValueError):
            continue
    return None


def _first_number(ms: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(ms.get(key))
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)
