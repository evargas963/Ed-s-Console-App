"""Replay max-hold bar authority (COH-I-K / COH-SA).

Three related helpers with distinct inputs:

- ``replay_max_hold_bars_for_setup`` — live Call card prescription (micro_regime + trade_type).
- ``replay_max_hold_bars_from_context`` — strict read from persisted ``replay_context_json``.
- ``replay_max_hold_bars_for_trade_type`` — trade-type-only fallback when live card value absent.

STACK-WIRE-6 (FIND-WIRE6-1, FIND-WIRE6-2): ``TRADE_TYPE_HOLD_BARS`` is the single
source of truth for trade_type → max 1m hold bars; both setup and fallback paths
read from it. ``trade_type="none"`` returns 0 in BOTH paths (prior divergence had
the fallback returning 20 vs the live setup returning 0). The
``replay_max_hold_bars_from_context`` upper cap derives from
``time_et.RTH_SESSION_MINUTES`` (= ``RTH_END_MINS - RTH_START_MINS = 390``).
"""

from __future__ import annotations

from time_et import RTH_SESSION_MINUTES



def replay_max_hold_bars_from_context(replay_obj: dict) -> int | None:
    """Require explicit replay_max_hold_bars in replay_context_json (no silent 30-bar default)."""
    raw = replay_obj.get("replay_max_hold_bars")
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    return min(n, RTH_SESSION_MINUTES)






