"""Tests for HVL and max-pain key level computations."""

from math_levels import compute_hvl, compute_max_pain, hvl_gamma_strength, max_pain_oi_strength


def test_compute_hvl_picks_peak_total_gamma_strike():
    exposures = {
        100.0: {"call_gamma": 10.0, "put_gamma": 5.0},
        105.0: {"call_gamma": 50.0, "put_gamma": 40.0},
        110.0: {"call_gamma": 20.0, "put_gamma": 15.0},
    }
    assert compute_hvl(exposures) == 105.0
    assert hvl_gamma_strength(exposures, 105.0) == 90.0


def test_compute_max_pain_minimizes_itm_payout():
    # Calls dominate above 100; puts below 100 — pain minimized near 100
    exposures = {
        95.0: {"call_oi": 0.0, "put_oi": 1000.0, "put_oi_mult": 100000.0},
        100.0: {"call_oi": 500.0, "put_oi": 500.0, "call_oi_mult": 50000.0, "put_oi_mult": 50000.0},
        105.0: {"call_oi": 1000.0, "put_oi": 0.0, "call_oi_mult": 100000.0},
    }
    mp = compute_max_pain(exposures)
    assert mp == 100.0
    assert max_pain_oi_strength(exposures, mp) == 1000.0


def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    assert compute_max_pain({100.0: {"call_oi": 10.0, "put_oi": 0.0}}) is None
