"""F1 S3 seam tests — input gates + label-quality report (drives the REAL gates).

Locks: bar-source gate by explicit membership with UNKNOWN failing closed;
gate-clean candidates delegate to label_event_cell_f1_v2 unchanged; the greeks
era floor at epoch 1784502281 exactly; the TWO-SIDED permutation verdict
(anti-signal is a STOP, not a pass — the Round-2 finding); the seeded placebo
shuffler; and the per-ticker class-balance/flag-rate report.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from research.pilot_step3.data_loader import Bar1m
from research.pilot_step3.event_generation import PilotEvent
from research.pilot_step3.f1_input_gates import (
    F1_GREEKS_ERA_FLOOR_TS_UTC,
    build_label_quality_report,
    classify_bar_source,
    gated_label_event_cell_f1,
    greeks_era_ok,
    permutation_control_verdict,
    placebo_permuted_labels,
)
from research.pilot_step3.labeling import build_atr_series, label_event_cell_f1_v2

ET = ZoneInfo("America/New_York")
REAL = "schwab_1m_accumulator_sqlite"


def _mk_bars(n=40, *, source=REAL, price=680.0, rng=0.2):
    t0 = datetime(2026, 7, 22, 10, 0, tzinfo=ET)
    out = []
    for i in range(n):
        s = (t0 + timedelta(minutes=i)).timestamp()
        out.append(
            Bar1m(
                bar_start_ts_utc=s,
                bar_end_ts_utc=s + 60.0,
                open=price,
                high=price + rng,
                low=price - rng,
                close=price,
                volume=100.0,
                source=source,
            )
        )
    return out


def _ev(i_sig=20):
    return PilotEvent(
        event_id=f"gate-{i_sig}",
        signal_bar_index=i_sig,
        T_close_ts_utc=0.0,
        side="LONG",
        sma_fast=0.0,
        sma_slow=0.0,
        cusum_pos=0.0,
        cusum_neg=0.0,
        z_trigger=0.0,
        candidate_generator_id="gate_fixture",
    )


_KW = dict(stop_atr=50.0, target_atr=50.0, vertical_minutes=5, cost_round_trip_bp=1.0)


def test_classify_bar_source_is_explicit_membership_both_ways():
    assert classify_bar_source(REAL) == "real"
    assert classify_bar_source("schwab_pricehistory") == "real"
    assert classify_bar_source("synthetic_interior_grid_repair_v1") == "synthetic"
    assert classify_bar_source("gap_fill_canonical_1m_grid_v1") == "synthetic"
    assert classify_bar_source("some_future_tag") == "unknown"
    assert classify_bar_source(None) == "unknown"


def test_synthetic_bar_in_window_withholds():
    bars = _mk_bars()
    bars[22] = Bar1m(
        bars[22].bar_start_ts_utc, bars[22].bar_end_ts_utc, bars[22].open,
        bars[22].high, bars[22].low, bars[22].close, bars[22].volume,
        source="synthetic_interior_grid_repair_v1",
    )
    r = gated_label_event_cell_f1(bars, build_atr_series(bars), _ev(), **_KW)
    assert r.withheld_reason == "synthetic_bar_in_window"


def test_unknown_bar_source_fails_closed():
    bars = _mk_bars()
    bars[10] = Bar1m(
        bars[10].bar_start_ts_utc, bars[10].bar_end_ts_utc, bars[10].open,
        bars[10].high, bars[10].low, bars[10].close, bars[10].volume, source=None,
    )
    r = gated_label_event_cell_f1(bars, build_atr_series(bars), _ev(), **_KW)
    assert r.withheld_reason == "unknown_bar_source_in_window"


def test_all_real_window_delegates_to_v2_unchanged():
    bars = _mk_bars()
    atr = build_atr_series(bars)
    gated = gated_label_event_cell_f1(bars, atr, _ev(), **_KW)
    direct = label_event_cell_f1_v2(bars, atr, _ev(), **_KW)
    assert gated == direct
    assert gated.withheld_reason is None


def test_greeks_era_floor_exact_at_epoch():
    e = F1_GREEKS_ERA_FLOOR_TS_UTC
    assert greeks_era_ok(e) is True
    assert greeks_era_ok(e + 1.0) is True
    assert greeks_era_ok(e - 1.0) is False
    assert greeks_era_ok(e - 1.0, rebuilt_from_chain_archive=True) is True


def test_permutation_verdict_is_two_sided():
    ok = permutation_control_verdict(1.0 / 3.0)
    assert ok == {"collapsed_to_chance": True, "leakage_stop": False, "anti_signal_stop": False}
    leak = permutation_control_verdict(0.42)
    assert leak["leakage_stop"] is True and leak["collapsed_to_chance"] is False
    anti = permutation_control_verdict(0.24)
    assert anti["anti_signal_stop"] is True and anti["collapsed_to_chance"] is False


def test_placebo_shuffle_preserves_multiset_and_is_seeded():
    labels = ["WIN"] * 5 + ["LOSS"] * 3 + ["TIMEOUT"] * 2
    a = placebo_permuted_labels(labels, seed=20260723)
    b = placebo_permuted_labels(labels, seed=20260723)
    c = placebo_permuted_labels(labels, seed=1)
    assert a == b
    assert sorted(a) == sorted(labels) == sorted(c)
    assert a != labels or c != labels  # at least one seed actually moves labels


def test_display_lane_guard_refuses_greeks_without_prereg_binding():
    from research.pilot_step3.f1_input_gates import (
        DISPLAY_ONLY_GREEKS_FEATURES,
        assert_features_off_display_lane,
    )
    from research.pilot_step3.meta_xgb_tb_runner import FEATURE_NAMES

    assert_features_off_display_lane(FEATURE_NAMES)  # v1 price-only set is clean
    assert "net_gamma" in DISPLAY_ONLY_GREEKS_FEATURES
    assert "net_gamma_rc" in DISPLAY_ONLY_GREEKS_FEATURES
    with pytest.raises(ValueError, match="net_gamma"):
        assert_features_off_display_lane([*FEATURE_NAMES, "net_gamma"])
    # An explicit certified-prereg binding is the ONLY admission path.
    assert_features_off_display_lane(
        [*FEATURE_NAMES, "net_gamma"],
        certified_prereg_id="CERTIFIED_GREEKS_CHANNEL_PREREG_EXAMPLE_V1",
    )


def test_label_quality_report_counts_and_rates():
    bars = _mk_bars()
    atr = build_atr_series(bars)
    ok = gated_label_event_cell_f1(bars, atr, _ev(), **_KW)          # TIMEOUT (wide barriers)
    synth_bars = _mk_bars(source="synthetic_edge_carry_v1")
    wh = gated_label_event_cell_f1(synth_bars, build_atr_series(synth_bars), _ev(), **_KW)
    rep = build_label_quality_report({"SPY": [ok, wh]})
    assert list(rep.keys()) == ["SPY"]
    cell = next(iter(rep.values()))
    assert cell["n_candidates"] == 2
    assert cell["n_labeled"] == 1
    assert cell["n_withheld"] == 1
    assert cell["class_counts"]["TIMEOUT"] == 1
    assert cell["withheld_reasons"] == {"synthetic_bar_in_window": 1}
    assert cell["bar_source_withheld_rate"] == 0.5
    assert cell["cost_floor_binding_rate"] == 0.0
