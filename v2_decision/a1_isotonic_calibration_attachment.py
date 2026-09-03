"""Attach A1 isotonic calibration outputs to v2 decision market-state dictionaries."""

from __future__ import annotations

from typing import Any

from v2_decision.a1_isotonic_artifact_loader import load_a1_isotonic_artifact
from v2_decision.a1_isotonic_runtime import apply_a1_v2_calibration_to_raw_probability
from v2_decision.a1_raw_probability import dominant_probability


def attach_a1_isotonic_calibration_to_ms_dict(ms_dict: dict[str, Any], *, ticker: str) -> None:
    """Mutates ms_dict in place. Loads isotonic artifact for the (ticker, primary_horizon)
    pair, applies v2 isotonic calibration to the dominant raw probability, and sets:

    - ms_dict["a1_calibrated_probability"]
    - ms_dict["a1_calibrated_probability_lineage_id"]

    Either both keys populated (artifact loaded, raw probability extracted, calibration
    applied successfully) OR both None (any failure: missing inputs, loader returned None,
    runtime apply returned None). Closes the canonical calibration source gap per
    docs/contracts/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md (e2e1dbc).
    """
    horizon = str(ms_dict.get("primary_horizon") or "").strip().lower()
    if not ticker or not horizon:
        ms_dict["a1_calibrated_probability"] = None
        ms_dict["a1_calibrated_probability_lineage_id"] = None
        return

    artifact = load_a1_isotonic_artifact(ticker=ticker, horizon=horizon)
    raw_probability = dominant_probability(ms_dict)

    calibrated, lineage_id = apply_a1_v2_calibration_to_raw_probability(
        isotonic_artifact=artifact,
        raw_probability=raw_probability,
    )
    ms_dict["a1_calibrated_probability"] = calibrated
    ms_dict["a1_calibrated_probability_lineage_id"] = lineage_id
