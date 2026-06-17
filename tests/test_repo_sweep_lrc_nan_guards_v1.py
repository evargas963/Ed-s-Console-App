"""REPO_SWEEP SWEEP-LRC-NAN: lifecycle_rule_core NaN guards (OBS-LRC-3 + OBS-LRC-4)."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from lifecycle_rule_core import (
    apply_risk_multiplier,
    apply_time_decay,
    apply_vix_adjustment,
    derive_stop_distance_pct,
    fire_exit,
)
from math_exposure import (
    STOP_BASE_PCT,
    STOP_CEILING_PCT,
    STOP_FLOOR_PCT,
    STOP_TIME_DECAY_PCT,
    STOP_VIX_HIGH_PCT,
)

_LIFECYCLE_NAN_PASSTHROUGH = re.compile(r"return\s+float\(distance_pct\)")
_LIFECYCLE_CORE = Path(__file__).resolve().parents[1] / "lifecycle_rule_core.py"


def _bar(*, high: float, low: float) -> dict:
    return {"candle_high": high, "candle_low": low}


def test_fire_exit_nan_max_hold_bars_defaults_to_1_not_value_error():
    bars = [_bar(high=102, low=100)] * 5
    with_nan = fire_exit(
        signal="long",
        stop=99.0,
        target=103.0,
        forward_bars=bars,
        max_hold_bars=float("nan"),  # type: ignore[arg-type]
    )
    one_bar = fire_exit(
        signal="long",
        stop=99.0,
        target=103.0,
        forward_bars=bars,
        max_hold_bars=1,
    )
    assert with_nan == one_bar
    assert with_nan.exit_reason == "time_expiry"


def test_apply_time_decay_nan_distance_pct_returns_stop_base_pct():
    out = apply_time_decay(float("nan"), 60)
    expected = STOP_BASE_PCT - (60 / 60.0) * STOP_TIME_DECAY_PCT
    assert out == pytest.approx(expected)
    assert math.isfinite(out)


def test_apply_vix_adjustment_nan_distance_pct_returns_stop_base_pct():
    out = apply_vix_adjustment(float("nan"), 31.0)
    expected = STOP_BASE_PCT + STOP_VIX_HIGH_PCT
    assert out == pytest.approx(expected)
    assert math.isfinite(out)


def test_apply_risk_multiplier_nan_distance_pct_returns_stop_base_pct():
    out = apply_risk_multiplier(float("nan"), 1.25)
    expected = STOP_BASE_PCT * 1.25
    assert out == pytest.approx(expected)
    assert math.isfinite(out)


def test_lifecycle_nan_passthrough_pattern_banned_in_production():
    src = _LIFECYCLE_CORE.read_text(encoding="utf-8")
    matches = _LIFECYCLE_NAN_PASSTHROUGH.findall(src)
    assert matches == []


def test_derive_stop_distance_pct_with_nan_seed_seeds_back_to_stop_base_pct():
    pct = float("nan")
    pct = apply_time_decay(pct, 60.0)
    pct = apply_vix_adjustment(pct, 31.0)
    pct = apply_risk_multiplier(pct, 1.35)
    pct = max(STOP_FLOOR_PCT, min(STOP_CEILING_PCT, pct))
    assert math.isfinite(pct)
    assert STOP_FLOOR_PCT <= pct <= STOP_CEILING_PCT

    direct = derive_stop_distance_pct(
        spot=500.0,
        vix_level=31.0,
        mins_elapsed_since_open=60.0,
        risk_multiplier=1.35,
    )
    assert math.isfinite(direct.final_pct)
    assert direct.final_pct == pytest.approx(pct)
