"""Build A1 execution-adjusted EV artifacts from EV bounds.

Scope is intentionally training/evaluation-time only. This scaffold validates
Schwab-normalized quote inputs and an explicitly supplied execution-cost model,
then adjusts EV bounds by a declared R-multiple cost. It does not estimate fill,
slippage, impact, adverse selection, or capacity terms from thin data.

Runtime promotion is [REAL-GATE:accepted-design] deferred: ``execution_adjusted_EV`` remains
unchanged at runtime until promotion gates are designed.
``not_implemented`` in v2 decision adapters until calibrated probability,
conformal bounds, EV bounds, and execution-cost models all validate on real
data.
"""

from __future__ import annotations

import math
from typing import Any


A1_EXECUTION_EV_ARTIFACT_SCHEMA_VERSION = "1"
A1_EXECUTION_EV_METHOD = "a1_execution_adjusted_ev_scaffold"
A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES = (
    "fill_probability_estimate",
    "slippage_estimate",
    "market_impact_estimate",
    "adverse_selection_score",
    "capacity_participation_cap",
)
A1_EXECUTION_EV_REQUIRED_NORMALIZED_FIELDS = (
    "bid",
    "ask",
    "mark",
    "bidSize",
    "askSize",
    "quoteTimeInLong",
    "symbol",
)
A1_EXECUTION_EV_NORMALIZED_SOURCE_PATHS = {
    "bid": ("chains.callExpDateMap.*.bid", "chains.putExpDateMap.*.bid"),
    "ask": ("chains.callExpDateMap.*.ask", "chains.putExpDateMap.*.ask"),
    "mark": ("chains.callExpDateMap.*.mark", "chains.putExpDateMap.*.mark"),
    "bidSize": ("chains.callExpDateMap.*.bidSize", "chains.putExpDateMap.*.bidSize"),
    "askSize": ("chains.callExpDateMap.*.askSize", "chains.putExpDateMap.*.askSize"),
    "bidAskSize": ("chains.callExpDateMap.*.bidAskSize", "chains.putExpDateMap.*.bidAskSize"),
    "quoteTimeInLong": ("chains.callExpDateMap.*.quoteTimeInLong", "chains.putExpDateMap.*.quoteTimeInLong"),
    "symbol": ("chains.callExpDateMap.*.symbol", "chains.putExpDateMap.*.symbol"),
}
A1_EXECUTION_EV_DEFAULT_MIN_FILL_HISTORY_N = 500  # O-24-style floor for first scaffold gate.
A1_EXECUTION_EV_DEFAULT_QUOTE_STALENESS_MS = 2_000  # O-20 quote staleness threshold.


