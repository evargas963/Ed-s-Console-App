"""Shared static lifecycle rule core for A2 advisory lifecycle work.

This module is intentionally consumer-free in Commit A: it defines the shared
threshold-derivation and exit-firing primitives that later commits can wire into
``realized_contract_eval.py`` and the in-scope geometry portions of
``call_engine.py``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, NamedTuple, Sequence

from math_exposure import (
    STOP_BASE_PCT,
    STOP_CEILING_PCT,
    STOP_FLOOR_PCT,
    STOP_TIME_DECAY_PCT,
    STOP_VIX_HIGH_PCT,
    STOP_VIX_MED_PCT,
)


LIFECYCLE_RULE_CORE_VERSION = "0.1.0"

Direction = Literal["long", "short"]
ExitReason = Literal["stop_hit", "target_hit", "time_expiry"]

MAX_RR_T1 = 5.0
MAX_RR_T2 = 8.0
MIN_RR = 1.5


class SameBarResolution(str, Enum):
    CANDLE_BODY_OPEN_CLOSE = "candle_body_open_close"
    CONSERVATIVE_STOP_FIRST = "conservative_stop_first"
    NO_CONFLICT = "no_conflict"


class StopDistance(NamedTuple):
    final_pct: float
    adjustments_applied: tuple[str, ...]


class TargetLevels(NamedTuple):
    target: float
    target2: float
    target_source: str
    target2_source: str
    target_snapped: bool
    target2_snapped: bool


class ExitOutcome(NamedTuple):
    exit_reason: ExitReason | None
    skip_reason: str | None
    exit_bar_index: int | None
    same_bar_conflict: bool
    same_bar_resolution_rule: str


class SameBarConflictResult(NamedTuple):
    resolution: SameBarResolution
    exit_reason: ExitReason | None
    same_bar_resolution_rule: str


def apply_time_decay(distance_pct: float, mins_elapsed_since_open: float | None) -> float:
    mins = max(0.0, float(mins_elapsed_since_open or 0.0))
    return float(distance_pct) - (mins / 60.0) * STOP_TIME_DECAY_PCT


def apply_vix_adjustment(distance_pct: float, vix_level: float | None) -> float:
    pct = float(distance_pct)
    if vix_level is None:
        return pct
    vix = float(vix_level)
    if vix > 30:
        return pct + STOP_VIX_HIGH_PCT
    if vix > 20:
        return pct + STOP_VIX_MED_PCT
    return pct


def apply_risk_multiplier(distance_pct: float, risk_multiplier: float | None) -> float:
    mult = risk_multiplier or 1.0
    return float(distance_pct) * max(0.8, min(1.5, float(mult)))


def derive_stop_distance_pct(
    *,
    spot: float,
    vix_level: float | None,
    mins_elapsed_since_open: float | None,
    risk_multiplier: float | None,
) -> StopDistance:
    """Derive final stop percentage using call_engine's current order."""
    _ = float(spot)  # Kept in the API so Commit C can mirror call_engine inputs.
    adjustments: list[str] = []
    pct = STOP_BASE_PCT

    pct = apply_time_decay(pct, mins_elapsed_since_open)
    if mins_elapsed_since_open and float(mins_elapsed_since_open) > 0:
        adjustments.append("time_decay")

    before_vix = pct
    pct = apply_vix_adjustment(pct, vix_level)
    if pct != before_vix:
        adjustments.append("vix_high" if vix_level is not None and float(vix_level) > 30 else "vix_medium")

    before_mult = pct
    pct = apply_risk_multiplier(pct, risk_multiplier)
    if pct != before_mult:
        adjustments.append("risk_multiplier")

    pct = max(STOP_FLOOR_PCT, min(STOP_CEILING_PCT, pct))
    return StopDistance(final_pct=pct, adjustments_applied=tuple(adjustments))


