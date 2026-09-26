"""Tests for HVL and max-pain key level computations."""

from math_levels import (
    compute_max_pain,
)






def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    assert compute_max_pain({100.0: {"call_oi": 10.0, "put_oi": 0.0}}) is None


def test_compute_max_pain_skips_strikes_with_missing_multiplier():
    # 90 has call_oi but no call_oi_mult: never a synthetic *100 (dbf6e9e) and no longer
    # skipped either (M-08, 2026-09-24) -- a max pain that leaves out real OI is withheld.
    exposures = {
        90.0: {"call_oi": 5000.0, "put_oi": 0.0, "oi_unreported": 0},
        100.0: {"call_oi": 500.0, "put_oi": 500.0, "call_oi_mult": 50000.0, "put_oi_mult": 50000.0,
                "oi_unreported": 0},
        105.0: {"call_oi": 1000.0, "put_oi": 0.0, "call_oi_mult": 100000.0, "oi_unreported": 0},
    }
    assert compute_max_pain(exposures) is None