def build_a1_execution_ev_artifact(
    ev_bounds_artifact: dict[str, Any],
    *,
    execution_cost_model: dict[str, Any] | None = None,
    normalized_contract: dict[str, Any] | None = None,
    decision_time_ms: float | None = None,
    quote_staleness_threshold_ms: int = A1_EXECUTION_EV_DEFAULT_QUOTE_STALENESS_MS,
) -> dict[str, Any]:
    """Build an execution-adjusted EV artifact without fabricating missing costs."""
    ev_status_raw = ev_bounds_artifact.get("status")
    ev_reason = ev_bounds_artifact.get("reason")
    ev_bounds_run_id = ev_bounds_artifact.get("ev_bounds_run_id")
    base = {
        "schema_version": A1_EXECUTION_EV_ARTIFACT_SCHEMA_VERSION,
        "calibration_run_id": ev_bounds_artifact.get("calibration_run_id"),
        "calibration_window_id": ev_bounds_artifact.get("calibration_window_id"),
        "conformal_run_id": ev_bounds_artifact.get("conformal_run_id"),
        "ev_bounds_run_id": ev_bounds_run_id,
        "execution_ev_run_id": (
            f"{ev_bounds_run_id}-execution-ev" if ev_bounds_run_id else None
        ),
        "module_id": ev_bounds_artifact.get("module_id"),
        "expression_profile_id": ev_bounds_artifact.get("expression_profile_id"),
        "horizon": ev_bounds_artifact.get("horizon"),
        "method": A1_EXECUTION_EV_METHOD,
        "input_ev_bounds_status": ev_status_raw,
        "runtime_adapter_unchanged": True,
        "approximate_guarantee_disclosure": approximate_guarantee_disclosure(ev_bounds_artifact),
    }
    if ev_status_raw is None or not str(ev_status_raw).strip():
        return _skip_artifact(
            base,
            status="execution_ev_skipped_missing_upstream_status",
            reason="ev_bounds_artifact_status_field_missing",
        )
    if not ev_bounds_run_id:
        return _skip_artifact(
            base,
            status="execution_ev_skipped_missing_ev_bounds_run_id",
            reason="ev_bounds_run_id_missing",
        )
    ev_status = str(ev_status_raw).strip()
    base["input_ev_bounds_status"] = ev_status
    if ev_status.startswith("ev_bounds_skipped_"):
        return _skip_artifact(
            base,
            status="execution_ev_skipped_upstream_ev_bounds_unavailable",
            reason=f"{ev_status}:{ev_reason or 'no_reason'}",
        )
    if ev_status.startswith("ev_bounds_degraded_"):
        return _skip_artifact(
            base,
            status="execution_ev_skipped_upstream_ev_bounds_degraded",
            reason=f"{ev_status}:{ev_reason or 'no_reason'}",
        )
    if execution_cost_model is None:
        return _skip_artifact(
            base,
            status="execution_ev_skipped_missing_execution_cost_model",
            reason="fill_slippage_impact_model_unavailable",
        )

    quote_check = validate_normalized_execution_inputs(
        normalized_contract,
        decision_time_ms=decision_time_ms,
        quote_staleness_threshold_ms=quote_staleness_threshold_ms,
    )
    if not quote_check["ok"]:
        return _skip_artifact(
            {**base, "normalized_quote_input_check": quote_check},
            status=str(quote_check["status"]),
            reason=str(quote_check["reason"]),
        )

    model_check = validate_execution_cost_model(execution_cost_model)
    if not model_check["ok"]:
        return _skip_artifact(
            {**base, "normalized_quote_input_check": quote_check, "execution_cost_model_check": model_check},
            status=str(model_check["status"]),
            reason=str(model_check["reason"]),
        )

    ev_rows = _usable_ev_bounds(ev_bounds_artifact.get("ev_bounds") or [])
    if not ev_rows:
        return _skip_artifact(
            {**base, "normalized_quote_input_check": quote_check, "execution_cost_model_check": model_check},
            status="execution_ev_skipped_missing_ev_bounds_rows",
            reason="no_usable_ev_bounds_rows",
        )

    expected_cost_r = float(execution_cost_model["expected_cost_r"])
    adjusted_rows = [_adjusted_row(row, expected_cost_r) for row in ev_rows]
    status = "execution_ev_warning_upstream_ev_bounds" if ev_status.startswith("ev_bounds_warning_") else "ok"
    reason = f"{ev_status}:{ev_reason or 'no_reason'}" if status.startswith("execution_ev_warning_") else None
    return {
        **base,
        "status": status,
        "reason": reason,
        "normalized_quote_input_check": quote_check,
        "execution_cost_model_check": model_check,
        "execution_ev_model": {
            "type": A1_EXECUTION_EV_METHOD,
            "model_id": execution_cost_model.get("model_id"),
            "source": execution_cost_model.get("source"),
            "registry_entries": list(execution_cost_model.get("registry_entries") or []),
            "expected_cost_r": round(expected_cost_r, 6),
            "validated": True,
        },
        "execution_adjusted_ev": adjusted_rows,
        "summary": {
            "n": len(adjusted_rows),
            "mean_execution_adjusted_EV_lower": _mean(row["execution_adjusted_EV_lower"] for row in adjusted_rows),
            "mean_execution_adjusted_EV_upper": _mean(row["execution_adjusted_EV_upper"] for row in adjusted_rows),
        },
    }


def validate_normalized_execution_inputs(
    normalized_contract: dict[str, Any] | None,
    *,
    decision_time_ms: float | None = None,
    quote_staleness_threshold_ms: int = A1_EXECUTION_EV_DEFAULT_QUOTE_STALENESS_MS,
) -> dict[str, Any]:
    """Validate Schwab chain-row quote inputs (raw chain row, no normalizer)."""
    missing = [
        field
        for field in A1_EXECUTION_EV_REQUIRED_NORMALIZED_FIELDS
        if normalized_contract is None or _value_missing(normalized_contract.get(field))
    ]
    base = {
        "source_boundary": "schwab_chain_row",
        "required_normalized_fields": list(A1_EXECUTION_EV_REQUIRED_NORMALIZED_FIELDS),
        "source_paths": A1_EXECUTION_EV_NORMALIZED_SOURCE_PATHS,
        "missing_fields": missing,
    }
    if missing:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_normalized_schwab_quote_inputs",
            "reason": "missing_required_normalized_quote_fields",
        }
    qt_raw = normalized_contract["quoteTimeInLong"]  # type: ignore[index]
    if isinstance(qt_raw, bool):
        qt_raw = None
    try:
        qt_f = float(qt_raw) if qt_raw is not None else None
    except (TypeError, ValueError):
        qt_f = None
    if qt_f is None or not math.isfinite(qt_f):
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_normalized_schwab_quote_inputs",
            "reason": "quoteTimeInLong_unparseable",
        }
    quote_time = qt_f
    if decision_time_ms is not None:
        staleness_ms = max(0.0, float(decision_time_ms) - quote_time)
        if staleness_ms > float(quote_staleness_threshold_ms):
            return {
                **base,
                "ok": False,
                "status": "execution_ev_skipped_stale_quote_inputs",
                "reason": "quote_staleness_exceeds_o20",
                "quote_staleness_ms": round(staleness_ms, 3),
                "threshold_ms": int(quote_staleness_threshold_ms),
            }
    return {
        **base,
        "ok": True,
        "status": "ok",
        "reason": None,
        "quote_staleness_ms": None if decision_time_ms is None else round(max(0.0, float(decision_time_ms) - quote_time), 3),
        "threshold_ms": int(quote_staleness_threshold_ms),
    }


