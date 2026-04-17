"""Aggregate FULL / PARTIAL / DEGRADED grade from per-horizon fused_stack_status_* + fused_move_prob_*."""
from __future__ import annotations

from typing import Any

from ml_horizon import ML_HORIZON_SLUGS


def fusion_replay_stack_grade_v1(flat: dict[str, Any]) -> str | None:
    """
    FULL: all governed horizons have fused_move_prob and fusion_ok-style status.
    DEGRADED: all horizons have fused_move_prob but at least one horizon not fusion_ok.
    PARTIAL: some but not all horizons produced fused_move_prob.
    """
    n_hz = len(ML_HORIZON_SLUGS)
    present: list[str] = []
    ok_pat = "fusion_ok"
    for hz in ML_HORIZON_SLUGS:
        k = f"fused_move_prob_{hz}"
        if k not in flat or flat[k] is None:
            continue
        present.append(hz)
    n = len(present)
    if n == 0:
        return None
    if n < n_hz:
        return "PARTIAL"
    statuses = [flat.get(f"fused_stack_status_{hz}") for hz in ML_HORIZON_SLUGS]
    all_ok = all(
        s is not None and ok_pat in str(s).lower() and "fusion_unavailable" not in str(s).lower()
        for s in statuses
    )
    if all_ok:
        return "FULL"
    return "DEGRADED"
