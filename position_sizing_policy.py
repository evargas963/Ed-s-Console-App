"""Position sizing policy constants (COH-SA regime multipliers).

Sibling thresholds (confidence buckets, VIX tiers, MC EAE branches) remain inline in
``call_engine.compute_position_size`` until the magic-thresholds policy-table slice.
"""

from __future__ import annotations

import logging
from typing import Final, Literal

log = logging.getLogger(__name__)

RegimeSizeLabel = Literal[
    "pinning",
    "mean_reversion",
    "reversal_prone",
    "vol_compression",
    "vol_expansion",
    "breakout",
    "acceleration",
    "trend_continuation",
    "unknown",
]

REGIME_SIZE_MULTIPLIER_DEFAULT: Final[float] = 0.70

# Base R-unit regime scale before confidence nudge (high +0.10 capped at 1.0; low -0.10 floor 0.40).
REGIME_SIZE_MULTIPLIERS: Final[dict[str, float]] = {
    # Dealer-pin / range: reduce size — adverse selection and mean-revert chop dominate.
    "pinning": 0.60,
    "mean_reversion": 0.60,
    # Reversal-prone: widest cut — structure vulnerable to failure.
    "reversal_prone": 0.50,
    # Coiling / compressed vol: moderate reduction until expansion confirms.
    "vol_compression": 0.70,
    # Expansion regimes: allow more size; stops often wider but direction clearer.
    "vol_expansion": 0.85,
    "breakout": 0.90,
    "acceleration": 0.90,
    # Trend continuation: full base size when regime confidence supports it.
    "trend_continuation": 1.00,
    # Explicit unknown / resolver miss — same numeric default as dict miss (0.70).
    "unknown": REGIME_SIZE_MULTIPLIER_DEFAULT,
}


def regime_size_multiplier(
    regime_label: str | None,
    regime_confidence: str | None = None,
) -> float:
    """
    Regime + confidence → R-unit regime multiplier for ``compute_position_size``.

    Unknown or typo'd labels log at debug and use ``REGIME_SIZE_MULTIPLIER_DEFAULT``.
    """
    label = (regime_label or "").strip() or "unknown"
    mult = REGIME_SIZE_MULTIPLIERS.get(label)
    if mult is None:
        log.debug(
            "regime_size_multiplier: unmapped regime_label=%r → default %.2f",
            regime_label,
            REGIME_SIZE_MULTIPLIER_DEFAULT,
        )
        mult = REGIME_SIZE_MULTIPLIER_DEFAULT

    conf = (regime_confidence or "").strip().lower()
    if conf == "high" and mult < 1.0:
        mult = min(1.0, mult + 0.10)
    elif conf == "low":
        mult = max(0.40, mult - 0.10)

    return mult
