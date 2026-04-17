"""
Canonical 60s UTC grid helpers for BAR_ANCHOR_V1 (Issue 4) + price_bars_1m.

Used by scan/repair tools and DB write guards. Grid: bar_start_ts_utc ≡ 0 (mod 60).
"""
from __future__ import annotations

import math
from typing import Iterable

# Must match horizon_outcomes.OUTCOME_BAR_SPECS forward minutes.
FORWARD_MINUTES: tuple[int, ...] = (1, 3, 5, 8, 13, 15, 60)


def is_canonical_bar_start_ts_utc(ts: float) -> bool:
    """True if ts is on the 60-second UTC grid (bar open)."""
    try:
        x = float(ts)
    except (TypeError, ValueError):
        return False
    if x <= 0:
        return False
    # Whole-minute epoch seconds (allow tiny float noise)
    return abs(x - round(x / 60.0) * 60.0) < 1e-3


def forward_bar_starts_for_snapshot(ts_snapshot: float) -> dict[str, float]:
    """Map outcome column prefix -> required forward bar_start_ts_utc."""
    from horizon_outcomes import forward_bar_start_utc, OUTCOME_BAR_SPECS

    out: dict[str, float] = {}
    for odir, _opt, n_min in OUTCOME_BAR_SPECS:
        out[odir] = float(forward_bar_start_utc(ts_snapshot, n_min))
    return out


def max_forward_minutes() -> int:
    return max(FORWARD_MINUTES)