def snap_target_to_structural(
    *,
    target_price: float,
    structural_levels: Sequence[float],
    direction: Direction,
    risk: float,
) -> float:
    """Snap to the nearest eligible structural level within 1.5 risk units.

    ``structural_levels`` must already be direction-eligible for the setup
    (above spot for long, below spot for short), preserving call_engine's
    current filtering boundary for the later consumer rewire.
    """
    target = float(target_price)
    snap_range = float(risk) * 1.5
    if direction == "long":
        candidates = [float(level) for level in structural_levels if level and float(level) > target - snap_range]
    else:
        candidates = [float(level) for level in structural_levels if level and float(level) < target + snap_range]
    nearby = [level for level in candidates if abs(level - target) <= snap_range]
    if nearby:
        return min(nearby, key=lambda level: abs(level - target))
    return target


def derive_target_levels(
    *,
    entry: float,
    direction: Direction,
    risk: float,
    avg5: float | None,
    avg15: float | None,
    avg60: float | None,
    structural_levels: Sequence[float],
) -> TargetLevels:
    """Derive T1/T2 using call_engine's current R/R and horizon rules.

    ``risk`` is absolute dollar risk (``abs(entry - stop)``), not a percentage.
    """
    entry_f = float(entry)
    risk_f = float(risk)
    if risk_f <= 0:
        raise ValueError("risk must be positive absolute dollar risk")
    sign = 1.0 if direction == "long" else -1.0

    avg5_abs = _abs_or_none(avg5)
    avg15_abs = _abs_or_none(avg15)
    avg60_abs = _abs_or_none(avg60)

    if avg5_abs is not None and avg5_abs > risk_f * MIN_RR:
        target_raw = entry_f + sign * min(avg5_abs, risk_f * MAX_RR_T1)
        target_source = "5c_avg_move"
    else:
        target_raw = entry_f + sign * risk_f * 2.0
        target_source = "2r_fallback"

    target_snapped_raw = snap_target_to_structural(
        target_price=target_raw,
        structural_levels=structural_levels,
        direction=direction,
        risk=risk_f,
    )
    target = _cap_target(entry_f, target_snapped_raw, direction, risk_f, MAX_RR_T1)
    target_snapped = round(target_snapped_raw, 8) != round(target_raw, 8)

    target_distance = abs(target - entry_f)
    if avg15_abs is not None and avg15_abs > target_distance:
        target2_raw = entry_f + sign * min(avg15_abs, risk_f * MAX_RR_T2)
        target2_source = "15c_avg_move"
    elif avg60_abs is not None and avg60_abs > target_distance:
        target2_raw = entry_f + sign * min(avg60_abs, risk_f * MAX_RR_T2)
        target2_source = "60c_avg_move"
    else:
        target2_raw = target + sign * risk_f
        target2_source = "1r_offset_from_t1"

    target2_snapped_raw = snap_target_to_structural(
        target_price=target2_raw,
        structural_levels=structural_levels,
        direction=direction,
        risk=risk_f,
    )
    target2 = _cap_target(entry_f, target2_snapped_raw, direction, risk_f, MAX_RR_T2)
    if direction == "long" and target2 <= target:
        target2 = round(target + risk_f, 2)
    elif direction == "short" and target2 >= target:
        target2 = round(target - risk_f, 2)
    target2_snapped = round(target2_snapped_raw, 8) != round(target2_raw, 8)

    return TargetLevels(
        target=round(target, 2),
        target2=round(target2, 2),
        target_source=target_source,
        target2_source=target2_source,
        target_snapped=target_snapped,
        target2_snapped=target2_snapped,
    )


