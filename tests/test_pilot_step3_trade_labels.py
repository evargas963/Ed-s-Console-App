"""Lightweight tests for pilot_step3 trade-outcome labeling (no DB)."""

from __future__ import annotations

from datetime import datetime

import pytest  # noqa: F401 — used by approx in several tests

from app.domain.time_et import ET as _ET
def _b(start_et: str, o: float, h: float, lo: float, c: float):
    from research.pilot_step3.data_loader import Bar1m

    dt = datetime.strptime(start_et, "%Y-%m-%d %H:%M").replace(tzinfo=_ET)
    ts = dt.timestamp()
    return Bar1m(ts, ts + 60.0, o, h, lo, c, 1.0)


def test_wilder_atr_non_null_after_warmup():
    from research.pilot_step3.atr import wilder_atr_14

    n = 30
    h = [100.0 + i * 0.1 for i in range(n)]
    l = [99.5 + i * 0.1 for i in range(n)]
    c = [99.8 + i * 0.1 for i in range(n)]
    atr = wilder_atr_14(h, l, c, period=14)
    assert atr[14] is not None
    assert atr[14] > 0


def test_next_bar_open_entry_price():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [
        Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100 + i * 0.01, 101 + i * 0.01, 99.5 + i * 0.01, 100.5 + i * 0.01, 1.0)
        for i in range(80)
    ]
    atr = build_atr_series(bars)
    sig = 15
    ev = PilotEvent("e1", sig, bars[sig].bar_end_ts_utc, "LONG", 1.0, 0.0, 0.0, 0.0, 0.0, "gen")
    r = label_event_cell(bars, atr, ev, stop_atr=5.0, target_atr=5.0, vertical_minutes=15, cost_round_trip_bp=1.0)
    assert r.withheld_reason is None
    assert r.entry_price == pytest.approx(bars[sig + 1].open)


def test_long_geometry_target_hit_win():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars: list[Bar1m] = []
    for i in range(25):
        bars.append(
            Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100.0, 100.5, 99.8, 100.1 + i * 0.05, 1.0)
        )
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 15, bars[15].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=0.5, target_atr=0.5, vertical_minutes=120, cost_round_trip_bp=1.0)
    assert r.label_conservative in ("WIN", "LOSS", "TIMEOUT")


def test_short_geometry():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [
        Bar1m(t0 + i * 60, t0 + i * 60 + 60, 102.0 - i * 0.3, 102.5 - i * 0.3, 101.5 - i * 0.3, 102.0 - i * 0.3, 1.0)
        for i in range(25)
    ]
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 15, bars[15].bar_end_ts_utc, "SHORT", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=0.75, target_atr=1.0, vertical_minutes=120, cost_round_trip_bp=1.0)
    assert r.label_conservative in ("WIN", "LOSS", "TIMEOUT")


def test_same_bar_conservative_long_and_reject():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100, 100.2, 99.9, 100.05, 1.0) for i in range(30)]
    # Signal at 15 → ATR anchor T-1 is index 14 (first non-null Wilder slot). Ambiguous bar is entry bar 16.
    bars[16] = Bar1m(bars[16].bar_start_ts_utc, bars[16].bar_end_ts_utc, 100.0, 110.0, 90.0, 100.0, 1.0)
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 15, bars[15].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=0.5, target_atr=0.5, vertical_minutes=120, cost_round_trip_bp=1.0)
    assert r.same_bar_ambiguous is True
    assert r.label_conservative == "LOSS"
    assert r.label_reject == "REJECT"


def test_force_flat_sets_barrier_audit():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 15, 52, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100, 101, 99, 100.0, 1.0) for i in range(8)]
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 2, bars[2].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=10.0, target_atr=10.0, vertical_minutes=60, cost_round_trip_bp=1.0)
    if r.barrier_hit == "FORCE_FLAT":
        assert r.force_flat is True
        assert r.label_conservative == "TIMEOUT"


def test_missing_path_withheld():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100, 101, 99, 100.2, 1.0) for i in range(18)]
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 16, bars[16].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=50.0, target_atr=500.0, vertical_minutes=120, cost_round_trip_bp=1.0)
    assert r.withheld_reason == "missing_path_data_before_vertical_or_force_flat"


