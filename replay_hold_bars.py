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

from app.domain.time_et import RTH_SESSION_MINUTES

# ── STACK-WIRE-6: single source of truth for trade_type → max 1m hold bars ──
# Both ``replay_max_hold_bars_for_setup`` and ``replay_max_hold_bars_for_trade_type``
# MUST return the same value for the same trade_type. "none" means no trade →
# 0-bar hold (FIND-WIRE6-2 parity break: fallback used to return 20).
TRADE_TYPE_HOLD_BARS: dict[str, int] = {
    "trend_continuation": 60,
    "breakout": 15,
    "reversal": 20,
    "fade": 30,
    "mean_reversion": 30,
    "none": 0,
}
TRADE_TYPE_HOLD_BARS_DEFAULT: int = 30
# Micro_regime override applies only in the live ``for_setup`` path (compression
# squeezes hold to 15 bars regardless of trade_type, except "none" which is 0).
MICRO_REGIME_HOLD_BARS_COMPRESSION: int = 15


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


def replay_max_hold_bars_for_trade_type(trade_type: str | None) -> int:
    """Fallback max 1m bars when Call card did not supply ``replay_max_hold_bars_live``."""
    t = (trade_type or "").strip().lower()
    return TRADE_TYPE_HOLD_BARS.get(t, TRADE_TYPE_HOLD_BARS_DEFAULT)


def replay_max_hold_bars_for_setup(micro_regime: str, trade_type: str) -> int:
    """
    Max 1m bars for historical replay time_expiry — branches stay aligned with Call ``_time_qualifier()``.

    Canonical 1m snapshots: one bar ≈ one minute of RTH cadence in the training table.
    """
    from micro_structure import R_COMPRESSION, R_RANGE

    if trade_type == "none":
        return TRADE_TYPE_HOLD_BARS["none"]  # 0 — no-trade signal short-circuits micro_regime
    if micro_regime == R_COMPRESSION:
        return MICRO_REGIME_HOLD_BARS_COMPRESSION  # 15 — compression overrides trade_type defaults
    if trade_type in TRADE_TYPE_HOLD_BARS:
        return TRADE_TYPE_HOLD_BARS[trade_type]
    if micro_regime == R_RANGE:
        return TRADE_TYPE_HOLD_BARS_DEFAULT
    return TRADE_TYPE_HOLD_BARS_DEFAULT


def resolve_replay_max_hold_bars_for_payload(
    *,
    trade_type: str | None,
    replay_max_hold_bars_live: int | None,
) -> tuple[int, str, int]:
    """
    Choose hold bars for ``build_replay_context_payload``.

    Returns ``(resolved_bars, source, trade_type_fallback_bars)`` where source is
    ``call_card`` or ``trade_type_fallback``.
    """
    hold_fb = replay_max_hold_bars_for_trade_type(trade_type)
    try:
        live = int(replay_max_hold_bars_live) if replay_max_hold_bars_live is not None else None
    except (TypeError, ValueError):
        live = None
    if live is not None and live > 0:
        return live, "call_card", hold_fb
    return hold_fb, "trade_type_fallback", hold_fb
