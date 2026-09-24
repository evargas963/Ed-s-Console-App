"""Action 11.1: math_levels fail-closed on missing chain greeks/OI (fails on d2684fb)."""

from __future__ import annotations

from math_exposure_core import key_level_strikes_with_oi
from math_levels import (
    _pick_oi_center,
    _strike_total_oi,
    build_summary_rows,
    build_totals_rows,
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


def test_strike_total_oi_is_known_only_when_every_contract_reported_oi():
    """T-04 / M-06 (2026-09-24): a one-sided strike's absent leg is a KNOWN zero (every
    contract there reported OI); a strike with an unreported-OI contract is unknown. The
    old rule required both legs, dropping every one-sided strike."""
    assert _strike_total_oi({"call_oi": 100.0, "oi_unreported": 0}) == 100.0
    assert _strike_total_oi({"put_oi": 50.0, "oi_unreported": 0}) == 50.0
    assert _strike_total_oi({"call_oi": 100.0, "put_oi": 50.0, "oi_unreported": 0}) == 150.0
    assert _strike_total_oi({"call_oi": 100.0, "put_oi": 50.0, "oi_unreported": 1}) is None
    assert _strike_total_oi({"call_oi": 100.0, "put_oi": 50.0}) is None   # not from the producer


def test_pick_oi_center_counts_one_sided_oi_and_skips_unknown():
    exposures = {
        100.0: {"call_oi": 1500.0, "oi_unreported": 0},            # one-sided, known
        105.0: {"call_oi": 200.0, "put_oi": 800.0, "oi_unreported": 0},
        110.0: {"call_oi": 9000.0, "oi_unreported": 2},            # unknown -> not ranked
    }
    assert _pick_oi_center(exposures, [100.0, 105.0, 110.0]) == 100.0


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