def resolve_same_bar_conflict(
    *,
    bar_ohlc: dict[str, Any],
    stop: float,
    target: float,
    signal: str,
) -> SameBarConflictResult:
    sig = (signal or "").strip().lower()
    co = _float_or_none(_bar_value(bar_ohlc, "candle_open"))
    cc = _float_or_none(_bar_value(bar_ohlc, "candle_close"))

    if co is None or cc is None:
        return SameBarConflictResult(
            resolution=SameBarResolution.CONSERVATIVE_STOP_FIRST,
            exit_reason="stop_hit",
            same_bar_resolution_rule="conservative_stop_first_missing_body",
        )

    if sig == "long":
        if cc >= co:
            return SameBarConflictResult(
                resolution=SameBarResolution.CANDLE_BODY_OPEN_CLOSE,
                exit_reason="stop_hit",
                same_bar_resolution_rule="bull_bar_assume_extreme_low_before_high_stop_priority",
            )
        return SameBarConflictResult(
            resolution=SameBarResolution.CANDLE_BODY_OPEN_CLOSE,
            exit_reason="target_hit",
            same_bar_resolution_rule="bear_bar_assume_extreme_high_before_low_target_priority",
        )

    if cc >= co:
        return SameBarConflictResult(
            resolution=SameBarResolution.CANDLE_BODY_OPEN_CLOSE,
            exit_reason="target_hit",
            same_bar_resolution_rule="bull_bar_assume_low_before_high_short_target_before_stop",
        )
    return SameBarConflictResult(
        resolution=SameBarResolution.CANDLE_BODY_OPEN_CLOSE,
        exit_reason="stop_hit",
        same_bar_resolution_rule="bear_bar_assume_high_before_low_short_stop_before_target",
    )


def fire_exit(
    *,
    signal: str,
    stop: float | None,
    target: float | None,
    forward_bars: Sequence[dict[str, Any]],
    max_hold_bars: int,
) -> ExitOutcome:
    sig = (signal or "").strip().lower()
    bars = list(forward_bars or [])[: max(1, int(max_hold_bars or 1))]
    if not bars:
        return _skip("no_exit_snapshot")
    if sig not in ("long", "short"):
        return _skip("invalid_call_signal_for_path")
    if stop is None or target is None:
        return _skip("missing_stop_target_for_exit")

    for idx, bar in enumerate(bars):
        hi = _float_or_none(_bar_value(bar, "candle_high"))
        lo = _float_or_none(_bar_value(bar, "candle_low"))
        if hi is None or lo is None:
            return _skip("missing_ohlc_forward_path")

        if sig == "long":
            stop_hit = lo <= float(stop)
            target_hit = hi >= float(target)
        else:
            stop_hit = hi >= float(stop)
            target_hit = lo <= float(target)

        if stop_hit and target_hit:
            resolution = resolve_same_bar_conflict(bar_ohlc=bar, stop=float(stop), target=float(target), signal=sig)
            return ExitOutcome(
                exit_reason=resolution.exit_reason,
                skip_reason=None,
                exit_bar_index=idx,
                same_bar_conflict=True,
                same_bar_resolution_rule=resolution.same_bar_resolution_rule,
            )
        if stop_hit:
            return ExitOutcome(
                exit_reason="stop_hit",
                skip_reason=None,
                exit_bar_index=idx,
                same_bar_conflict=False,
                same_bar_resolution_rule="",
            )
        if target_hit:
            return ExitOutcome(
                exit_reason="target_hit",
                skip_reason=None,
                exit_bar_index=idx,
                same_bar_conflict=False,
                same_bar_resolution_rule="",
            )

    return ExitOutcome(
        exit_reason="time_expiry",
        skip_reason=None,
        exit_bar_index=len(bars) - 1,
        same_bar_conflict=False,
        same_bar_resolution_rule="",
    )


def _skip(reason: str) -> ExitOutcome:
    return ExitOutcome(
        exit_reason=None,
        skip_reason=reason,
        exit_bar_index=None,
        same_bar_conflict=False,
        same_bar_resolution_rule="",
    )


def _cap_target(entry: float, target: float, direction: Direction, risk: float, max_rr: float) -> float:
    if direction == "long":
        return round(min(float(target), float(entry) + float(risk) * float(max_rr)), 2)
    return round(max(float(target), float(entry) - float(risk) * float(max_rr)), 2)


def _abs_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return abs(float(value))


def _bar_value(bar: dict[str, Any], key: str) -> Any:
    return bar.get(key)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None
