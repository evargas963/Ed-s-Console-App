"""F1 S4 — consolidated battery: DST end-to-end, placebo isolation, gate wrapping.

Everything drives the REAL gated pipeline (S3 gates → S2 labeler → S1 calendar).

DST proof strategy: the 2026-03-08 spring-forward happens Sunday 02:00 ET when
no session exists, so no intraday candidate can contain the shift. The proof is
therefore three-part: (a) force-flat instants pin to 15:55 ET on BOTH sides of
the transition while their UTC offsets differ by exactly the DST hour; (b) the
vertical barrier is pure UTC arithmetic on both sides (no false timeouts, no
stretched bounds); (c) a pre-transition candidate whose vertical would span the
weekend is FORCE_FLAT'd on Friday — the shift is structurally unreachable.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from research.pilot_step3.data_loader import Bar1m
from research.pilot_step3.event_generation import PilotEvent
from research.pilot_step3.f1_input_gates import (
    gated_label_event_cell_f1,
    placebo_shuffle_train_only,
    run_gated_battery,
)
from research.pilot_step3.labeling import build_atr_series, force_flat_ts_utc_f1_v2

ET = ZoneInfo("America/New_York")
REAL = "schwab_1m_accumulator_sqlite"
_KW = dict(stop_atr=50.0, target_atr=50.0, vertical_minutes=5, cost_round_trip_bp=1.0)


def _mk_day(date_ymd, start_hm, n, *, source=REAL, price=680.0, rng=0.2):
    y, mo, d = date_ymd
    h, mi = start_hm
    t0 = datetime(y, mo, d, h, mi, tzinfo=ET)
    out = []
    for i in range(n):
        s = (t0 + timedelta(minutes=i)).timestamp()
        out.append(
            Bar1m(s, s + 60.0, price, price + rng, price - rng, price, 100.0, source)
        )
    return out


def _ev(i_sig, side="LONG"):
    return PilotEvent(
        event_id=f"s4-{i_sig}",
        signal_bar_index=i_sig,
        T_close_ts_utc=0.0,
        side=side,
        sma_fast=0.0,
        sma_slow=0.0,
        cusum_pos=0.0,
        cusum_neg=0.0,
        z_trigger=0.0,
        candidate_generator_id="s4_fixture",
    )


# ── 1. DST end-to-end resilience ─────────────────────────────────────────────


def test_force_flat_pins_to_et_across_the_dst_shift():
    """15:55 ET both sides; UTC instants differ by exactly 3 days minus the DST hour."""
    fri_entry = datetime(2026, 3, 6, 10, 21, tzinfo=ET).timestamp()   # EST (UTC-5)
    mon_entry = datetime(2026, 3, 9, 10, 21, tzinfo=ET).timestamp()   # EDT (UTC-4)
    ff_fri = force_flat_ts_utc_f1_v2(fri_entry)
    ff_mon = force_flat_ts_utc_f1_v2(mon_entry)
    assert ff_fri is not None and ff_mon is not None
    for ff in (ff_fri, ff_mon):
        dt = datetime.fromtimestamp(ff, tz=ET)
        assert (dt.hour, dt.minute) == (15, 55)
    assert (ff_mon - ff_fri) == 3 * 86400.0 - 3600.0  # the missing DST hour, exactly


def test_vertical_barrier_exact_on_both_sides_of_transition():
    """Same fixture shape on EST Friday and EDT Monday → identical relative
    outcomes: TIMEOUT at exactly entry + vertical seconds, end-to-end through gates."""
    for date_ymd in ((2026, 3, 6), (2026, 3, 9)):
        bars = _mk_day(date_ymd, (10, 0), 40)
        r = gated_label_event_cell_f1(bars, build_atr_series(bars), _ev(20), **_KW)
        assert r.withheld_reason is None
        assert r.barrier_hit == "TIMEOUT"
        assert r.vertical_ts_utc == r.entry_ts_utc + 5 * 60.0        # pure UTC arithmetic
        assert r.t_exit_utc == r.entry_ts_utc + 5 * 60.0             # no false timeout drift
        exit_dt = datetime.fromtimestamp(r.t_exit_utc, tz=ET)
        assert (exit_dt.hour, exit_dt.minute) == (10, 26)            # ET clock agrees


def test_transition_weekend_is_structurally_unreachable():
    """A Friday candidate whose vertical would span the DST weekend force-flats
    on Friday — the shift can never sit inside a barrier window."""
    fri = _mk_day((2026, 3, 6), (15, 30), 30)                        # 15:30..15:59 EST
    mon = _mk_day((2026, 3, 9), (9, 30), 10, price=600.0)            # EDT, far prices
    bars = fri + mon
    r = gated_label_event_cell_f1(
        bars, build_atr_series(bars),
        _ev(20),                                                     # signal 15:50 Fri
        stop_atr=50.0, target_atr=50.0, vertical_minutes=3000, cost_round_trip_bp=1.0,
    )
    assert r.withheld_reason is None
    assert r.barrier_hit == "FORCE_FLAT"
    exit_dt = datetime.fromtimestamp(r.t_exit_utc, tz=ET)
    assert (exit_dt.year, exit_dt.month, exit_dt.day) == (2026, 3, 6)


# ── 2. Placebo isolation ─────────────────────────────────────────────────────


def test_placebo_shuffle_never_touches_holdout():
    labels = ["WIN", "LOSS", "TIMEOUT"] * 20
    is_train = [i < 40 for i in range(60)]                            # last 20 = holdout
    out = placebo_shuffle_train_only(labels, is_train, seed=20260723)
    assert out[40:] == labels[40:]                                    # holdout byte-identical
    assert sorted(out[:40]) == sorted(labels[:40])                    # train multiset preserved
    assert out[:40] != labels[:40]                                    # and actually permuted
    again = placebo_shuffle_train_only(labels, is_train, seed=20260723)
    assert again == out                                               # seeded determinism


def test_placebo_shuffle_rejects_partial_masks():
    import pytest

    with pytest.raises(ValueError, match="mask"):
        placebo_shuffle_train_only(["WIN", "LOSS"], [True], seed=1)


# ── 3. Gate wrapping ─────────────────────────────────────────────────────────


def test_battery_routes_every_event_through_the_gate():
    clean = _mk_day((2026, 7, 22), (10, 0), 40)
    poisoned = list(clean)
    poisoned[22] = Bar1m(
        clean[22].bar_start_ts_utc, clean[22].bar_end_ts_utc, clean[22].open,
        clean[22].high, clean[22].low, clean[22].close, clean[22].volume,
        source="synthetic_interior_grid_repair_v1",
    )
    results, report = run_gated_battery(
        poisoned, build_atr_series(poisoned), [_ev(17), _ev(20)], ticker="SPY", **_KW
    )
    # Event at 17: window [2..] includes bar 22 (walk span) -> withheld; both share the window.
    assert all(r.withheld_reason == "synthetic_bar_in_window" for r in results)
    cell = next(iter(report.values()))
    assert cell["n_withheld"] == 2 and cell["bar_source_withheld_rate"] == 1.0


def test_gate_precedes_core_even_on_holiday_fixtures():
    """Synthetic bars on a holiday date: the SOURCE gate fires first — proof the
    S3 wrapper runs before any S2 session logic."""
    bars = _mk_day((2026, 5, 25), (10, 0), 40, source="synthetic_edge_carry_v1")
    r = gated_label_event_cell_f1(bars, build_atr_series(bars), _ev(20), **_KW)
    assert r.withheld_reason == "synthetic_bar_in_window"
    real_holiday = _mk_day((2026, 5, 25), (10, 0), 40)
    r2 = gated_label_event_cell_f1(real_holiday, build_atr_series(real_holiday), _ev(20), **_KW)
    assert r2.withheld_reason == "no_session_for_entry_date"


def test_battery_report_matches_direct_report_composition():
    bars = _mk_day((2026, 7, 22), (10, 0), 40)
    results, report = run_gated_battery(
        bars, build_atr_series(bars), [_ev(20)], ticker="SPY", **_KW
    )
    assert len(results) == 1 and results[0].barrier_hit == "TIMEOUT"
    cell = next(iter(report.values()))
    assert cell["n_candidates"] == 1 and cell["n_labeled"] == 1
