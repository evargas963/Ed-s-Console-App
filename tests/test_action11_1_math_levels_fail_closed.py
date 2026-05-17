"""Action 11.1: math_levels fail-closed on missing chain greeks/OI (fails on d2684fb)."""

from __future__ import annotations

from math_levels import (
    _pick_oi_center,
    _strike_total_oi,
    build_summary_rows,
    build_totals_rows,
    compute_max_pain,
)


def test_strike_total_oi_requires_both_legs():
    assert _strike_total_oi({"call_oi": 100.0}) is None
    assert _strike_total_oi({"put_oi": 50.0}) is None
    assert _strike_total_oi({"call_oi": 100.0, "put_oi": 50.0}) == 150.0


def test_pick_oi_center_skips_one_sided_oi():
    exposures = {
        100.0: {"call_oi": 1000.0},
        105.0: {"call_oi": 200.0, "put_oi": 800.0},
    }
    assert _pick_oi_center(exposures, [100.0, 105.0]) == 105.0


def test_build_totals_no_phantom_zero_when_greeks_missing():
    exposures = {
        100.0: {"call_oi": 10.0, "put_oi": 10.0},
    }
    rows = build_totals_rows(exposures, 100.0, windows=[5], contracts_for_iv=[])
    consensus = rows[0]
    assert consensus.call_gamma is None
    assert consensus.put_gamma is None
    assert consensus.net_gamma is None
    assert consensus.net_delta is None


def test_build_summary_net_gamma_none_when_all_strikes_missing_gamma():
    exposures = {
        100.0: {"call_oi": 1.0, "put_oi": 1.0},
        101.0: {"call_oi": 2.0, "put_oi": 2.0},
    }
    rows = build_summary_rows(exposures, 100.5, windows=[5])
    assert rows[0].net_gamma is None
    assert rows[0].net_delta is None


def test_compute_max_pain_skips_strike_with_only_one_oi_mult():
    exposures = {
        90.0: {"call_oi": 5000.0, "call_oi_mult": 500000.0},
        100.0: {
            "call_oi": 500.0,
            "put_oi": 500.0,
            "call_oi_mult": 50000.0,
            "put_oi_mult": 50000.0,
        },
    }
    assert compute_max_pain(exposures) == 100.0
