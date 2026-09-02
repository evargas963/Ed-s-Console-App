"""Shared A1 conformal artifact contract helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from calibration.v2_a1_conformal import (
    A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION,
    A1_CONFORMAL_DEGRADED_COVERAGE,
)
from calibration.v2_a1_calibration import A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION


ARTIFACT_LIFECYCLE_SCHEMA_VERSION = "1"


def is_eligible_for_current_pointer(artifact: dict) -> tuple[bool, str | None]:
    """Apply the 2C.0/2C.1 seven-criterion ``_current.json`` eligibility gate."""
    required = (
        "schema_version",
        "calibration_run_id",
        "calibration_window_id",
        "conformal_run_id",
        "module_id",
        "expression_profile_id",
        "horizon",
        "ticker_universe",
        "governed_max_age_seconds",
        "generated_at_epoch_seconds",
        "calibration_lineage_id",
        "artifact_lifecycle_schema_version",
    )
    for key in required:
        if key not in artifact:
            return False, f"missing required field: {key}"
    if artifact.get("schema_version") != A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION:
        return False, "schema_version mismatch"
    if artifact.get("artifact_lifecycle_schema_version") != ARTIFACT_LIFECYCLE_SCHEMA_VERSION:
        return False, "artifact_lifecycle_schema_version mismatch"
    if not isinstance(artifact.get("ticker_universe"), list) or not artifact["ticker_universe"]:
        return False, "ticker_universe must be a non-empty list"
    if not str(artifact.get("horizon") or ""):
        return False, "horizon missing"
    coverage_evaluation = artifact.get("coverage_evaluation")
    if not isinstance(coverage_evaluation, dict):
        return False, "coverage_evaluation missing"
    if coverage_evaluation.get("source") != "separate_evaluation_predictions":
        return False, "coverage_evaluation source is not separate_evaluation_predictions"
    diagnostics = artifact.get("evaluation_diagnostics")
    if not isinstance(diagnostics, dict):
        return False, "evaluation_diagnostics missing"
    try:
        empirical_coverage = float(diagnostics["empirical_coverage"])
    except (KeyError, TypeError, ValueError):
        return False, "evaluation_diagnostics.empirical_coverage invalid"
    if empirical_coverage < A1_CONFORMAL_DEGRADED_COVERAGE:
        return False, "evaluation_diagnostics.empirical_coverage below threshold"
    aggregate = (artifact.get("sample_gate") or {}).get("aggregate_holdout")
    if not isinstance(aggregate, dict) or aggregate.get("sufficient_sample") is not True:
        return False, "sample_gate.aggregate_holdout.sufficient_sample is not True"
    if _float_or_none(artifact.get("governed_max_age_seconds")) is None:
        return False, "governed_max_age_seconds invalid"
    if _float_or_none(artifact.get("generated_at_epoch_seconds")) is None:
        return False, "generated_at_epoch_seconds invalid"
    lineage = artifact.get("calibration_lineage_id")
    if not isinstance(lineage, str) or not lineage or ":" not in lineage:
        return False, "calibration_lineage_id invalid"
    return True, None


def is_eligible_for_current_pointer_isotonic(artifact: dict) -> tuple[bool, str | None]:
    """Apply 3.0 contract eligibility for isotonic ``_current.json`` promotion."""
    required = (
        "schema_version",
        "calibration_run_id",
        "calibration_window_id",
        "module_id",
        "expression_profile_id",
        "horizon",
        "method",
        "raw_probability_field",
        "target_label",
        "sample_gate",
        "window",
        "status",
        "reason",
        "model",
        "ticker_universe",
        "governed_max_age_seconds",
        "generated_at_epoch_seconds",
        "calibration_lineage_id",
        "artifact_lifecycle_schema_version",
    )
    for key in required:
        if key not in artifact:
            return False, f"missing required field: {key}"
    if artifact.get("schema_version") != A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION:
        return False, "schema_version mismatch"
    if artifact.get("artifact_lifecycle_schema_version") != ARTIFACT_LIFECYCLE_SCHEMA_VERSION:
        return False, "artifact_lifecycle_schema_version mismatch"
    if not isinstance(artifact.get("ticker_universe"), list) or not artifact["ticker_universe"]:
        return False, "ticker_universe must be a non-empty list"
    if not str(artifact.get("horizon") or ""):
        return False, "horizon missing"
    if artifact.get("status") != "ok":
        return False, "status is not ok"
    if not isinstance(artifact.get("model"), dict) or not artifact["model"]:
        return False, "model must be a non-empty dict"
    aggregate = (artifact.get("sample_gate") or {}).get("aggregate_holdout")
    if not isinstance(aggregate, dict) or aggregate.get("sufficient_sample") is not True:
        return False, "sample_gate.aggregate_holdout.sufficient_sample is not True"
    if _float_or_none(artifact.get("governed_max_age_seconds")) is None:
        return False, "governed_max_age_seconds invalid"
    if _float_or_none(artifact.get("generated_at_epoch_seconds")) is None:
        return False, "generated_at_epoch_seconds invalid"
    lineage = artifact.get("calibration_lineage_id")
    if not isinstance(lineage, str) or not lineage or ":" not in lineage:
        return False, "calibration_lineage_id invalid"
    return True, None


def artifact_output_path(
    *,
    ticker: str,
    horizon: str,
    calibration_run_id: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    data_root: Path | None = None,
    artifact_kind: Literal["conformal", "isotonic"] = "conformal",
) -> Path:
    root = Path("data") if data_root is None else Path(data_root)
    return (
        root
        / "v2_calibration"
        / artifact_kind
        / module_id
        / expression_profile_id
        / ticker
        / horizon
        / f"{calibration_run_id}.json"
    )


def current_pointer_path(
    *,
    ticker: str,
    horizon: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    data_root: Path | None = None,
    artifact_kind: Literal["conformal", "isotonic"] = "conformal",
) -> Path:
    root = Path("data") if data_root is None else Path(data_root)
    return root / "v2_calibration" / artifact_kind / module_id / expression_profile_id / ticker / horizon / "_current.json"


def _float_or_none(value: Any) -> float | None:
    from app.domain.numeric_contract import float_finite_or_none

    return float_finite_or_none(value)
