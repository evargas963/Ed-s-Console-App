"""A1 conformal interval promotion helper.

This module is intentionally payload-only: it consumes an already supplied
conformal artifact and calibrated probability from ``ms_dict``. It performs no
filesystem I/O, caching, artifact discovery, or policy binding.
"""

from __future__ import annotations

import time
from typing import Any


OK_STATUS = "ok"
A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION = "1"
A1_CONFORMAL_DEGRADED_COVERAGE = 0.85


def derive_a1_conformal_bounds(ms_dict: dict[str, Any]) -> tuple[float | None, float | None, str]:
    """Return ``(p_low, p_high, status)`` for A1 conformal interval promotion."""
    artifact = ms_dict.get("a1_conformal_artifact")
    calibrated_probability = _bounded_probability_or_none(ms_dict.get("a1_calibrated_probability"))
    if not isinstance(artifact, dict):
        return None, None, "precondition_1_artifact_present_failed"

    if artifact.get("schema_version") != A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION:
        return None, None, "precondition_2_schema_version_failed"

    if not _honest_evaluation_passes(artifact):
        return None, None, "precondition_3_honest_evaluation_failed"

    if not _aggregate_sample_gate_passes(artifact):
        return None, None, "precondition_4_aggregate_sample_threshold_failed"

    if not _horizon_matches(artifact, ms_dict):
        return None, None, "precondition_5_horizon_match_failed"

    if not _freshness_passes(artifact, now=time.time()):
        return None, None, "precondition_6_freshness_failed"

    if calibrated_probability is None:
        return None, None, "precondition_7_calibrated_probability_failed"

    if not _lineage_match_passes(artifact, ms_dict):
        return None, None, "precondition_8_calibration_lineage_match_failed"

    interval_model = artifact.get("interval_model")
    if not isinstance(interval_model, dict):
        return None, None, "precondition_1_artifact_present_failed"

    from calibration.v2_a1_conformal import apply_a1_conformal_interval

    p_low, p_high = apply_a1_conformal_interval(interval_model, calibrated_probability)
    return p_low, p_high, OK_STATUS


def _honest_evaluation_passes(artifact: dict[str, Any]) -> bool:
    if artifact.get("status") not in ("ok", "conformal_warning_below_nominal"):
        return False
    coverage = artifact.get("coverage_evaluation")
    if not isinstance(coverage, dict):
        return False
    if coverage.get("source") != "separate_evaluation_predictions":
        return False
    if coverage.get("same_rows_as_quantile_fit") is True:
        return False
    diagnostics = artifact.get("evaluation_diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    empirical_coverage = _float_or_none(diagnostics.get("empirical_coverage"))
    return empirical_coverage is not None and empirical_coverage >= A1_CONFORMAL_DEGRADED_COVERAGE


def _aggregate_sample_gate_passes(artifact: dict[str, Any]) -> bool:
    sample_gate = artifact.get("sample_gate")
    if not isinstance(sample_gate, dict):
        return False
    aggregate = sample_gate.get("aggregate_holdout")
    if not isinstance(aggregate, dict):
        return False
    if aggregate.get("sufficient_sample") is not True:
        return False
    n = _float_or_none(aggregate.get("n"))
    from calibration.v2_a1_calibration import A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES

    return n is None or n >= A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES


def _horizon_matches(artifact: dict[str, Any], ms_dict: dict[str, Any]) -> bool:
    artifact_horizon = str(artifact.get("horizon") or "").strip().lower()
    primary_horizon = str(ms_dict.get("primary_horizon") or "").strip().lower()
    return bool(artifact_horizon and primary_horizon and artifact_horizon == primary_horizon)


def _freshness_passes(artifact: dict[str, Any], *, now: float) -> bool:
    max_age = _float_or_none(artifact.get("governed_max_age_seconds"))
    generated_at = _float_or_none(artifact.get("generated_at_epoch_seconds"))
    if max_age is None or generated_at is None or max_age < 0:
        return False
    return now - generated_at <= max_age


def _lineage_match_passes(artifact: dict[str, Any], ms_dict: dict[str, Any]) -> bool:
    probability_lineage = ms_dict.get("a1_calibrated_probability_lineage_id")
    artifact_lineage = artifact.get("calibration_lineage_id")
    return (
        isinstance(probability_lineage, str)
        and isinstance(artifact_lineage, str)
        and probability_lineage != ""
        and artifact_lineage != ""
        and probability_lineage == artifact_lineage
    )


def _bounded_probability_or_none(value: Any) -> float | None:
    probability = _float_or_none(value)
    if probability is None or probability < 0.0 or probability > 1.0:
        return None
    return probability


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
