"""Phase 5B D17 — market_state.py mixed-line lexical NOT_MARKET_DATA boundary.

Scope: exactly 34 deferred Phase 4 mixed-line lexical scanner false positives on
lines that also carry wire/BINOP UNREVIEWED rows. Slice merge uses register_id
exact match (Phase 5B loader change) so co-located wire rows are not NMD-collateral.

Excluded from Phase 4 lexical denylist: 2aed52be1672cf844044 @ L853 (already REPLACED).
"""

from __future__ import annotations

from typing import Final

from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
from governance.phase4_d17_market_state_boundary import (
    PHASE4_LEXICAL_PATTERN_KINDS,
    PHASE4_LEXICAL_REGISTER_DENYLIST,
    PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    PHASE4_MARKET_STATE_PATH,
)

PHASE5B_MARKET_STATE_PATH: Final[str] = PHASE4_MARKET_STATE_PATH

PHASE5B_EXCLUDED_ALREADY_REPLACED_REGISTER_ID: Final[str] = "2aed52be1672cf844044"

# Frozen @ Phase 5B investigation on main @ 1519c44 — Phase 4 denylist minus L853 REPLACED.
PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS: frozenset[str] = frozenset(
    PHASE4_LEXICAL_REGISTER_DENYLIST - {PHASE5B_EXCLUDED_ALREADY_REPLACED_REGISTER_ID}
)

# Representative mixed-line fixture @ market_state.py L702 (collateral proof).
PHASE5B_LINE702_LEXICAL_REGISTER_ID: Final[str] = "b0dae654c91c19dce513"
PHASE5B_LINE702_WIRE_REGISTER_ID: Final[str] = "af0ec82de0c0e4bdd0a6"

PHASE5B_NMD_NOTE: Final[str] = (
    "Phase 5B D17 market_state mixed-line lexical NOT_MARKET_DATA — "
    "register_id-safe merge; wire/BINOP co-located rows preserved"
)

__all__ = (
    "PHASE4_LEXICAL_PATTERN_KINDS",
    "PHASE4_LEXICAL_WIRE_LINE_DENYLIST",
    "PHASE5B_EXCLUDED_ALREADY_REPLACED_REGISTER_ID",
    "PHASE5B_LINE702_LEXICAL_REGISTER_ID",
    "PHASE5B_LINE702_WIRE_REGISTER_ID",
    "PHASE5B_MARKET_STATE_PATH",
    "PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS",
    "PHASE5B_NMD_NOTE",
    "WIRE_PATTERN_KINDS",
)
