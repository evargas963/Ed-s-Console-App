"""Action 11.1: math_levels fail-closed on missing chain greeks/OI (fails on d2684fb)."""

from __future__ import annotations

from math_exposure_core import key_level_strikes_with_oi
from math_levels import (
    compute_max_pain,
)


def test_key_level_strikes_with_oi_counts_one_sided_and_skips_unknown():
    exposures = {
        100.0: {"call_oi": 100.0, "oi_unreported": 0},                  # one-sided: counts (M-06)
        105.0: {"call_oi": 50.0, "put_oi": 50.0, "oi_unreported": 0},
        110.0: {"call_oi": 70.0, "put_oi": 70.0, "oi_unreported": 1},   # unknown OI: excluded
        115.0: {"oi_unreported": 0},                                    # known zero OI: excluded
    }
    assert key_level_strikes_with_oi(exposures) == [100.0, 105.0]










def test_compute_max_pain_ignores_strike_when_oi_present_but_mult_missing():
    exposures = {
        100.0: {
            "call_oi": 500.0,
            "put_oi": 500.0,
            "call_oi_mult": None,
            "put_oi_mult": 50000.0,
            "oi_unreported": 0,
        },
        105.0: {
            "call_oi": 100.0,
            "put_oi": 100.0,
            "call_oi_mult": 10000.0,
            "put_oi_mult": 10000.0,
            "oi_unreported": 0,
        },
    }
    # positive OI with no multiplier: the strike can't be weighed, so NO max pain -- it
    # used to be skipped, giving a max pain over part of the open interest (M-08)
    assert compute_max_pain(exposures) is None


def test_compute_max_pain_skips_strike_with_only_one_oi_mult():
    exposures = {
        90.0: {"call_oi": 5000.0, "call_oi_mult": 500000.0, "oi_unreported": 0},
        100.0: {
            "call_oi": 500.0,
            "put_oi": 500.0,
            "call_oi_mult": 50000.0,
            "put_oi_mult": 50000.0,
            "oi_unreported": 0,
        },
        105.0: {
            "call_oi": 50.0,
            "put_oi": 50.0,
            "call_oi_mult": 5000.0,
            "put_oi_mult": 5000.0,
            "oi_unreported": 0,
        },
    }
    # the one-sided 90 strike now COUNTS (M-08): its 5000 calls are what settlement at 90
    # would pay nothing on, so max pain moves to 90
    assert compute_max_pain(exposures) == 90.0
