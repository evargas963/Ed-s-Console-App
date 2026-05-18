from __future__ import annotations

from types import SimpleNamespace

import pytest

from multi_horizon_decision import (
    REASON_PRIMARY_HORIZON_DATA_MISSING,
    build_multi_horizon_bundle,
)


def _inp(spot: float = 441.5, mins_to_close: float = 180.0):
    return SimpleNamespace(
        spot=spot,
        mins_to_close=mins_to_close,
        nearest_below_val=441.3,
        nearest_above_val=441.8,
    )


def _pred(
    u1=0.6, d1=0.2, f1=0.2,
    u5=0.6, d5=0.2, f5=0.2,
    u15=0.65, d15=0.2, f15=0.15,
    u60=0.62, d60=0.2, f60=0.18,
):
    return SimpleNamespace(
        up_prob_1c=u1, down_prob_1c=d1, flat_prob_1c=f1,
        up_prob_5c=u5, down_prob_5c=d5, flat_prob_5c=f5,
        up_prob_15c=u15, down_prob_15c=d15, flat_prob_15c=f15,
        up_prob_60c=u60, down_prob_60c=d60, flat_prob_60c=f60,
        avg_5c_pts=1.1, avg_15c_pts=2.3, avg_60c_pts=4.6,
    )


def _call(signal: str = "long", entry: float | None = 441.55, state: str = "WATCH"):
    return SimpleNamespace(signal=signal, entry=entry, stop=440.9, target=442.8, target2=444.1, call_state=state)


def _canonical():
    return SimpleNamespace(direction="up", probability_up=0.6, probability_down=0.2, probability_flat=0.2, confidence="medium", provenance="test")


def test_all_horizons_bullish_fully_aligned_long():
    b = build_multi_horizon_bundle(_inp(mins_to_close=200), _pred(), _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "LONG"
    assert d.contradiction_state not in ("structural",)


def test_intraday_15c_primary_with_1c_timing_contradiction_downgrades_not_forced_reversal():
    p = _pred(u1=0.25, d1=0.6, f1=0.15, u15=0.67, d15=0.2, f15=0.13, u60=0.6, d60=0.2, f60=0.2)
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    d = b.final_decision
    assert d.primary_horizon == "15c"
    assert d.final_bias in ("LONG", "WAIT")
    assert any(r["horizon"] == "1c" and r["role"] in ("Timing", "Contradiction") for r in [vars(x) for x in d.supporting_assessments])


def test_session_mode_60c_primary_when_valid():
    b = build_multi_horizon_bundle(_inp(mins_to_close=320), _pred(), _canonical(), _call())
    assert b.final_decision.primary_horizon == "60c"


def test_scalp_mode_prefers_1c_or_5c():
    p = _pred(u1=0.4, d1=0.32, f1=0.28, u5=0.66, d5=0.2, f5=0.14)
    b = build_multi_horizon_bundle(_inp(mins_to_close=40), p, _canonical(), _call())
    assert b.final_decision.primary_horizon in ("1c", "5c")


def test_primary_fallback_when_preferred_unavailable():
    p = _pred(u15=0.34, d15=0.33, f15=0.33, u5=0.63, d5=0.2, f5=0.17)
    # Without Issue-13 canonical, 15c stays non-tradeable → fallback to 5c.
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, None, _call())
    d = b.final_decision
    assert d.primary_selection.fallback_used is True
    assert d.primary_horizon != d.primary_selection.requested_primary


def test_severe_contradiction_can_force_wait():
    p = _pred(u15=0.65, d15=0.2, f15=0.15, u60=0.15, d60=0.72, f60=0.13, u5=0.2, d5=0.65, f5=0.15)
    b = build_multi_horizon_bundle(_inp(mins_to_close=190), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias in ("WAIT", "LONG")
    if d.final_bias == "WAIT":
        assert d.wait_reason != ""


def test_missingness_can_result_in_wait():
    p = _pred()
    p.up_prob_15c = None
    p.down_prob_15c = None
    p.flat_prob_15c = None
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    assert b.completeness in ("partial", "complete")


def test_entry_state_forming_armed_confirmed_filled():
    p = _pred()
    # forming: out of zone
    b_forming = build_multi_horizon_bundle(_inp(spot=443.0, mins_to_close=180), p, _canonical(), _call(state="WATCH", entry=None))
    assert b_forming.final_decision.entry_state == "forming"
    # armed: in zone but no 1c confirmation
    p2 = _pred(u1=0.35, d1=0.35, f1=0.30)
    b_armed = build_multi_horizon_bundle(_inp(spot=441.45, mins_to_close=180), p2, _canonical(), _call(state="WATCH", entry=None))
    assert b_armed.final_decision.entry_state in ("armed", "forming")
    # confirmed: in zone with 1c confirmation
    b_conf = build_multi_horizon_bundle(_inp(spot=441.45, mins_to_close=180), p, _canonical(), _call(state="WATCH", entry=441.5))
    assert b_conf.final_decision.entry_state in ("confirmed", "filled")
    # filled: active + entry
    b_filled = build_multi_horizon_bundle(_inp(spot=441.45, mins_to_close=180), p, _canonical(), _call(state="ACTIVE", entry=441.5))
    assert b_filled.final_decision.entry_state == "filled"


def test_mhap_rows_have_fixed_horizon_set():
    b = build_multi_horizon_bundle(_inp(), _pred(), _canonical(), _call())
    got = [r.horizon for r in b.final_decision.supporting_assessments]
    assert set(got) == {"1c", "5c", "15c", "60c"}


@pytest.mark.parametrize("hz,attr_prefix", [
    ("1c", "1c"),
    ("5c", "5c"),
    ("15c", "15c"),
    ("60c", "60c"),
])
def test_missing_native_horizon_assessment_unavailable(hz, attr_prefix):
    """Phase A: null native probs → UNAVAILABLE + reason (no secondary substitution)."""
    p = _pred()
    setattr(p, f"up_prob_{attr_prefix}", None)
    setattr(p, f"down_prob_{attr_prefix}", None)
    setattr(p, f"flat_prob_{attr_prefix}", None)
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    row = next(x for x in b.final_decision.supporting_assessments if x.horizon == hz)
    assert row.missing is True
    assert row.call == "UNAVAILABLE"
    assert row.row_state == "missing"
    assert row.reason_code == REASON_PRIMARY_HORIZON_DATA_MISSING
    assert hz in b.missing_horizons


def test_missing_15c_does_not_substitute_13c_probs():
    """Regression: 15c missing must not show tradeable LONG from unrelated horizons."""
    p = _pred(u15=0.67, d15=0.2, f15=0.15)
    p.up_prob_15c = None
    p.down_prob_15c = None
    p.flat_prob_15c = None
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    row = next(x for x in b.final_decision.supporting_assessments if x.horizon == "15c")
    assert row.missing is True
    assert row.call == "UNAVAILABLE"
    assert row.confidence == 0.0
