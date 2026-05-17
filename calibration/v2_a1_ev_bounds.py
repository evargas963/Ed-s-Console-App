"""Build A1 EV-bound artifacts from conformal probability bands.

Scope is intentionally training/evaluation-time only: this scaffold converts
existing conformal ``p_low`` / ``p_high`` rows into R-multiple EV bounds and
leaves runtime v2 adapter fields unchanged.

The scaffold uses artifact-level ``reward_r`` and ``risk_r`` assumptions across
all rows. Runtime promotion requires per-row trade geometry sourced from
candidate metadata; that per-row variant is deferred until promotion gates are
designed.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

log = logging.getLogger(__name__)

from calibration.v2_a1_calibration import (
    A1_CALIBRATION_PER_REGIME_MIN_SAMPLES,
    axis_reliability_bucket_value,
)
from calibration.v2_a1_conformal import A1_CONFORMAL_REGIME_AXES

A1_EV_BOUNDS_ARTIFACT_SCHEMA_VERSION = "1"
A1_EV_BOUNDS_METHOD = "a1_ev_bounds_from_conformal_probability_band"


def build_a1_ev_bounds_artifact(
    conformal_artifact: dict[str, Any],
    *,
    reward_r: float,
    risk_r: float = 1.0,
) -> dict[str, Any]:
    """Build a JSON-serializable EV-bounds artifact from A1 conformal output."""
    geometry = _validate_geometry(reward_r=reward_r, risk_r=risk_r)
    conformal_status_raw = conformal_artifact.get("status")
    conformal_reason = conformal_artifact.get("reason")
    conformal_run_id = conformal_artifact.get("conformal_run_id")
    ev_bounds_run_id = f"{conformal_run_id}-ev-bounds" if conformal_run_id else None
    base = {
        "schema_version": A1_EV_BOUNDS_ARTIFACT_SCHEMA_VERSION,
        "calibration_run_id": conformal_artifact.get("calibration_run_id"),
        "calibration_window_id": conformal_artifact.get("calibration_window_id"),
        "conformal_run_id": conformal_run_id,
        "ev_bounds_run_id": ev_bounds_run_id,
        "module_id": conformal_artifact.get("module_id"),
        "expression_profile_id": conformal_artifact.get("expression_profile_id"),
        "horizon": conformal_artifact.get("horizon"),
        "method": A1_EV_BOUNDS_METHOD,
        "input_conformal_status": conformal_status_raw,
        "runtime_adapter_unchanged": True,
        "trade_geometry": geometry,
        "geometry_scope": {
            "type": "artifact_level",
            "per_row_geometry_required_for_runtime_promotion": True,
            "note": (
                "This scaffold applies one reward_r/risk_r pair across all rows; runtime promotion "
                "requires per-row candidate trade geometry."
            ),
        },
        "approximate_guarantee_disclosure": approximate_guarantee_disclosure(conformal_artifact),
    }
    if conformal_status_raw is None or not str(conformal_status_raw).strip():
        return _skip_artifact(
            base,
            status="ev_bounds_skipped_missing_upstream_conformal_status",
            reason="conformal_artifact_status_field_missing",
        )
    conformal_status = str(conformal_status_raw).strip()
    base["input_conformal_status"] = conformal_status
    if conformal_status.startswith("conformal_skipped_"):
        return _skip_artifact(
            base,
            status="ev_bounds_skipped_upstream_conformal_unavailable",
            reason=f"{conformal_status}:{conformal_reason or 'no_reason'}",
        )
    if conformal_status == "conformal_degraded_empirical_coverage":
        return _skip_artifact(
            base,
            status="ev_bounds_skipped_upstream_conformal_degraded",
            reason=f"{conformal_status}:{conformal_reason or 'no_reason'}",
        )

    interval_rows = _usable_interval_rows(conformal_artifact.get("holdout_intervals") or [])
    if not interval_rows:
        return _skip_artifact(
            base,
            status="ev_bounds_skipped_missing_conformal_intervals",
            reason="no_usable_conformal_interval_rows",
        )

    ev_rows = [_ev_row(row, geometry) for row in interval_rows]
    status = (
        "ev_bounds_warning_upstream_conformal_below_nominal"
        if conformal_status == "conformal_warning_below_nominal"
        else "ok"
    )
    reason = (
        f"{conformal_status}:{conformal_reason or 'no_reason'}"
        if status.startswith("ev_bounds_warning_")
        else None
    )
    return {
        **base,
        "status": status,
        "reason": reason,
        "ev_model": {
            "type": A1_EV_BOUNDS_METHOD,
            "reward_r": geometry["reward_r"],
            "risk_r": geometry["risk_r"],
            "formula": "EV = p_win * reward_r - (1 - p_win) * risk_r",
            "execution_adjusted_ev": "not_implemented",
        },
        "ev_bounds": ev_rows,
        "summary": _summary(ev_rows),
        "regime_ev_bounds": _regime_ev_bounds(ev_rows),
    }


def compute_ev_bound(p_win: float, *, reward_r: float, risk_r: float = 1.0) -> float:
    """Compute EV in R units for one win probability and simple reward/risk geometry."""
    p = _bounded_probability(p_win)
    geom = _validate_geometry(reward_r=reward_r, risk_r=risk_r)
    return round(p * geom["reward_r"] - (1.0 - p) * geom["risk_r"], 6)


def approximate_guarantee_disclosure(conformal_artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "inherits": conformal_artifact.get("approximate_guarantee_disclosure"),
        "method": A1_EV_BOUNDS_METHOD,
        "assumptions": [
            "conformal probability band is approximately valid",
            "reward_r and risk_r represent the candidate trade geometry at decision time",
            "reward_r/risk_r geometry is stable enough for the evaluated horizon",
        ],
        "likely_violation_modes": [
            "regime_shift",
            "volatility_clustering",
            "stop_target_geometry_drift",
            "gap_through_stop_or_target",
            "execution_costs_not_modeled",
        ],
        "qualification": "approximate_not_exact",
        "execution_adjusted_ev": "not_implemented",
    }


def _skip_artifact(base: dict[str, Any], *, status: str, reason: str) -> dict[str, Any]:
    return {
        **base,
        "status": status,
        "reason": reason,
        "ev_model": None,
        "ev_bounds": [],
        "summary": None,
        "regime_ev_bounds": {},
    }


def _ev_row(row: dict[str, Any], geometry: dict[str, float]) -> dict[str, Any]:
    ev_lower = compute_ev_bound(row["p_low"], reward_r=geometry["reward_r"], risk_r=geometry["risk_r"])
    ev_upper = compute_ev_bound(row["p_high"], reward_r=geometry["reward_r"], risk_r=geometry["risk_r"])
    return {
        "calibration_row_id": row.get("calibration_row_id"),
        "ticker": row.get("ticker"),
        "decision_ts_utc": row.get("decision_ts_utc"),
        "p_low": row["p_low"],
        "p_high": row["p_high"],
        "EV_lower": ev_lower,
        "EV_upper": ev_upper,
        "reward_r": geometry["reward_r"],
        "risk_r": geometry["risk_r"],
        **{axis: row.get(axis) for axis in A1_CONFORMAL_REGIME_AXES},
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "mean_EV_lower": _mean(row["EV_lower"] for row in rows),
        "mean_EV_upper": _mean(row["EV_upper"] for row in rows),
        "min_EV_lower": round(min(float(row["EV_lower"]) for row in rows), 6),
        "max_EV_upper": round(max(float(row["EV_upper"]) for row in rows), 6),
    }


def _regime_ev_bounds(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for axis in A1_CONFORMAL_REGIME_AXES:
        values = sorted({axis_reliability_bucket_value(row.get(axis)) for row in rows})
        for value in values:
            bucket = [
                row for row in rows if axis_reliability_bucket_value(row.get(axis)) == value
            ]
            gate = _sample_gate(len(bucket), A1_CALIBRATION_PER_REGIME_MIN_SAMPLES, "O-25")
            key = f"{axis}:{value}"
            entry = {
                "axis": axis,
                "value": value,
                "n": len(bucket),
                "sample_gate": gate,
                "mean_EV_lower": None,
                "mean_EV_upper": None,
                "status": "insufficient_sample" if not gate["sufficient_sample"] else "ok",
            }
            if gate["sufficient_sample"] and bucket:
                entry["mean_EV_lower"] = _mean(row["EV_lower"] for row in bucket)
                entry["mean_EV_upper"] = _mean(row["EV_upper"] for row in bucket)
            out[key] = entry
    return out


def _usable_interval_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        p_low = _float_or_none(row.get("p_low"))
        p_high = _float_or_none(row.get("p_high"))
        if p_low is None or p_high is None:
            continue
        p_low = _bounded_probability(p_low)
        p_high = _bounded_probability(p_high)
        if p_low > p_high:
            continue
        out.append({**row, "p_low": p_low, "p_high": p_high})
    return out


def _validate_geometry(*, reward_r: float, risk_r: float) -> dict[str, float]:
    reward = float(reward_r)
    risk = float(risk_r)
    if reward < 0.0:
        raise ValueError("reward_r must be non-negative")
    if risk <= 0.0:
        raise ValueError("risk_r must be positive")
    return {"reward_r": reward, "risk_r": risk}


def _bounded_probability(value: float) -> float:
    raw = float(value)
    if raw < 0.0 or raw > 1.0:
        log.warning(
            "v2_a1_ev_bounds: probability %s outside [0, 1]; clamping before EV computation",
            raw,
        )
    return min(1.0, max(0.0, raw))


def _sample_gate(n: int, min_required: int, operator_decision: str) -> dict[str, Any]:
    return {
        "n": int(n),
        "min_required": int(min_required),
        "sufficient_sample": int(n) >= int(min_required),
        "status": "ok" if int(n) >= int(min_required) else "insufficient_sample",
        "operator_decision": operator_decision,
    }


def _mean(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("cannot compute mean of empty values")
    return round(sum(vals) / len(vals), 6)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None
