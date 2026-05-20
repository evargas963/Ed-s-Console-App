"""Replay max-hold bar authority (COH-I-K / COH-SA).

Three related helpers with distinct inputs:

- ``replay_max_hold_bars_for_setup`` — live Call card prescription (micro_regime + trade_type).
- ``replay_max_hold_bars_from_context`` — strict read from persisted ``replay_context_json``.
- ``replay_max_hold_bars_for_trade_type`` — trade-type-only fallback when live card value absent.
"""

from __future__ import annotations


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
    return min(n, 390)


def replay_max_hold_bars_for_trade_type(trade_type: str | None) -> int:
    """Fallback max 1m bars when Call card did not supply ``replay_max_hold_bars_live``."""
    t = (trade_type or "").strip().lower()
    if t == "trend_continuation":
        return 60
    if t == "breakout":
        return 15
    if t == "reversal":
        return 20
    if t in ("fade", "mean_reversion"):
        return 30
    if t == "none":
        return 20
    return 30


def replay_max_hold_bars_for_setup(micro_regime: str, trade_type: str) -> int:
    """
    Max 1m bars for historical replay time_expiry — branches stay aligned with Call ``_time_qualifier()``.

    Canonical 1m snapshots: one bar ≈ one minute of RTH cadence in the training table.
    """
    from micro_structure import R_COMPRESSION, R_RANGE

    if trade_type == "none":
        return 0
    if micro_regime == R_COMPRESSION:
        return 15
    if trade_type == "fade":
        return 30
    if trade_type == "breakout":
        return 15
    if trade_type == "reversal":
        return 20
    if trade_type == "trend_continuation":
        return 60
    if trade_type == "mean_reversion":
        return 30
    if micro_regime == R_RANGE:
        return 30
    return 30


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
