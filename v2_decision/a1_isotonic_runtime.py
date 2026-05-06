"""Runtime apply helper for A1 v2 isotonic calibration."""

from __future__ import annotations

from typing import Any

from calibration.a1_conformal_artifact_production import compute_calibration_lineage_id
from calibration.v2_a1_calibration import apply_isotonic_model

import logging

log = logging.getLogger(__name__)


def apply_a1_v2_calibration_to_raw_probability(
    *,
    isotonic_artifact: dict[str, Any] | None,
    raw_probability: float | None,
) -> tuple[float | None, str | None]:
    """Apply v2 isotonic calibration to a raw probability.

    Returns (calibrated_probability, lineage_id) on success, or (None, None) on
    any failure (invalid inputs, missing model, etc.).

    Per governance/A1_ISOTONIC_ARTIFACT_LIFECYCLE_AND_RUNTIME_CONTRACT.md §8.
    Never raises in production. Logs at debug.
    """
    try:
        if not isinstance(isotonic_artifact, dict):
            return None, None
        model = isotonic_artifact.get("model")
        if not isinstance(model, dict):
            return None, None
        if not isinstance(raw_probability, (int, float)) or isinstance(raw_probability, bool):
            return None, None
        raw = float(raw_probability)
        if raw < 0.0 or raw > 1.0:
            return None, None
        calibrated = float(apply_isotonic_model(model, raw))
        if calibrated < 0.0 or calibrated > 1.0:
            return None, None
        lineage_id = compute_calibration_lineage_id(isotonic_artifact)
        if not isinstance(lineage_id, str) or not lineage_id or ":" not in lineage_id:
            return None, None
        return calibrated, lineage_id
    except Exception:
        log.debug("A1 v2 isotonic calibration apply failed", exc_info=True)
        return None, None
