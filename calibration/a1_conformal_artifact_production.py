"""Manual A1 conformal artifact production helpers.

This module is intentionally explicit and testable: no scheduler hooks, no
implicit window defaults, and no writes outside caller-provided paths.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

from calibration.v2_a1_calibration import (
    WalkForwardSplit,
    apply_isotonic_model,
    fit_a1_isotonic_artifact,
    load_a1_calibration_rows,
)
from calibration.v2_a1_conformal import (
    A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION,
    A1_CONFORMAL_DEGRADED_COVERAGE,
    build_a1_conformal_artifact,
)


ARTIFACT_LIFECYCLE_SCHEMA_VERSION = "1"


def compute_calibration_lineage_id(calibration_artifact: dict) -> str:
    """Return ``<calibration_run_id>:<sha256(canonical model json)>``."""
    run_id = str(calibration_artifact["calibration_run_id"])
    model_json = json.dumps(
        calibration_artifact["model"],
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{run_id}:{sha256(model_json.encode('utf-8')).hexdigest()}"


def augment_conformal_artifact_with_lifecycle_fields(
    *,
    conformal_artifact: dict,
    ticker: str,
    governed_max_age_seconds: float,
    generated_at_epoch_seconds: float,
    calibration_lineage_id: str,
) -> dict:
    """Return a copy of a conformal artifact with 2A lifecycle fields added."""
    return {
        **conformal_artifact,
        "ticker_universe": [ticker],
        "governed_max_age_seconds": governed_max_age_seconds,
        "generated_at_epoch_seconds": generated_at_epoch_seconds,
        "calibration_lineage_id": calibration_lineage_id,
        "artifact_lifecycle_schema_version": ARTIFACT_LIFECYCLE_SCHEMA_VERSION,
    }


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


def artifact_output_path(
    *,
    ticker: str,
    horizon: str,
    calibration_run_id: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    data_root: Path | None = None,
) -> Path:
    root = Path("data") if data_root is None else Path(data_root)
    return (
        root
        / "v2_calibration"
        / "conformal"
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
) -> Path:
    root = Path("data") if data_root is None else Path(data_root)
    return root / "v2_calibration" / "conformal" / module_id / expression_profile_id / ticker / horizon / "_current.json"


def write_artifact_atomically(*, artifact: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str), encoding="utf-8")


def update_current_pointer_atomically(*, artifact_relative_path: str, pointer_path: Path) -> None:
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = pointer_path.with_name(f"{pointer_path.name}.new")
    tmp_path.write_text(
        json.dumps({"artifact_relative_path": artifact_relative_path}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, pointer_path)


def produce_a1_conformal_artifact(
    *,
    db_path,
    ticker,
    horizon,
    train_start,
    train_end,
    calibration_start,
    calibration_end,
    holdout_start,
    holdout_end,
    eval_start,
    eval_end,
    governed_max_age_seconds,
    now_epoch_seconds,
    data_root: Path | None = None,
) -> dict:
    """Run the manual A1 conformal artifact production pipeline."""
    split = WalkForwardSplit(
        train_start=float(train_start),
        train_end=float(train_end),
        calibration_start=float(calibration_start),
        calibration_end=float(calibration_end),
        holdout_start=float(holdout_start),
        holdout_end=float(holdout_end),
    )
    if float(eval_start) < float(holdout_end):
        raise ValueError("eval_start must be greater than or equal to holdout_end")

    rows = [
        row
        for row in load_a1_calibration_rows(Path(db_path), horizon=str(horizon))
        if str(row.get("ticker") or "").upper() == str(ticker).upper()
    ]
    calibration_artifact = fit_a1_isotonic_artifact(rows, horizon=str(horizon), split=split)
    model = calibration_artifact.get("model")
    if not isinstance(model, dict):
        raise ValueError("calibration artifact model is required")
    evaluation_rows = [
        row
        for row in rows
        if float(eval_start) <= float(row.get("decision_ts_utc")) <= float(eval_end)
    ]
    evaluation_predictions = [
        {
            **row,
            "calibrated_probability": apply_isotonic_model(model, row["raw_probability"]),
        }
        for row in evaluation_rows
    ]
    conformal_artifact = build_a1_conformal_artifact(
        calibration_artifact,
        evaluation_predictions=evaluation_predictions,
    )
    artifact = augment_conformal_artifact_with_lifecycle_fields(
        conformal_artifact=conformal_artifact,
        ticker=str(ticker),
        governed_max_age_seconds=float(governed_max_age_seconds),
        generated_at_epoch_seconds=float(now_epoch_seconds),
        calibration_lineage_id=compute_calibration_lineage_id(calibration_artifact),
    )
    output_path = artifact_output_path(
        ticker=str(ticker),
        horizon=str(horizon),
        calibration_run_id=str(artifact["calibration_run_id"]),
        module_id=str(artifact.get("module_id") or "A"),
        expression_profile_id=str(artifact.get("expression_profile_id") or "A1"),
        data_root=data_root,
    )
    write_artifact_atomically(artifact=artifact, output_path=output_path)

    eligible, reason = is_eligible_for_current_pointer(artifact)
    pointer_updated = False
    if eligible:
        pointer_path = current_pointer_path(
            ticker=str(ticker),
            horizon=str(horizon),
            module_id=str(artifact.get("module_id") or "A"),
            expression_profile_id=str(artifact.get("expression_profile_id") or "A1"),
            data_root=data_root,
        )
        relative_path = output_path.relative_to(Path("data") if data_root is None else Path(data_root))
        update_current_pointer_atomically(
            artifact_relative_path=relative_path.as_posix(),
            pointer_path=pointer_path,
        )
        pointer_updated = True

    return {
        "status": "ok" if pointer_updated else "audit_not_promoted",
        "artifact_path": output_path,
        "pointer_updated": pointer_updated,
        "eligibility_reason": reason,
        "artifact": artifact,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
