"""Phase 5A D17 — market_state.py off-mixed-line structural NOT_MARKET_DATA boundary.

Scope: exactly three UNREVIEWED scanner structural false positives on lines that
are not Phase 4 mixed-line wire/lexical collision lines — DECORATOR_SITE @ L133,
REGISTRY_DISPATCH @ L631 and L812. No wire, lexical, KEEP_DERIVED, or PASS_THROUGH.
"""

from __future__ import annotations

from typing import Final

from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
from governance.phase4_d17_market_state_boundary import (
    PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    PHASE4_MARKET_STATE_PATH,
)

PHASE5A_MARKET_STATE_PATH: Final[str] = PHASE4_MARKET_STATE_PATH

PHASE5A_STRUCTURAL_PATTERN_KINDS: frozenset[str] = frozenset(
    {
        "DECORATOR_SITE",
        "REGISTRY_DISPATCH",
    }
)

PHASE5A_STRUCTURAL_LINES: frozenset[str] = frozenset(
    {
        "133",
        "631",
        "812",
    }
)

# Frozen @ Phase 5A investigation on main @ 742bdd5 (post Phase 4 merge baseline).
PHASE5A_STRUCTURAL_REGISTER_IDS: frozenset[str] = frozenset(
    {
        "1bcf7071b9f5b80f21f8",
        "76a305bd2eef276f31cb",
        "f0e759888b7b89b21112",
    }
)

PHASE5A_NMD_NOTE: Final[str] = (
    "Phase 5A D17 market_state structural NOT_MARKET_DATA — off-mixed-line "
    "DECORATOR_SITE and REGISTRY_DISPATCH scanner false positives only"
)

__all__ = (
    "PHASE5A_MARKET_STATE_PATH",
    "PHASE5A_NMD_NOTE",
    "PHASE5A_STRUCTURAL_LINES",
    "PHASE5A_STRUCTURAL_PATTERN_KINDS",
    "PHASE5A_STRUCTURAL_REGISTER_IDS",
    "PHASE4_LEXICAL_WIRE_LINE_DENYLIST",
    "WIRE_PATTERN_KINDS",
)
