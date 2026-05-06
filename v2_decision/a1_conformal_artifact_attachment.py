"""Attach A1 conformal artifacts to v2 decision market-state dictionaries."""

from __future__ import annotations

from typing import Any

from v2_decision.a1_conformal_artifact_loader import load_a1_conformal_artifact


def attach_a1_conformal_artifact_to_ms_dict(ms_dict: dict[str, Any], *, ticker: str) -> None:
    """Mutate ``ms_dict`` with the runtime-loadable A1 conformal artifact.

    This intentionally does not inject ``a1_calibrated_probability`` or
    ``a1_calibrated_probability_lineage_id``. Per
    ``governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md``, the
    canonical calibration source is not yet wired into runtime; injecting either
    field here would fake provenance. Preconditions 7 and 8 in
    ``derive_a1_conformal_bounds`` fail honestly until that canonical path
    exists.
    """
    horizon = str(ms_dict.get("primary_horizon") or "").strip().lower()
    if not ticker or not horizon:
        ms_dict["a1_conformal_artifact"] = None
        return
    ms_dict["a1_conformal_artifact"] = load_a1_conformal_artifact(
        ticker=ticker,
        horizon=horizon,
    )