def validate_execution_cost_model(model: dict[str, Any]) -> dict[str, Any]:
    """Validate that a supplied execution cost model is explicit and sufficiently warm."""
    entries = set(str(x) for x in (model.get("registry_entries") or []))
    missing_entries = [x for x in A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES if x not in entries]
    if "min_fill_history_n" in model:
        try:
            min_fill_history_n = int(model["min_fill_history_n"])
        except (TypeError, ValueError):
            min_fill_history_n = -1
    else:
        min_fill_history_n = A1_EXECUTION_EV_DEFAULT_MIN_FILL_HISTORY_N
    fill_history_n = int(model.get("fill_history_n") or 0)
    base = {
        "model_id": model.get("model_id"),
        "source": model.get("source"),
        "required_registry_entries": list(A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES),
        "missing_registry_entries": missing_entries,
        "min_fill_history_n": min_fill_history_n,
        "fill_history_n": fill_history_n,
    }
    if "min_fill_history_n" in model and min_fill_history_n <= 0:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_execution_cost_model",
            "reason": "min_fill_history_n_explicit_zero_or_negative",
        }
    if model.get("source") != "derived_because_schwab_does_not_provide":
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_execution_cost_model",
            "reason": "execution_cost_model_source_not_registered_derived",
        }
    if missing_entries:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_execution_cost_model",
            "reason": "execution_cost_model_missing_registry_entries",
        }
    if model.get("validated") is not True:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_execution_cost_model",
            "reason": "execution_cost_model_not_validated",
        }
    if fill_history_n < min_fill_history_n:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_fill_history",
            "reason": "fill_history_below_o24_style_floor",
        }
    if model.get("capacity_model_available") is not True:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_capacity_model",
            "reason": "capacity_model_unavailable",
        }
    expected_cost_r = _float_or_none(model.get("expected_cost_r"))
    if expected_cost_r is None or expected_cost_r < 0.0:
        return {
            **base,
            "ok": False,
            "status": "execution_ev_skipped_missing_execution_cost_model",
            "reason": "expected_cost_r_missing_or_negative",
        }
    return {
        **base,
        "ok": True,
        "status": "ok",
        "reason": None,
        "expected_cost_r": round(expected_cost_r, 6),
    }


def approximate_guarantee_disclosure(ev_bounds_artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "inherits": ev_bounds_artifact.get("approximate_guarantee_disclosure"),
        "method": A1_EXECUTION_EV_METHOD,
        "assumptions": [
            "execution cost model is estimated from representative fill/slippage observations",
            "top-of-book quote inputs represent actionable liquidity at decision time",
            "capacity model approximates participation limits for the selected contract",
        ],
        "likely_violation_modes": [
            "quote_staleness",
            "spread_regime_shift",
            "fill_rate_warmup_insufficient",
            "slippage_distribution_shift",
            "market_impact_nonlinearity",
            "opening_or_event_gap_liquidity",
        ],
        "qualification": "approximate_not_exact",
    }


def _skip_artifact(base: dict[str, Any], *, status: str, reason: str) -> dict[str, Any]:
    return {
        **base,
        "status": status,
        "reason": reason,
        "execution_ev_model": None,
        "execution_adjusted_ev": [],
        "summary": None,
    }


def _usable_ev_bounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ev_lower = _float_or_none(row.get("EV_lower"))
        ev_upper = _float_or_none(row.get("EV_upper"))
        if ev_lower is None or ev_upper is None:
            continue
        out.append({**row, "EV_lower": ev_lower, "EV_upper": ev_upper})
    return out


def _adjusted_row(row: dict[str, Any], expected_cost_r: float) -> dict[str, Any]:
    return {
        **row,
        "expected_cost_r": round(float(expected_cost_r), 6),
        "execution_adjusted_EV_lower": round(float(row["EV_lower"]) - float(expected_cost_r), 6),
        "execution_adjusted_EV_upper": round(float(row["EV_upper"]) - float(expected_cost_r), 6),
    }


def _mean(values: list[float] | Any) -> float:
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("cannot compute mean of empty values")
    return round(sum(vals) / len(vals), 6)


def _value_missing(value: Any) -> bool:
    return value is None or value == ""


def _float_or_none(value: Any) -> float | None:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)
