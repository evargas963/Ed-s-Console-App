"""Shared static lifecycle rule core for A2 advisory lifecycle work.

This module is intentionally consumer-free in Commit A: it defines the shared
threshold-derivation and exit-firing primitives that later commits can wire into
``realized_contract_eval.py`` and the in-scope geometry portions of
``call_engine.py``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, NamedTuple, Sequence




ExitReason = Literal["stop_hit", "target_hit", "time_expiry"]



class SameBarResolution(str, Enum):
    CANDLE_BODY_OPEN_CLOSE = "candle_body_open_close"
    CONSERVATIVE_STOP_FIRST = "conservative_stop_first"
    NO_CONFLICT = "no_conflict"






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
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)














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






def _bar_value(bar: dict[str, Any], key: str) -> Any:
    return bar.get(key)
