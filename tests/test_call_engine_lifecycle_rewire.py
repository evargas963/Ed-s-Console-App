"""call_engine's rewired stop/target wiring through lifecycle_rule_core and
math_exposure must still compute the correct StopDistance/TargetLevels after the
rewire -- this proves the seam, not just that the old code path still exists."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import call_engine as ce


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
    atr: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        atr=atr,
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




def test_compute_levels_never_snaps_to_structural_levels():
    """Price-action plan (operator 2026-06-11): a nearby VWAP/wall must NOT pull
    targets — geometry is entry/stop/R-multiples + predicted moves only."""
    result = ce._compute_levels(
        _inp(spot=1000.0, vwap=1003.5, atr=1.2),
        "long",
        rules=None,
        pred=_pred(avg_5c_pts=3.0, avg_15c_pts=5.0),
        risk_multiplier=1.0,
        governed_zone="",
    )

    # 1.8-pt stop; T1 = the 3.0 5c move (> 1.5R = 2.7), T2 = the 5.0 15c move -- the VWAP
    # at 1003.5 does not pull T1.
    assert result == (1000.0, 998.2, 1003.0, 1005.0)
    # no measured moves -> entry/stop, but NO targets (not a 2R/3R ladder)
    assert ce._compute_levels(_inp(spot=1000.0, atr=1.2), "long", rules=None, pred=_pred(),
                              risk_multiplier=1.0, governed_zone="") == (1000.0, 998.2, None, None)


def test_stop_distance_is_atr_only_and_never_guessed():
    """ATR-scaled stop (Wilder 1978): ATR_STOP_MULT x ATR x regime multiplier. No finite,
    positive ATR -> None: the VIX/clock percentage stop that used to stand in is gone
    (audit P0, operator rule 2026-09-23: no fallbacks)."""
    inp = _inp(spot=1000.0, vix_level=35.0)
    inp.atr = 2.0
    assert ce._stop_distance(inp) == pytest.approx(ce.ATR_STOP_MULT * 2.0)
    assert ce._stop_distance(inp, risk_multiplier=1.2) == pytest.approx(
        round(ce.ATR_STOP_MULT * 2.0 * 1.2, 2)
    )
    for bad in (None, 0.0, -1.0, float("nan"), float("inf")):
        inp.atr = bad
        assert ce._stop_distance(inp) is None, bad


def test_no_measured_stop_means_no_plan():
    for signal in ("long", "short"):
        assert ce._compute_levels(_inp(spot=1000.0), signal, rules=None, pred=_pred(),
                                  risk_multiplier=1.0, governed_zone="") == (None, None, None, None)


def test_compute_levels_preserves_long_targets_and_rr_caps():
    result = ce._compute_levels(
        _inp(spot=1000.0, atr=1.2),
        "long",
        rules=None,
        pred=_pred(avg_5c_pts=100.0, avg_15c_pts=100.0),
        risk_multiplier=1.0,
        governed_zone="",
    )

    assert result == (1000.0, 998.2, 1009.0, 1014.4)


def test_compute_levels_preserves_short_targets_and_rr_caps():
    result = ce._compute_levels(
        _inp(spot=1000.0, atr=1.2),
        "short",
        rules=None,
        pred=_pred(avg_5c_pts=100.0, avg_15c_pts=100.0),
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
