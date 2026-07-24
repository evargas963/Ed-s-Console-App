"""
Triple-barrier labeling (pilot v1): NEXT_BAR_OPEN_V1 entry, Wilder ATR-14 anchored at T-1.

Barrier width uses ATR at signal_bar_index - 1 so the signal bar's range does not scale stops/targets.

Costs are applied post-label only (realized_return_bp_post_cost).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

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
    # F1 v2 additive fields (defaults keep pilot-v1 constructors byte-compatible).
    cost_floor_binding: bool = False


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


# ═══════════════════════════════════════════════════════════════════════════════
# F1 v2 labeler (S2, 2026-07-23) — pilot v1 above is FROZEN under prereg_v1.json
# and stays byte-identical. v2 adds, per the approved F1 spec:
#   * calendar-aware force-flat via the S1 session authority (holiday / early
#     close / uncovered-year fail-closed) instead of a clock-only 15:55;
#   * the 1bp cost floor on barrier widths (flagged when binding);
#   * same-session exit guards — a missing force-flat/vertical bar is a
#     WITHHELD, never a silent exit at the NEXT session's open (the RC-31
#     class, latent in v1 and regression-documented in the S2 seam tests);
#   * signal→entry same-session requirement (a last-bar-of-day signal cannot
#     silently become an overnight-held entry at tomorrow's open);
#   * TIMEOUT/FORCE_FLAT exits at the first bar OPEN after the boundary (the
#     first available price), not that bar's close a minute later.
# ═══════════════════════════════════════════════════════════════════════════════

F1_COST_FLOOR_BP_DEFAULT = 1.0
FORCE_FLAT_BUFFER_MINS = 5


def _et_date_of(ts_utc: float) -> str:
    from time_et import et_date_str_from_ts_utc

    return et_date_str_from_ts_utc(float(ts_utc))


def force_flat_ts_utc_f1_v2(entry_ts_utc: float) -> float | None:
    """Force-flat instant for the entry's ET session: (session close − buffer).

    Uses the S1 calendar authority: 15:55 ET on a normal day, 12:55 ET on a
    13:00 early close, None (fail closed) on holidays and uncovered years.
    """
    from time_et import session_close_mins_for_et_date

    d = _et_date_of(entry_ts_utc)
    close_mins = session_close_mins_for_et_date(d)
    if close_mins is None:
        return None
    ff = int(close_mins) - FORCE_FLAT_BUFFER_MINS
    dt = datetime.fromtimestamp(float(entry_ts_utc), tz=timezone.utc).astimezone(_ET)
    return datetime(dt.year, dt.month, dt.day, ff // 60, ff % 60, 0, tzinfo=_ET).timestamp()


def _f1_withheld(
    reason: str,
    *,
    entry_ts_utc: float = float("nan"),
    entry_price: float = float("nan"),
    stop_price: float = float("nan"),
    target_price: float = float("nan"),
    vertical_ts_utc: float = float("nan"),
    t_exit_utc: float = float("nan"),
    barrier_hit: BarrierHit = "TIMEOUT",
    force_flat: bool = False,
    cost_floor_binding: bool = False,
) -> TripleBarrierResult:
    """Fail-closed v2 result: labels None, reason named, no fabricated values."""
    return TripleBarrierResult(
        entry_ts_utc=entry_ts_utc,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        vertical_ts_utc=vertical_ts_utc,
        t_exit_utc=t_exit_utc,
        barrier_hit=barrier_hit,
        label_conservative=None,
        label_reject=None,
        same_bar_ambiguous=False,
        force_flat=force_flat,
        realized_R=None,
        realized_return_bp=None,
        realized_return_bp_post_cost=None,
        withheld_reason=reason,
        cost_floor_binding=cost_floor_binding,
    )


def _f1_barrier_widths(
    entry: float, atr: float, stop_atr: float, target_atr: float, cost_floor_bp: float
) -> tuple[float, float, bool]:
    """(stop_width, target_width, floor_binding): k·ATR_{T-1} floored at the
    cost floor — a "win" smaller than the round trip cannot exist by construction."""
    floor_pts = entry * float(cost_floor_bp) / 10000.0
    stop_w = float(stop_atr) * float(atr)
    tgt_w = float(target_atr) * float(atr)
    binding = (stop_w < floor_pts) or (tgt_w < floor_pts)
    return max(stop_w, floor_pts), max(tgt_w, floor_pts), binding


@dataclass
class _F1Walk:
    reason: str | None
    hit: BarrierHit
    cons: LabelTri | None
    rej: LabelTri | Literal["REJECT"] | None
    ambig: bool
    t_exit: float
    exit_px: float
    force_flat: bool


def _f1_walk_barriers(
    bars: list[Bar1m],
    i_ent: int,
    entry_date: str,
    side: str,
    stop_p: float,
    tgt_p: float,
    ff_ts: float,
    sim_end_ts: float,
) -> _F1Walk:
    """Path walk with fail-closed session guards; exits price at first bar OPEN
    after a time boundary (the first available price, not that bar's close)."""
    nan = float("nan")
    for j in range(i_ent, len(bars)):
        b = bars[j]
        b_start = float(b.bar_start_ts_utc)
        if _et_date_of(b_start) != entry_date:
            # Same-session coverage ran out before any boundary resolved: the
            # exit bar is MISSING. Pilot v1 exited at the next session's open here.
            reason = (
                "force_flat_bar_missing_same_session"
                if sim_end_ts >= ff_ts
                else "vertical_exit_bar_missing_same_session"
            )
            return _F1Walk(reason, "TIMEOUT", None, None, False, nan, nan, False)
        if b_start >= ff_ts:
            return _F1Walk(None, "FORCE_FLAT", "TIMEOUT", "TIMEOUT", False, b_start, float(b.open), True)
        if b_start >= sim_end_ts:
            return _F1Walk(None, "TIMEOUT", "TIMEOUT", "TIMEOUT", False, b_start, float(b.open), False)
        checker = _same_bar_long_conservative if side == "LONG" else _same_bar_short_conservative
        hs, ht, both = checker(float(b.low), float(b.high), stop_p, tgt_p)
        if both:
            return _F1Walk(None, "LOSS", "LOSS", "REJECT", True, b_start, stop_p, False)
        if hs:
            return _F1Walk(None, "LOSS", "LOSS", "LOSS", False, b_start, stop_p, False)
        if ht:
            return _F1Walk(None, "WIN", "WIN", "WIN", False, b_start, tgt_p, False)
    return _F1Walk(
        "missing_path_data_before_vertical_or_force_flat", "TIMEOUT", None, None, False, nan, nan, False
    )


def _f1_entry_context(
    bars: list[Bar1m], atr_series: list[float | None], ev: PilotEvent
) -> TripleBarrierResult | tuple[int, float, float, str, float]:
    """Validate event → entry context, or a withheld result.

    Returns (i_ent, entry_price, entry_ts, entry_date, atr_T_minus_1) when the
    candidate is admissible. Fail-closed reasons: no next bar, ATR T−1 index /
    value unavailable, or a last-bar-of-day signal whose NEXT_BAR_OPEN would be
    TOMORROW's open — an overnight-held position an intraday strategy never takes.
    """
    i_sig = ev.signal_bar_index
    i_ent = i_sig + 1
    if i_ent >= len(bars):
        return _f1_withheld("no_next_bar_for_entry")
    i_atr = i_sig - 1
    if i_atr < 0:
        return _f1_withheld("atr_T_minus_1_index_unavailable")
    atr = atr_series[i_atr] if i_atr < len(atr_series) else None
    if atr is None or not (atr > 0):
        return _f1_withheld("atr_unavailable_at_T_minus_1")
    entry = float(bars[i_ent].open)
    entry_ts = float(bars[i_ent].bar_start_ts_utc)
    entry_date = _et_date_of(entry_ts)
    if entry_date != _et_date_of(float(bars[i_sig].bar_start_ts_utc)):
        return _f1_withheld("entry_crosses_session")
    return i_ent, entry, entry_ts, entry_date, float(atr)


def label_event_cell_f1_v2(
    bars: list[Bar1m],
    atr_series: list[float | None],
    ev: PilotEvent,
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_round_trip_bp: float,
    cost_floor_bp: float = F1_COST_FLOOR_BP_DEFAULT,
) -> TripleBarrierResult:
    """F1 triple-barrier labeling: NEXT_BAR_OPEN entry, ATR T−1 widths with a
    cost floor, calendar-aware FORCE_FLAT, fail-closed session guards."""
    ctx = _f1_entry_context(bars, atr_series, ev)
    if isinstance(ctx, TripleBarrierResult):
        return ctx
    i_ent, entry, entry_ts, entry_date, atr = ctx

    ff_ts = force_flat_ts_utc_f1_v2(entry_ts)
    if ff_ts is None:
        return _f1_withheld("no_session_for_entry_date")
    vert_ts = entry_ts + float(vertical_minutes) * 60.0
    if entry_ts >= ff_ts - 1e-6:
        return _f1_withheld(
            "entry_on_or_after_force_flat_window",
            entry_ts_utc=entry_ts,
            entry_price=entry,
            vertical_ts_utc=vert_ts,
            t_exit_utc=entry_ts,
            barrier_hit="FORCE_FLAT",
            force_flat=True,
        )

    stop_w, tgt_w, floor_binding = _f1_barrier_widths(entry, atr, stop_atr, target_atr, cost_floor_bp)
    side = ev.side
    stop_p = entry - stop_w if side == "LONG" else entry + stop_w
    tgt_p = entry + tgt_w if side == "LONG" else entry - tgt_w

    walk = _f1_walk_barriers(bars, i_ent, entry_date, side, stop_p, tgt_p, ff_ts, min(vert_ts, ff_ts))
    if walk.reason is not None or walk.cons is None:
        return _f1_withheld(
            walk.reason or "missing_path_data_before_vertical_or_force_flat",
            entry_ts_utc=entry_ts,
            entry_price=entry,
            stop_price=stop_p,
            target_price=tgt_p,
            vertical_ts_utc=vert_ts,
            cost_floor_binding=floor_binding,
        )

    exit_px = walk.exit_px
    r_r = _exit_r_long(entry, stop_p, exit_px) if side == "LONG" else _exit_r_short(entry, stop_p, exit_px)
    bp = ((exit_px - entry) if side == "LONG" else (entry - exit_px)) / max(entry, 1e-12) * 10000.0
    return TripleBarrierResult(
        entry_ts_utc=entry_ts,
        entry_price=entry,
        stop_price=stop_p,
        target_price=tgt_p,
        vertical_ts_utc=vert_ts,
        t_exit_utc=walk.t_exit,
        barrier_hit=walk.hit,
        label_conservative=walk.cons,
        label_reject=walk.rej,
        same_bar_ambiguous=walk.ambig,
        force_flat=walk.force_flat,
        realized_R=float(r_r),
        realized_return_bp=float(bp),
        realized_return_bp_post_cost=float(bp - cost_round_trip_bp),
        withheld_reason=None,
        cost_floor_binding=floor_binding,
    )
