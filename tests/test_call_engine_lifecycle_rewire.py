from __future__ import annotations

from types import SimpleNamespace

import pytest

import call_engine as ce
from lifecycle_rule_core import StopDistance, TargetLevels
from math_exposure import (
    STOP_BASE_PCT,
    STOP_CEILING_PCT,
    STOP_FLOOR_PCT,
    STOP_TIME_DECAY_PCT,
    STOP_VIX_HIGH_PCT,
    STOP_VIX_MED_PCT,
)


def _inp(
    *,
    spot: float = 1000.0,
    et_hour: int = 9,
    et_minute: int = 30,
    vix_level: float | None = None,
    vwap: float | None = None,
    call_gamma_wall: float | None = None,
    put_gamma_wall: float | None = None,
    call_oi_wall: float | None = None,
    put_oi_wall: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        spot=spot,
        et_hour=et_hour,
        et_minute=et_minute,
        vix_level=vix_level,
        vwap=vwap,
        call_gamma_wall=call_gamma_wall,
        put_gamma_wall=put_gamma_wall,
        call_oi_wall=call_oi_wall,
        put_oi_wall=put_oi_wall,
    )


def _pred(
    *,
    avg_5c_pts: float | None = None,
    avg_15c_pts: float | None = None,
    avg_60c_pts: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        avg_5c_pts=avg_5c_pts,
        avg_15c_pts=avg_15c_pts,
        avg_60c_pts=avg_60c_pts,
        move_range_hi=None,
    )


def _expected_stop_distance(
    *,
    spot: float = 1000.0,
    elapsed_minutes: float = 0.0,
    vix_level: float | None = None,
    risk_multiplier: float | None = 1.0,
) -> float:
    pct = STOP_BASE_PCT - (elapsed_minutes / 60.0) * STOP_TIME_DECAY_PCT
    if vix_level is not None:
        if vix_level > 30:
            pct += STOP_VIX_HIGH_PCT
        elif vix_level > 20:
            pct += STOP_VIX_MED_PCT
    pct *= max(0.8, min(1.5, risk_multiplier or 1.0))
    pct = max(STOP_FLOOR_PCT, min(STOP_CEILING_PCT, pct))
    return round(pct * spot, 2)


def test_stop_distance_delegates_to_lifecycle_rule_core(monkeypatch):
    calls: list[dict] = []

    def fake_derive_stop_distance_pct(**kwargs):
        calls.append(kwargs)
        return StopDistance(final_pct=0.01, adjustments_applied=("test",))

    monkeypatch.setattr(ce, "derive_stop_distance_pct", fake_derive_stop_distance_pct, raising=False)

    result = ce._stop_distance(_inp(spot=100.0, et_hour=10, et_minute=0, vix_level=21.0), risk_multiplier=1.2)

    assert calls == [
        {
            "spot": 100.0,
            "vix_level": 21.0,
            "mins_elapsed_since_open": 30,
            "risk_multiplier": 1.2,
        }
    ]
    assert result == pytest.approx(1.0)


def test_compute_levels_delegates_target_geometry_to_lifecycle_rule_core(monkeypatch):
    calls: list[dict] = []

    def fake_derive_target_levels(**kwargs):
        calls.append(kwargs)
        return TargetLevels(
            target=105.0,
            target2=106.0,
            target_source="test",
            target2_source="test",
            target_snapped=False,
            target2_snapped=False,
        )

    monkeypatch.setattr(ce, "derive_target_levels", fake_derive_target_levels, raising=False)

    result = ce._compute_levels(
        _inp(spot=100.0, vwap=104.0, call_gamma_wall=105.0),
        "long",
        rules=None,
        pred=_pred(avg_5c_pts=4.0, avg_15c_pts=5.0, avg_60c_pts=6.0),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert len(calls) == 1
    assert calls[0]["direction"] == "long"
    assert calls[0]["avg5"] == pytest.approx(4.0)
    assert calls[0]["avg15"] == pytest.approx(5.0)
    assert calls[0]["avg60"] == pytest.approx(6.0)
    assert set(calls[0]["structural_levels"]) == {104.0, 105.0}
    assert result == (100.0, pytest.approx(99.82), 105.0, 106.0)


@pytest.mark.parametrize(
    ("vix_level", "expected_add"),
    [
        (20.0, 0.0),
        (20.01, STOP_VIX_MED_PCT),
        (30.0, STOP_VIX_MED_PCT),
        (30.01, STOP_VIX_HIGH_PCT),
    ],
)
def test_stop_distance_preserves_vix_20_and_30_boundaries(vix_level, expected_add):
    expected = round((STOP_BASE_PCT + expected_add) * 1000.0, 2)

    assert ce._stop_distance(_inp(vix_level=vix_level)) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("hour", "minute", "elapsed"),
    [
        (9, 30, 0),
        (11, 30, 120),
        (15, 55, 385),
    ],
)
def test_stop_distance_preserves_time_decay_across_session(hour, minute, elapsed):
    assert ce._stop_distance(_inp(et_hour=hour, et_minute=minute)) == pytest.approx(
        _expected_stop_distance(elapsed_minutes=elapsed)
    )


@pytest.mark.parametrize(
    ("risk_multiplier", "effective_multiplier"),
    [
        (0.5, 0.8),
        (0.0, 1.0),
        (2.0, 1.5),
    ],
)
def test_stop_distance_preserves_risk_multiplier_clamp(risk_multiplier, effective_multiplier):
    expected = round(STOP_BASE_PCT * effective_multiplier * 1000.0, 2)

    assert ce._stop_distance(_inp(), risk_multiplier=risk_multiplier) == pytest.approx(expected)


def test_compute_levels_preserves_structural_snap_toward_near_level():
    result = ce._compute_levels(
        _inp(spot=1000.0, vwap=1003.5),
        "long",
        rules=None,
        pred=_pred(),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert result == (1000.0, 998.2, 1003.5, 1005.3)


def test_compute_levels_preserves_long_targets_and_rr_caps():
    result = ce._compute_levels(
        _inp(spot=1000.0),
        "long",
        rules=None,
        pred=_pred(avg_5c_pts=100.0, avg_15c_pts=100.0),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert result == (1000.0, 998.2, 1009.0, 1014.4)


def test_compute_levels_preserves_short_targets_and_rr_caps():
    result = ce._compute_levels(
        _inp(spot=1000.0),
        "short",
        rules=None,
        pred=_pred(avg_5c_pts=100.0, avg_60c_pts=100.0),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert result == (1000.0, 1001.8, 991.0, 985.6)


def test_compute_levels_preserves_legacy_tuple_shape():
    result = ce._compute_levels(
        _inp(),
        "wait",
        rules=None,
        pred=_pred(),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert result == (None, None, None, None)
