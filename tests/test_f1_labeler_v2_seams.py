"""F1 S2 seam tests — label_event_cell_f1_v2 (drives the REAL labeler).

Locks the approved F1 spec: ATR T−1 anchor immunity, 1bp cost floor binding,
calendar-aware FORCE_FLAT (normal day 15:55 ET, early close 12:55 ET, holiday
withheld), fail-closed same-session exits (regression-documents that pilot v1
silently exits at the NEXT session's open when force-flat bars are missing),
signal→entry same-session rule, and first-open-after-boundary exit prices.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from research.pilot_step3.event_generation import PilotEvent
from research.pilot_step3.data_loader import Bar1m
from research.pilot_step3.labeling import (
    build_atr_series,
    force_flat_ts_utc_f1_v2,
    label_event_cell,
    label_event_cell_f1_v2,
)

ET = ZoneInfo("America/New_York")


def _mk_bars(date_ymd, start_hm, n, *, price=680.0, rng=0.2, step=0.0):
    y, mo, d = date_ymd
    h, mi = start_hm
    t0 = datetime(y, mo, d, h, mi, tzinfo=ET)
    out = []
    px = price
    for i in range(n):
        s = (t0 + timedelta(minutes=i)).timestamp()
        out.append(
            Bar1m(
                bar_start_ts_utc=s,
                bar_end_ts_utc=s + 60.0,
                open=px,
                high=px + rng,
                low=px - rng,
                close=px + step,
                volume=100.0,
            )
        )
        px += step
    return out


def _ev(i_sig, side="LONG"):
    return PilotEvent(
        event_id=f"seam-{i_sig}",
        signal_bar_index=i_sig,
        T_close_ts_utc=0.0,
        side=side,
        sma_fast=0.0,
        sma_slow=0.0,
        cusum_pos=0.0,
        cusum_neg=0.0,
        z_trigger=0.0,
        candidate_generator_id="seam_fixture",
    )


def _label_v2(bars, i_sig, *, stop_atr=1.5, target_atr=1.5, vertical=60, side="LONG", floor_bp=1.0):
    return label_event_cell_f1_v2(
        bars,
        build_atr_series(bars),
        _ev(i_sig, side),
        stop_atr=stop_atr,
        target_atr=target_atr,
        vertical_minutes=vertical,
        cost_round_trip_bp=1.0,
        cost_floor_bp=floor_bp,
    )


def test_atr_t_minus_1_anchor_immune_to_signal_bar_range():
    bars = _mk_bars((2026, 7, 22), (10, 0), 40)
    base = _label_v2(bars, 20)
    mutated = [Bar1m(b.bar_start_ts_utc, b.bar_end_ts_utc, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    mutated[20] = Bar1m(
        bars[20].bar_start_ts_utc, bars[20].bar_end_ts_utc,
        bars[20].open, bars[20].high + 50.0, bars[20].low - 50.0, bars[20].close, bars[20].volume,
    )
    after = _label_v2(mutated, 20)
    assert after.stop_price == base.stop_price
    assert after.target_price == base.target_price


def test_force_flat_resolves_same_day_never_next_session():
    day = _mk_bars((2026, 7, 22), (15, 30), 30)          # 15:30..15:59
    nxt = _mk_bars((2026, 7, 23), (9, 30), 10, price=600.0)  # tomorrow, far-away prices
    bars = day + nxt
    r = _label_v2(bars, 20, stop_atr=50, target_atr=50, vertical=120)  # signal 15:50, entry 15:51
    assert r.withheld_reason is None
    assert r.barrier_hit == "FORCE_FLAT"
    ff = force_flat_ts_utc_f1_v2(r.entry_ts_utc)
    assert r.t_exit_utc >= ff
    exit_dt = datetime.fromtimestamp(r.t_exit_utc, tz=ET)
    assert (exit_dt.year, exit_dt.month, exit_dt.day) == (2026, 7, 22)
    assert abs(r.entry_price - 680.0) < 5.0  # exit priced off same-day tape, not tomorrow's 600


def test_missing_force_flat_bars_fail_closed_while_v1_exits_next_session():
    day = _mk_bars((2026, 7, 22), (15, 30), 20)              # ends 15:49 — no 15:55 bar
    nxt = _mk_bars((2026, 7, 23), (9, 30), 10, price=600.0)
    bars = day + nxt
    atr = build_atr_series(bars)
    kw = dict(stop_atr=50, target_atr=50, vertical_minutes=120, cost_round_trip_bp=1.0)
    v2 = label_event_cell_f1_v2(bars, atr, _ev(17), **kw)
    assert v2.withheld_reason == "force_flat_bar_missing_same_session"
    # Regression documentation: pilot v1 walks into TOMORROW's open here.
    v1 = label_event_cell(bars, atr, _ev(17), **kw)
    assert v1.barrier_hit == "FORCE_FLAT" and v1.withheld_reason is None
    v1_exit_dt = datetime.fromtimestamp(v1.t_exit_utc, tz=ET)
    assert (v1_exit_dt.year, v1_exit_dt.month, v1_exit_dt.day) == (2026, 7, 23)


def test_cost_floor_binds_when_atr_compresses():
    tight = _mk_bars((2026, 7, 22), (10, 0), 40, rng=0.001)   # ATR ~0.002 pts
    r = _label_v2(tight, 20, stop_atr=1.5, target_atr=1.5, vertical=5)
    assert r.cost_floor_binding is True
    floor_pts = r.entry_price * 1.0 / 10000.0
    assert abs((r.entry_price - r.stop_price) - floor_pts) < 1e-9
    assert abs((r.target_price - r.entry_price) - floor_pts) < 1e-9
    wide = _mk_bars((2026, 7, 22), (10, 0), 40, rng=1.0)      # ATR ~2 pts >> floor
    r2 = _label_v2(wide, 20, stop_atr=1.5, target_atr=1.5, vertical=5)
    assert r2.cost_floor_binding is False
    assert (r2.entry_price - r2.stop_price) > floor_pts * 10


def test_early_close_day_force_flats_at_1255_et():
    day = _mk_bars((2026, 11, 27), (12, 30), 30)  # bars run past the 13:00 close on purpose
    r = _label_v2(day, 20, stop_atr=50, target_atr=50, vertical=120)  # signal 12:50, entry 12:51
    assert r.withheld_reason is None
    assert r.barrier_hit == "FORCE_FLAT"
    exit_dt = datetime.fromtimestamp(r.t_exit_utc, tz=ET)
    assert (exit_dt.hour, exit_dt.minute) >= (12, 55)
    assert (exit_dt.hour, exit_dt.minute) < (13, 0)


def test_holiday_entry_is_withheld():
    day = _mk_bars((2026, 5, 25), (10, 0), 40)  # Memorial Day rows CAN exist in data
    r = _label_v2(day, 20)
    assert r.withheld_reason == "no_session_for_entry_date"


def test_last_bar_of_day_signal_cannot_become_overnight_entry():
    day = _mk_bars((2026, 7, 22), (15, 30), 30)              # signal at index 29 = 15:59
    nxt = _mk_bars((2026, 7, 23), (9, 30), 10)
    r = _label_v2(day + nxt, 29)
    assert r.withheld_reason == "entry_crosses_session"


def test_timeout_exits_at_first_bar_open_after_vertical():
    bars = _mk_bars((2026, 7, 22), (10, 0), 40)
    r = _label_v2(bars, 20, stop_atr=50, target_atr=50, vertical=5)  # entry 10:21, vertical 10:26
    assert r.barrier_hit == "TIMEOUT" and r.withheld_reason is None
    exit_dt = datetime.fromtimestamp(r.t_exit_utc, tz=ET)
    assert (exit_dt.hour, exit_dt.minute) == (10, 26)
    idx = next(i for i, b in enumerate(bars) if b.bar_start_ts_utc == r.t_exit_utc)
    assert r.realized_return_bp is not None
    assert abs((bars[idx].open - r.entry_price) / r.entry_price * 10000.0 - r.realized_return_bp) < 1e-9


def test_win_and_loss_paths_still_resolve():
    up = _mk_bars((2026, 7, 22), (10, 0), 60, rng=0.2, step=0.3)  # steady climb
    r = _label_v2(up, 20, stop_atr=3.0, target_atr=1.0, vertical=30)
    assert r.barrier_hit == "WIN" and r.label_conservative == "WIN"
    down = _mk_bars((2026, 7, 22), (10, 0), 60, rng=0.2, step=-0.3)
    r2 = _label_v2(down, 20, stop_atr=1.0, target_atr=3.0, vertical=30)
    assert r2.barrier_hit == "LOSS" and r2.label_conservative == "LOSS"
