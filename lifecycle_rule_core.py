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
T1_FALLBACK_R_MULTIPLE = 2.0
T2_OFFSET_R_MULTIPLE = 1.0


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


def _float_or_none(value: Any) -> float | None:
    from app.domain.numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def apply_time_decay(distance_pct: float, mins_elapsed_since_open: float | None) -> float:
    mins_f = _float_or_none(mins_elapsed_since_open)
    mins = max(0.0, mins_f if mins_f is not None else 0.0)
    base = _float_or_none(distance_pct)
    if base is None:
        base = STOP_BASE_PCT
    return base - (mins / 60.0) * STOP_TIME_DECAY_PCT


def apply_vix_adjustment(distance_pct: float, vix_level: float | None) -> float:
    base = _float_or_none(distance_pct)
    if base is None:
        base = STOP_BASE_PCT
    if vix_level is None:
        return base
    vix = _float_or_none(vix_level)
    if vix is None:
        return base
    if vix > 30:
        return base + STOP_VIX_HIGH_PCT
    if vix > 20:
        return base + STOP_VIX_MED_PCT
    return base


def apply_risk_multiplier(distance_pct: float, risk_multiplier: float | None) -> float:
    base = _float_or_none(distance_pct)
    if base is None:
        base = STOP_BASE_PCT
    mult = _float_or_none(risk_multiplier)
    if mult is None or mult == 0.0:
        mult = 1.0
    else:
        mult = max(0.8, min(1.5, mult))
    return base * mult


def derive_stop_distance_pct(
    *,
    spot: float,
    vix_level: float | None,
    mins_elapsed_since_open: float | None,
    risk_multiplier: float | None,
) -> StopDistance:
    """Derive final stop percentage using call_engine's current order."""
    _ = _float_or_none(spot)  # API parity; non-finite spot does not affect stop % math today.
    adjustments: list[str] = []
    pct = STOP_BASE_PCT

    pct = apply_time_decay(pct, mins_elapsed_since_open)
    mins_f = _float_or_none(mins_elapsed_since_open)
    if mins_f is not None and mins_f > 0:
        adjustments.append("time_decay")

    before_vix = pct
    vix_f = _float_or_none(vix_level) if vix_level is not None else None
    if vix_level is not None and vix_f is None:
        adjustments.append("vix_unavailable")
    else:
        pct = apply_vix_adjustment(pct, vix_f)
        if pct != before_vix and vix_f is not None:
            adjustments.append("vix_high" if vix_f > 30 else "vix_medium")

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
    """Snap to the nearest eligible structural level within 1.5 risk units."""
    target = _float_or_none(target_price)
    if target is None:
        raise ValueError("target_price must be finite")
    risk_f = _float_or_none(risk)
    if risk_f is None:
        raise ValueError("risk must be finite")
    snap_range = risk_f * 1.5
    candidates: list[float] = []
    for level in structural_levels:
        if level is None:
            continue
        lf = _float_or_none(level)
        if lf is None:
            continue
        if direction == "long" and lf > target - snap_range:
            candidates.append(lf)
        elif direction == "short" and lf < target + snap_range:
            candidates.append(lf)
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
    """Derive T1/T2 using call_engine's current R/R and horizon rules."""
    entry_f = _float_or_none(entry)
    risk_f = _float_or_none(risk)
    if entry_f is None:
        raise ValueError("entry must be finite")
    if risk_f is None or risk_f <= 0:
        raise ValueError("risk must be positive absolute dollar risk")
    sign = 1.0 if direction == "long" else -1.0

    avg5_abs = _abs_or_none(avg5)
    avg15_abs = _abs_or_none(avg15)
    avg60_abs = _abs_or_none(avg60)

    if avg5_abs is not None and avg5_abs > risk_f * MIN_RR:
        target_raw = entry_f + sign * min(avg5_abs, risk_f * MAX_RR_T1)
        target_source = "5c_avg_move"
    else:
        target_raw = entry_f + sign * risk_f * T1_FALLBACK_R_MULTIPLE
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
        target2_raw = target + sign * risk_f * T2_OFFSET_R_MULTIPLE
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
    _mhb_f = _float_or_none(max_hold_bars)
    _mhb_int = int(_mhb_f) if _mhb_f is not None and _mhb_f >= 1 else 1
    bars = list(forward_bars or [])[: max(1, _mhb_int)]
    if not bars:
        return _skip("no_exit_snapshot")
    if sig not in ("long", "short"):
        return _skip("invalid_call_signal_for_path")
    if stop is None or target is None:
        return _skip("missing_stop_target_for_exit")
    stop_f = _float_or_none(stop)
    target_f = _float_or_none(target)
    if stop_f is None or target_f is None:
        return _skip("missing_stop_target_for_exit")

    for idx, bar in enumerate(bars):
        hi = _float_or_none(_bar_value(bar, "candle_high"))
        lo = _float_or_none(_bar_value(bar, "candle_low"))
        if hi is None or lo is None:
            return _skip("missing_ohlc_forward_path")

        if sig == "long":
            stop_hit = lo <= stop_f
            target_hit = hi >= target_f
        else:
            stop_hit = hi >= stop_f
            target_hit = lo <= target_f

        if stop_hit and target_hit:
            resolution = resolve_same_bar_conflict(
                bar_ohlc=bar, stop=stop_f, target=target_f, signal=sig
            )
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
    entry_f = _float_or_none(entry)
    target_f = _float_or_none(target)
    risk_f = _float_or_none(risk)
    max_rr_f = _float_or_none(max_rr)
    if entry_f is None or target_f is None or risk_f is None or max_rr_f is None:
        raise ValueError("cap_target inputs must be finite")
    if direction == "long":
        return round(min(target_f, entry_f + risk_f * max_rr_f), 2)
    return round(max(target_f, entry_f - risk_f * max_rr_f), 2)


def _abs_or_none(value: float | None) -> float | None:
    x = _float_or_none(value)
    if x is None:
        return None
    return abs(x)


def _bar_value(bar: dict[str, Any], key: str) -> Any:
    return bar.get(key)
