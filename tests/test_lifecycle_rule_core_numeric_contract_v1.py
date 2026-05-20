"""AUDIT_LANE lifecycle_rule_core — FIND-LRC-1..8 finite / fail-closed numerics."""

from __future__ import annotations

import math

import pytest

from lifecycle_rule_core import (
    apply_risk_multiplier,
    apply_time_decay,
    apply_vix_adjustment,
    derive_stop_distance_pct,
    derive_target_levels,
    fire_exit,
    snap_target_to_structural,
)
from math_exposure import STOP_BASE_PCT, STOP_VIX_HIGH_PCT


def _bar(high: float, low: float) -> dict:
    return {"candle_high": high, "candle_low": low}


def test_lrc1_time_decay_nan_mins_treated_as_zero():
    assert apply_time_decay(STOP_BASE_PCT, float("nan")) == pytest.approx(STOP_BASE_PCT)


def test_lrc2_vix_adjustment_nan_vix_unchanged():
    assert apply_vix_adjustment(STOP_BASE_PCT, float("nan")) == pytest.approx(STOP_BASE_PCT)


def test_lrc2_derive_stop_tags_vix_unavailable_on_nan_vix():
    result = derive_stop_distance_pct(
        spot=500.0,
        vix_level=float("nan"),
        mins_elapsed_since_open=None,
        risk_multiplier=None,
    )
    assert "vix_unavailable" in result.adjustments_applied
    assert result.final_pct == pytest.approx(
        max(0.0005, min(0.05, STOP_BASE_PCT)), rel=1e-6
    )


def test_lrc3_risk_multiplier_nan_defaults_to_one():
    assert apply_risk_multiplier(0.002, float("nan")) == pytest.approx(0.002)


def test_lrc4_abs_or_none_nan_avg_ignored_in_target_levels():
    levels = derive_target_levels(
        entry=100.0,
        direction="long",
        risk=2.0,
        avg5=float("nan"),
        avg15=None,
        avg60=None,
        structural_levels=[],
    )
    assert levels.target_source == "2r_fallback"


def test_lrc5_snap_includes_zero_structural_level():
    snapped = snap_target_to_structural(
        target_price=100.5,
        structural_levels=[0.0, 100.2],
        direction="long",
        risk=1.0,
    )
    assert snapped == pytest.approx(100.2)


def test_lrc5_snap_skips_nan_structural_level():
    snapped = snap_target_to_structural(
        target_price=105.0,
        structural_levels=[float("nan"), 104.5],
        direction="long",
        risk=1.0,
    )
    assert snapped == pytest.approx(104.5)


def test_lrc6_derive_target_levels_rejects_nan_risk():
    with pytest.raises(ValueError, match="risk must be positive"):
        derive_target_levels(
            entry=100.0,
            direction="long",
            risk=float("nan"),
            avg5=None,
            avg15=None,
            avg60=None,
            structural_levels=[],
        )


def test_lrc6_derive_target_levels_rejects_nan_entry():
    with pytest.raises(ValueError, match="entry must be finite"):
        derive_target_levels(
            entry=float("inf"),
            direction="long",
            risk=2.0,
            avg5=None,
            avg15=None,
            avg60=None,
            structural_levels=[],
        )


def test_lrc7_fire_exit_nan_stop_skips_not_time_expiry():
    outcome = fire_exit(
        signal="long",
        stop=float("nan"),
        target=103.0,
        forward_bars=[_bar(high=102, low=100)],
        max_hold_bars=5,
    )
    assert outcome.skip_reason == "missing_stop_target_for_exit"
    assert outcome.exit_reason is None


def test_lrc7_fire_exit_nan_target_skips():
    outcome = fire_exit(
        signal="long",
        stop=99.0,
        target=float("nan"),
        forward_bars=[_bar(high=102, low=100)],
        max_hold_bars=5,
    )
    assert outcome.skip_reason == "missing_stop_target_for_exit"


def test_lrc8_cap_target_via_finite_derive_produces_finite_outputs():
    levels = derive_target_levels(
        entry=100.0,
        direction="long",
        risk=2.0,
        avg5=6.0,
        avg15=None,
        avg60=None,
        structural_levels=[],
    )
    assert math.isfinite(levels.target)
    assert math.isfinite(levels.target2)


def test_lrc2_vix_finite_high_still_adjusts():
    assert apply_vix_adjustment(STOP_BASE_PCT, 31.0) == pytest.approx(
        STOP_BASE_PCT + STOP_VIX_HIGH_PCT
    )
