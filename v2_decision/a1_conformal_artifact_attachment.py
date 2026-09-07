"""Attach A1 conformal artifacts to v2 decision market-state dictionaries."""

from __future__ import annotations

from typing import Any

from v2_decision.a1_conformal_artifact_loader import load_a1_conformal_artifact


def attach_a1_conformal_artifact_to_ms_dict(ms_dict: dict[str, Any], *, ticker: str) -> None:
    """Mutate ``ms_dict`` with the runtime-loadable A1 conformal artifact.

    Handles ONLY the conformal artifact attachment. The sibling helper
    ``attach_a1_isotonic_calibration_to_ms_dict`` in
    ``v2_decision/a1_isotonic_calibration_attachment.py`` injects
    ``a1_calibrated_probability`` and
    ``a1_calibrated_probability_lineage_id`` per
    ``docs/contracts/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md``. Both
    helpers run in sequence at the server.py call sites.
    """
    horizon = str(ms_dict.get("primary_horizon") or "").strip().lower()
    if not ticker or not horizon:
        ms_dict["a1_conformal_artifact"] = None
        return
    ms_dict["a1_conformal_artifact"] = load_a1_conformal_artifact(
        ticker=ticker,
        horizon=horizon,
    )