def test_cost_does_not_change_label_classification():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100 + i * 0.5, 101 + i * 0.5, 99, 100 + i * 0.5, 1.0) for i in range(25)]
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 13, bars[13].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    a = label_event_cell(bars, atr, ev, stop_atr=1.0, target_atr=2.0, vertical_minutes=60, cost_round_trip_bp=0.0)
    b = label_event_cell(bars, atr, ev, stop_atr=1.0, target_atr=2.0, vertical_minutes=60, cost_round_trip_bp=50.0)
    assert a.label_conservative == b.label_conservative


def test_signal_bar_leakage_entry_uses_next_bar():
    """ATR anchored at T-1; entry is next open — entry bar index = signal + 1."""
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100, 101, 99, 100.0 + i * 0.01, 1.0) for i in range(22)]
    atr = build_atr_series(bars)
    sig = 10
    ev = PilotEvent("e", sig, bars[sig].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=2.0, target_atr=3.0, vertical_minutes=30, cost_round_trip_bp=1.0)
    if r.withheld_reason is None:
        assert r.entry_price == pytest.approx(bars[sig + 1].open)


def test_atr_T_minus_1_signal_bar_range_does_not_change_barriers():
    """Stop/target width uses ATR[T-1]; widening signal bar T alone must not move barriers."""
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    base = [
        Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100.0 + i * 0.02, 100.5 + i * 0.02, 99.5 + i * 0.02, 100.1 + i * 0.02, 1.0)
        for i in range(20)
    ]
    tail = []
    o = 100.5
    for j in range(130):
        ts = t0 + (21 + j) * 60
        c = o + 0.05 * j
        tail.append(Bar1m(ts, ts + 60.0, o, c + 0.2, o - 0.2, c, 1.0))
        o = c
    wide_sig = Bar1m(t0 + 20 * 60, t0 + 21 * 60, 100.4, 500.0, 1.0, 100.4, 1.0)
    tight_sig = Bar1m(t0 + 20 * 60, t0 + 21 * 60, 100.4, 100.8, 100.0, 100.4, 1.0)
    bars_a = base + [wide_sig] + tail
    bars_b = base + [tight_sig] + tail
    atr_a = build_atr_series(bars_a)
    atr_b = build_atr_series(bars_b)
    assert atr_a[19] is not None and atr_b[19] is not None
    assert atr_a[19] == pytest.approx(atr_b[19], rel=1e-9, abs=1e-9)
    assert atr_a[20] is not None and atr_b[20] is not None
    assert abs(float(atr_a[20]) - float(atr_b[20])) > 0.01

    sig = 20
    ev = PilotEvent("e", sig, bars_a[sig].bar_end_ts_utc, "LONG", 1.0, 0.5, 0.0, 0.0, 0.0, "g")
    ra = label_event_cell(bars_a, atr_a, ev, stop_atr=1.0, target_atr=2.0, vertical_minutes=120, cost_round_trip_bp=0.0)
    rb = label_event_cell(bars_b, atr_b, ev, stop_atr=1.0, target_atr=2.0, vertical_minutes=120, cost_round_trip_bp=0.0)
    assert ra.withheld_reason is None and rb.withheld_reason is None
    assert ra.stop_price == pytest.approx(rb.stop_price)
    assert ra.target_price == pytest.approx(rb.target_price)


def test_atr_T_minus_1_withheld_when_no_prior_bar():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.labeling import build_atr_series, label_event_cell
    from research.pilot_step3.event_generation import PilotEvent

    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=_ET).timestamp()
    bars = [Bar1m(t0 + i * 60, t0 + i * 60 + 60, 100, 101, 99, 100.0, 1.0) for i in range(5)]
    atr = build_atr_series(bars)
    ev = PilotEvent("e", 0, bars[0].bar_end_ts_utc, "LONG", 1, 0, 0, 0, 0, "g")
    r = label_event_cell(bars, atr, ev, stop_atr=1.0, target_atr=2.0, vertical_minutes=30, cost_round_trip_bp=0.0)
    assert r.withheld_reason == "atr_T_minus_1_index_unavailable"
