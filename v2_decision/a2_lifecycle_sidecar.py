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
    vix_level = _first_number(ms, "vix_level", "vix")
    entry = _first_number(ms, "entry", "rec_entry")
    mins_elapsed = _mins_elapsed_since_open(ms)
    # MarketState producer key is `vol_regime_risk_mult`
    # (see market_state.py: ms.vol_regime_risk_mult). The legacy
    # `risk_multiplier` alias is kept only as a defensive fallback; it is not
    # written by any current producer.
    risk_multiplier = _first_number(ms, "vol_regime_risk_mult", "risk_multiplier")
    risk = _risk(ms=ms, entry=entry, direction=direction, spot=spot, mins_elapsed=mins_elapsed)
    structural_levels = _structural_levels(ms, direction)

    inputs: dict[str, dict[str, Any]] = {}

    # Schwab-direct equity quote (spot) — upstream leaf is the equity
    # quote ladder beginning at quotes.quote.lastPrice (see
    # server.py::_extract_quote / market_context.py::_extract_quote).
    inputs["spot"] = _schwab_leaf(
        spot, detail="quotes.quote.lastPrice"
    ) if spot is not None else _missing_leaf()

    # Schwab-direct $VIX quote (see market_context.py: ctx.vix sourced from
    # _extract_quote("$VIX", ...) — the same equity-quote ladder).
    inputs["vix_level"] = _schwab_leaf(
        vix_level, detail="quotes.$VIX.quote.lastPrice"
    ) if vix_level is not None else _missing_leaf()

    inputs["mins_elapsed_since_open"] = _input_leaf(
        mins_elapsed,
        "missing_from_ms_dict" if mins_elapsed is None else "schwab_native_normalized",
    )
    inputs["risk_multiplier"] = _input_leaf(
        risk_multiplier,
        "missing_from_ms_dict" if risk_multiplier is None else "schwab_native_normalized",
    )
    inputs["entry"] = _input_leaf(
        entry,
        "missing_from_ms_dict" if entry is None else "schwab_native_normalized",
    )
    inputs["direction"] = _input_leaf(
        direction,
        "missing_from_ms_dict" if direction is None else "schwab_native_normalized",
    )
    inputs["risk"] = _input_leaf(
        risk,
        "missing_from_ms_dict" if risk is None else "schwab_native_normalized",
    )
    for key, source_keys in (
        ("avg5", ("avg_5c_pts", "avg5")),
        ("avg15", ("avg_15c_pts", "avg15")),
        ("avg60", ("avg_60c_pts", "avg60")),
    ):
        value = _first_number(ms, *source_keys)
        inputs[key] = _input_leaf(
            value,
            "missing_from_ms_dict" if value is None else "schwab_native_normalized",
        )
    inputs["structural_levels"] = _input_leaf(
        structural_levels,
        "missing_from_ms_dict" if structural_levels is None else "schwab_native_normalized",
    )
    return inputs


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


def _schwab_leaf(value: Any, *, detail: str) -> dict[str, Any]:
    """Provenance leaf for inputs read directly from a Schwab wire field."""
    return {
        "value": value,
        "source": "v2_compliant",
        "source_classification": "schwab_native_normalized",
        "detail": detail,
    }


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
        risk_multiplier=_first_number(ms, "vol_regime_risk_mult", "risk_multiplier"),
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
