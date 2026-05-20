"""
Triple-barrier labeling (pilot v1): NEXT_BAR_OPEN_V1 entry, Wilder ATR-14 anchored at T-1.

Barrier width uses ATR at signal_bar_index - 1 so the signal bar's range does not scale stops/targets.

Costs are applied post-label only (realized_return_bp_post_cost).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from time_et import ET as _ET

from .atr import wilder_atr_14
from .data_loader import Bar1m
from .event_generation import PilotEvent

BarrierHit = Literal["WIN", "LOSS", "TIMEOUT", "FORCE_FLAT"]
LabelTri = Literal["WIN", "LOSS", "TIMEOUT"]


def force_flat_open_ts_utc(entry_ts_utc: float) -> float:
    """15:55 ET on same calendar day as entry (RTH close minus five minutes bar start)."""
    dt = datetime.fromtimestamp(float(entry_ts_utc), tz=timezone.utc).astimezone(_ET)
    t955 = datetime(dt.year, dt.month, dt.day, 15, 55, 0, tzinfo=_ET).timestamp()
    return float(t955)


@dataclass
class TripleBarrierResult:
    entry_ts_utc: float
    entry_price: float
    stop_price: float
    target_price: float
    vertical_ts_utc: float
    t_exit_utc: float
    barrier_hit: BarrierHit
    label_conservative: LabelTri | None
    label_reject: LabelTri | Literal["REJECT"] | None
    same_bar_ambiguous: bool
    force_flat: bool
    realized_R: float | None
    realized_return_bp: float | None
    realized_return_bp_post_cost: float | None
    withheld_reason: str | None = None


def _same_bar_long_conservative(low: float, high: float, stop: float, target: float) -> tuple[bool, bool, bool]:
    """Returns (hit_stop, hit_target, both)."""
    hit_stop = low <= stop
    hit_tgt = high >= target
    return hit_stop, hit_tgt, hit_stop and hit_tgt


def _same_bar_short_conservative(low: float, high: float, stop: float, target: float) -> tuple[bool, bool, bool]:
    hit_stop = high >= stop
    hit_tgt = low <= target
    return hit_stop, hit_tgt, hit_stop and hit_tgt


def _exit_r_long(entry: float, stop: float, exit_px: float) -> float:
    risk = max(entry - stop, 1e-9)
    return (exit_px - entry) / risk


def _exit_r_short(entry: float, stop: float, exit_px: float) -> float:
    risk = max(stop - entry, 1e-9)
    return (entry - exit_px) / risk


def label_event_cell(
    bars: list[Bar1m],
    atr_series: list[float | None],
    ev: PilotEvent,
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_round_trip_bp: float,
) -> TripleBarrierResult:
    """
    Simulate from NEXT_BAR_OPEN after signal bar ev.signal_bar_index.
    """
    i_sig = ev.signal_bar_index
    i_ent = i_sig + 1
    if i_ent >= len(bars):
        return TripleBarrierResult(
            entry_ts_utc=float("nan"),
            entry_price=float("nan"),
            stop_price=float("nan"),
            target_price=float("nan"),
            vertical_ts_utc=float("nan"),
            t_exit_utc=float("nan"),
            barrier_hit="TIMEOUT",
            label_conservative=None,
            label_reject=None,
            same_bar_ambiguous=False,
            force_flat=False,
            realized_R=None,
            realized_return_bp=None,
            realized_return_bp_post_cost=None,
            withheld_reason="no_next_bar_for_entry",
        )

    i_atr = i_sig - 1
    if i_atr < 0:
        return TripleBarrierResult(
            entry_ts_utc=float("nan"),
            entry_price=float("nan"),
            stop_price=float("nan"),
            target_price=float("nan"),
            vertical_ts_utc=float("nan"),
            t_exit_utc=float("nan"),
            barrier_hit="TIMEOUT",
            label_conservative=None,
            label_reject=None,
            same_bar_ambiguous=False,
            force_flat=False,
            realized_R=None,
            realized_return_bp=None,
            realized_return_bp_post_cost=None,
            withheld_reason="atr_T_minus_1_index_unavailable",
        )

    atr = atr_series[i_atr] if i_atr < len(atr_series) else None
    if atr is None or atr <= 0 or not (atr > 0):
        return TripleBarrierResult(
            entry_ts_utc=float("nan"),
            entry_price=float("nan"),
            stop_price=float("nan"),
            target_price=float("nan"),
            vertical_ts_utc=float("nan"),
            t_exit_utc=float("nan"),
            barrier_hit="TIMEOUT",
            label_conservative=None,
            label_reject=None,
            same_bar_ambiguous=False,
            force_flat=False,
            realized_R=None,
            realized_return_bp=None,
            realized_return_bp_post_cost=None,
            withheld_reason="atr_unavailable_at_T_minus_1",
        )

    entry = float(bars[i_ent].open)
    entry_ts = float(bars[i_ent].bar_start_ts_utc)
    ff_ts = force_flat_open_ts_utc(entry_ts)
    vert_ts = entry_ts + float(vertical_minutes) * 60.0
    sim_end_ts = min(vert_ts, ff_ts)

    if entry_ts >= ff_ts - 1e-6:
        return TripleBarrierResult(
            entry_ts_utc=entry_ts,
            entry_price=entry,
            stop_price=float("nan"),
            target_price=float("nan"),
            vertical_ts_utc=vert_ts,
            t_exit_utc=entry_ts,
            barrier_hit="FORCE_FLAT",
            label_conservative=None,
            label_reject=None,
            same_bar_ambiguous=False,
            force_flat=True,
            realized_R=None,
            realized_return_bp=None,
            realized_return_bp_post_cost=None,
            withheld_reason="entry_on_or_after_force_flat_window",
        )

    side = ev.side
    if side == "LONG":
        stop_p = entry - stop_atr * atr
        tgt_p = entry + target_atr * atr
    else:
        stop_p = entry + stop_atr * atr
        tgt_p = entry - target_atr * atr

    ambig = False
    cons: LabelTri | None = None
    rej: LabelTri | Literal["REJECT"] | None = None
    hit: BarrierHit = "TIMEOUT"
    t_exit = entry_ts
    exit_px = entry
    force_flat = False

    j = i_ent
    while j < len(bars):
        b = bars[j]
        if b.bar_start_ts_utc >= ff_ts:
            hit = "FORCE_FLAT"
            t_exit = float(b.bar_start_ts_utc)
            exit_px = float(b.open)
            force_flat = True
            cons = "TIMEOUT"
            rej = "TIMEOUT"
            break
        if b.bar_start_ts_utc >= sim_end_ts:
            hit = "TIMEOUT"
            t_exit = float(b.bar_start_ts_utc)
            exit_px = float(b.close)
            cons = "TIMEOUT"
            rej = "TIMEOUT"
            break

        lo, hi = float(b.low), float(b.high)
        if side == "LONG":
            hs, ht, both = _same_bar_long_conservative(lo, hi, stop_p, tgt_p)
            if both:
                ambig = True
                cons = "LOSS"
                rej = "REJECT"
                hit = "LOSS"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = stop_p
                break
            if hs:
                cons = rej = "LOSS"
                hit = "LOSS"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = stop_p
                break
            if ht:
                cons = rej = "WIN"
                hit = "WIN"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = tgt_p
                break
        else:
            hs, ht, both = _same_bar_short_conservative(lo, hi, stop_p, tgt_p)
            if both:
                ambig = True
                cons = "LOSS"
                rej = "REJECT"
                hit = "LOSS"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = stop_p
                break
            if hs:
                cons = rej = "LOSS"
                hit = "LOSS"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = stop_p
                break
            if ht:
                cons = rej = "WIN"
                hit = "WIN"
                t_exit = float(b.bar_start_ts_utc)
                exit_px = tgt_p
                break
        j += 1

    if cons is None:
        return TripleBarrierResult(
            entry_ts_utc=entry_ts,
            entry_price=entry,
            stop_price=stop_p,
            target_price=tgt_p,
            vertical_ts_utc=vert_ts,
            t_exit_utc=float(bars[-1].bar_end_ts_utc),
            barrier_hit="TIMEOUT",
            label_conservative=None,
            label_reject=None,
            same_bar_ambiguous=False,
            force_flat=False,
            realized_R=None,
            realized_return_bp=None,
            realized_return_bp_post_cost=None,
            withheld_reason="missing_path_data_before_vertical_or_force_flat",
        )

    r_r = _exit_r_long(entry, stop_p, exit_px) if side == "LONG" else _exit_r_short(entry, stop_p, exit_px)
    if side == "LONG":
        bp = (exit_px - entry) / max(entry, 1e-12) * 10000.0
    else:
        bp = (entry - exit_px) / max(entry, 1e-12) * 10000.0
    bp_post = bp - cost_round_trip_bp

    return TripleBarrierResult(
        entry_ts_utc=entry_ts,
        entry_price=entry,
        stop_price=stop_p,
        target_price=tgt_p,
        vertical_ts_utc=vert_ts,
        t_exit_utc=t_exit,
        barrier_hit=hit,
        label_conservative=cons,
        label_reject=rej,
        same_bar_ambiguous=ambig,
        force_flat=force_flat,
        realized_R=float(r_r),
        realized_return_bp=float(bp),
        realized_return_bp_post_cost=float(bp_post),
        withheld_reason=None,
    )


def build_atr_series(bars: list[Bar1m]) -> list[float | None]:
    h = [b.high for b in bars]
    lo = [b.low for b in bars]
    c = [b.close for b in bars]
    return wilder_atr_14(h, lo, c, period=14)
