"""
Multi-plane architecture — L1 near-real-time context lives in context_light.

L0: live_market_plane (authoritative quotes)
L2: server _state_cache ms_dict (heavy analytics, versioned)
L3: DB / persistence (never imported here)
"""

from planes.context_light import (
    L1_SCHEMA_VERSION,
    L1BuildContext,
    PLANE_L1,
    MERGE_RULE_L1,
    build_l1_context,
)

__all__ = [
    "L1_SCHEMA_VERSION",
    "L1BuildContext",
    "PLANE_L1",
    "MERGE_RULE_L1",
    "build_l1_context",
]
