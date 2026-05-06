"""Manual A1 isotonic artifact production helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from calibration.a1_conformal_artifact_production import (
    augment_artifact_with_lifecycle_fields,
    compute_calibration_lineage_id,
    update_current_pointer_atomically,
    write_artifact_atomically,
)
from calibration.v2_a1_calibration import (
    WalkForwardSplit,
    fit_a1_isotonic_artifact,
    load_a1_calibration_rows,
)
from v2_decision.a1_conformal_artifact_contract import (
    artifact_output_path,
    current_pointer_path,
    is_eligible_for_current_pointer_isotonic,
)


def produce_a1_isotonic_artifact(
    *,
    db_path: Path,
    ticker: str,
    horizon: str,
    train_start: float,
    train_end: float,
    calibration_start: float,
    calibration_end: float,
    holdout_start: float,
    holdout_end: float,
    governed_max_age_seconds: float,
    now_epoch_seconds: float,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Run the manual A1 isotonic artifact production pipeline."""
    split = WalkForwardSplit(
        train_start=float(train_start),
        train_end=float(train_end),
        calibration_start=float(calibration_start),
        calibration_end=float(calibration_end),
        holdout_start=float(holdout_start),
        holdout_end=float(holdout_end),
    )
    rows = [
        row
        for row in load_a1_calibration_rows(Path(db_path), horizon=str(horizon))
        if str(row.get("ticker") or "").upper() == str(ticker).upper()
    ]
    isotonic_artifact = fit_a1_isotonic_artifact(rows, horizon=str(horizon), split=split)
    artifact = augment_artifact_with_lifecycle_fields(
        artifact=isotonic_artifact,
        ticker=str(ticker),
        governed_max_age_seconds=float(governed_max_age_seconds),
        generated_at_epoch_seconds=float(now_epoch_seconds),
        calibration_lineage_id=compute_calibration_lineage_id(isotonic_artifact),
    )
    output_path = artifact_output_path(
        ticker=str(ticker),
        horizon=str(horizon),
        calibration_run_id=str(artifact["calibration_run_id"]),
        module_id=str(artifact.get("module_id") or "A"),
        expression_profile_id=str(artifact.get("expression_profile_id") or "A1"),
        data_root=data_root,
        artifact_kind="isotonic",
    )
    write_artifact_atomically(artifact=artifact, output_path=output_path)

    eligible, reason = is_eligible_for_current_pointer_isotonic(artifact)
    pointer_updated = False
    if eligible:
        pointer_path = current_pointer_path(
            ticker=str(ticker),
            horizon=str(horizon),
            module_id=str(artifact.get("module_id") or "A"),
            expression_profile_id=str(artifact.get("expression_profile_id") or "A1"),
            data_root=data_root,
            artifact_kind="isotonic",
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
