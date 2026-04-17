"""Phase 6 — diagnostic only: horizon availability vs hypothetical min-sample thresholds."""
from __future__ import annotations

from typing import Any

from prediction_engine import _count_labeled

from verification.similar_set_trace import PRODUCT_EMPIRICAL

DEFAULT_THRESHOLDS = (20, 25, 30, 35)


def _horizon_status(n: int, thr: int) -> str:
    if n >= thr:
        return "valid"
    return "withheld"


def threshold_stress_on_similar(similar: list, thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    counts = {hz: _count_labeled(similar, col) for hz, col, _ in PRODUCT_EMPIRICAL}
    by_thr: dict[str, Any] = {}
    for thr in thresholds:
        hz_states = {hz: _horizon_status(counts[hz], thr) for hz in counts}
        withheld_any = any(hz_states[hz] == "withheld" for hz in ("1c", "5c", "15c", "60c"))
        by_thr[str(thr)] = {
            "per_horizon": hz_states,
            "labeled_counts": counts,
            "all_four_valid": all(hz_states[hz] == "valid" for hz in ("1c", "5c", "15c", "60c")),
            "note": (
                "final_tradeable/WAIT also depends on multi_horizon_decision + fusion; "
                "this flags empirical sufficiency only."
            ),
        }
    return {"similar_size": len(similar), "thresholds": by_thr}
