"""Build A1 conformal probability-band artifacts for v2 Pilot 1B.

Scope is intentionally training/evaluation-time only: the scaffold wraps an
existing A1 isotonic calibration artifact, reports approximate-guarantee
diagnostics, and leaves runtime v2 adapter fields unchanged.

When no separate evaluation rows are supplied, empirical coverage is measured
on the same holdout rows used to fit the conformal quantile. That diagnostic is
useful for scaffolding but can be optimistic; honest out-of-sample evaluation
requires a separate post-fit set before any runtime promotion.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from calibration.v2_a1_calibration import (
    A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
    A1_CALIBRATION_PER_REGIME_MIN_SAMPLES,
)

A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION = "1"
A1_CONFORMAL_METHOD = "split_conformal_probability_band"
A1_CONFORMAL_NOMINAL_COVERAGE = 0.90  # O-23
A1_CONFORMAL_DEGRADED_COVERAGE = 0.85  # O-23
A1_CONFORMAL_REGIME_AXES = (
    "volatility_regime",
    "time_of_day_bucket",
    "expiry_dte_bucket",
    "ticker",
    "direction",
    "primary_horizon",
)


def build_a1_conformal_artifact(
    calibration_artifact: dict[str, Any],
    *,
    evaluation_predictions: list[dict[str, Any]] | None = None,
    min_holdout_samples: int = A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
    nominal_coverage: float = A1_CONFORMAL_NOMINAL_COVERAGE,
    degraded_coverage_threshold: float = A1_CONFORMAL_DEGRADED_COVERAGE,
) -> dict[str, Any]:
    """Build a JSON-serializable conformal artifact from A1 calibration output."""
    fit_rows = _usable_predictions(calibration_artifact.get("holdout_predictions") or [])
    eval_rows = _usable_predictions(evaluation_predictions if evaluation_predictions is not None else fit_rows)
    aggregate_gate = _sample_gate(len(fit_rows), min_holdout_samples, "O-24")
    horizon = str(calibration_artifact.get("horizon") or "unknown")
    base = {
        "schema_version": A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION,
        "calibration_run_id": calibration_artifact.get("calibration_run_id"),
        "calibration_window_id": calibration_artifact.get("calibration_window_id"),
        "conformal_run_id": f"{calibration_artifact.get('calibration_run_id') or 'a1'}-conformal",
        "module_id": calibration_artifact.get("module_id") or "A",
        "expression_profile_id": calibration_artifact.get("expression_profile_id") or "A1",
        "horizon": horizon,
        "method": A1_CONFORMAL_METHOD,
        "nominal_coverage": float(nominal_coverage),
        "degraded_coverage_threshold": float(degraded_coverage_threshold),
        "sample_gate": {
            "aggregate_holdout": aggregate_gate,
        },
        "runtime_adapter_unchanged": True,
        "approximate_guarantee_disclosure": approximate_guarantee_disclosure(),
        "coverage_evaluation": {
            "source": "separate_evaluation_predictions"
            if evaluation_predictions is not None
            else "same_holdout_as_quantile_fit",
            "same_rows_as_quantile_fit": evaluation_predictions is None,
            "note": (
                "Same-holdout empirical coverage can be optimistic; separate post-fit evaluation "
                "is required before runtime promotion."
            ),
        },
    }
    if not fit_rows:
        return {
            **base,
            "status": "conformal_skipped_missing_calibration_predictions",
            "reason": "no_usable_calibrated_holdout_predictions",
            "interval_model": None,
            "evaluation_diagnostics": _evaluation_diagnostics(None, eval_rows, degraded_coverage_threshold),
            "regime_coverage": _regime_coverage(None, eval_rows, degraded_coverage_threshold),
            "holdout_intervals": [],
        }
    if not aggregate_gate["sufficient_sample"]:
        return {
            **base,
            "status": "conformal_skipped_insufficient_samples",
            "reason": "aggregate_holdout_below_o24",
            "interval_model": None,
            "evaluation_diagnostics": _evaluation_diagnostics(None, eval_rows, degraded_coverage_threshold),
            "regime_coverage": _regime_coverage(None, eval_rows, degraded_coverage_threshold),
            "holdout_intervals": [],
        }

    q = _conformal_quantile(
        [_nonconformity_score(row["calibrated_probability"], row["label"]) for row in fit_rows],
        coverage=nominal_coverage,
    )
    candidate_model = {
        "type": A1_CONFORMAL_METHOD,
        "nonconformity_score": "absolute_label_probability_error",
        "score_quantile": q,
        "nominal_coverage": float(nominal_coverage),
        "fitted_sample_count": len(fit_rows),
        "operator_decision": "O-23",
    }
    eval_diag = _evaluation_diagnostics(candidate_model, eval_rows, degraded_coverage_threshold)
    empirical_coverage = eval_diag["empirical_coverage"]
    if empirical_coverage is None:
        status = "conformal_skipped_missing_calibration_predictions"
        reason = "no_usable_conformal_evaluation_predictions"
        interval_model: dict[str, Any] | None = None
        holdout_intervals: list[dict[str, Any]] = []
    elif empirical_coverage < float(degraded_coverage_threshold):
        status = "conformal_degraded_empirical_coverage"
        reason = "empirical_coverage_below_o23_degraded_threshold"
        interval_model = None
        holdout_intervals = []
    elif empirical_coverage < float(nominal_coverage):
        status = "conformal_warning_below_nominal"
        reason = "empirical_coverage_below_o23_nominal"
        interval_model = candidate_model
        holdout_intervals = _interval_rows(candidate_model, eval_rows)
    else:
        status = "ok"
        reason = None
        interval_model = candidate_model
        holdout_intervals = _interval_rows(candidate_model, eval_rows)

    return {
        **base,
        "status": status,
        "reason": reason,
        "interval_model": interval_model,
        "evaluation_diagnostics": eval_diag,
        "regime_coverage": _regime_coverage(candidate_model, eval_rows, degraded_coverage_threshold),
        "holdout_intervals": holdout_intervals,
    }


def apply_a1_conformal_interval(interval_model: dict[str, Any], calibrated_probability: float) -> tuple[float, float]:
    """Apply a conformal probability band model to one calibrated probability."""
    if not interval_model or interval_model.get("type") != A1_CONFORMAL_METHOD:
        raise ValueError("invalid A1 conformal interval model")
    q = float(interval_model["score_quantile"])
    p = _bounded_probability(calibrated_probability)
    return round(max(0.0, p - q), 6), round(min(1.0, p + q), 6)


def approximate_guarantee_disclosure() -> dict[str, Any]:
    return {
        "method": A1_CONFORMAL_METHOD,
        "assumption": "exchangeability of calibration and future examples",
        "likely_violation_modes": ["regime_shift", "volatility_clustering", "ticker_universe_drift"],
        "assumption_relaxed_variant": None,
        "qualification": "approximate_not_exact",
        "empirical_diagnostics_required": True,
    }


def _usable_predictions(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        p = _float_or_none(row.get("calibrated_probability"))
        label = _int_label_or_none(row.get("label"))
        if p is None or label is None:
            continue
        out.append({**row, "calibrated_probability": _bounded_probability(p), "label": label})
    return out


def _conformal_quantile(scores: list[float], *, coverage: float) -> float:
    if not scores:
        raise ValueError("cannot fit conformal quantile without scores")
    ordered = sorted(float(s) for s in scores)
    rank = int(math.ceil((len(ordered) + 1) * float(coverage)))
    idx = min(max(rank - 1, 0), len(ordered) - 1)
    return round(ordered[idx], 6)


def _evaluation_diagnostics(
    interval_model: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    degraded_coverage_threshold: float,
) -> dict[str, Any]:
    if not interval_model or not rows:
        return {
            "n": len(rows),
            "empirical_coverage": None,
            "degraded_coverage_threshold": float(degraded_coverage_threshold),
            "covered_count": None,
        }
    covered = sum(1 for row in rows if _covered(interval_model, row))
    coverage = round(covered / len(rows), 6)
    return {
        "n": len(rows),
        "empirical_coverage": coverage,
        "degraded_coverage_threshold": float(degraded_coverage_threshold),
        "covered_count": covered,
    }


def _regime_coverage(
    interval_model: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    degraded_coverage_threshold: float,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for axis in A1_CONFORMAL_REGIME_AXES:
        values = sorted({str(row.get(axis) or "unknown") for row in rows})
        for value in values:
            bucket = [row for row in rows if str(row.get(axis) or "unknown") == value]
            gate = _sample_gate(len(bucket), A1_CALIBRATION_PER_REGIME_MIN_SAMPLES, "O-25")
            key = f"{axis}:{value}"
            entry = {
                "axis": axis,
                "value": value,
                "n": len(bucket),
                "sample_gate": gate,
                "empirical_coverage": None,
                "status": "insufficient_sample" if not gate["sufficient_sample"] else "not_evaluated",
            }
            if interval_model and gate["sufficient_sample"] and bucket:
                covered = sum(1 for row in bucket if _covered(interval_model, row))
                coverage = round(covered / len(bucket), 6)
                entry["empirical_coverage"] = coverage
                entry["status"] = (
                    "degraded"
                    if coverage < float(degraded_coverage_threshold)
                    else "ok"
                )
            out[key] = entry
    return out


def _interval_rows(interval_model: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        p_low, p_high = apply_a1_conformal_interval(interval_model, row["calibrated_probability"])
        out.append(
            {
                "calibration_row_id": row.get("calibration_row_id"),
                "ticker": row.get("ticker"),
                "decision_ts_utc": row.get("decision_ts_utc"),
                "calibrated_probability": row["calibrated_probability"],
                "label": row["label"],
                "p_low": p_low,
                "p_high": p_high,
                "covered": int(row["label"]) >= p_low and int(row["label"]) <= p_high,
                **{axis: row.get(axis) for axis in A1_CONFORMAL_REGIME_AXES},
            }
        )
    return out


def _covered(interval_model: dict[str, Any], row: dict[str, Any]) -> bool:
    p_low, p_high = apply_a1_conformal_interval(interval_model, row["calibrated_probability"])
    label = int(row["label"])
    return label >= p_low and label <= p_high


def _nonconformity_score(calibrated_probability: float, label: int) -> float:
    return abs(float(label) - _bounded_probability(calibrated_probability))


def _bounded_probability(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _sample_gate(n: int, min_required: int, operator_decision: str) -> dict[str, Any]:
    return {
        "n": int(n),
        "min_required": int(min_required),
        "sufficient_sample": int(n) >= int(min_required),
        "status": "ok" if int(n) >= int(min_required) else "insufficient_sample",
        "operator_decision": operator_decision,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None


def _int_label_or_none(value: Any) -> int | None:
    try:
        label = int(value)
    except (TypeError, ValueError):
        return None
    return label if label in (0, 1) else None
