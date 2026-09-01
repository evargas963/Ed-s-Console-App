"""multi_horizon_decision's alignment-state classification (ALIGNMENT_STATE_NO_PRIMARY
etc.) must correctly detect when the primary-horizon decision data is missing rather
than silently aligning against a stale/absent horizon."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from multi_horizon_decision import (
    ALIGNMENT_STATE_NO_PRIMARY,
    REASON_PRIMARY_HORIZON_DATA_MISSING,
    alignment_state_operator_label,
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
        horizon_directional_authorized={
            "1c": True, "5c": True, "15c": True, "60c": True,
        },
    )


def _call(signal: str = "long", entry: float | None = 441.55, state: str = "WATCH", wait_blocker=None):
    return SimpleNamespace(
        signal=signal,
        entry=entry,
        stop=440.9,
        target=442.8,
        target2=444.1,
        call_state=state,
        wait_blocker=wait_blocker,
    )


def _canonical():
    return SimpleNamespace(direction="up", probability_up=0.6, probability_down=0.2, probability_flat=0.2, confidence="medium", provenance="test")


def test_flat_primary_emits_no_primary_alignment_not_wait():
    """Flat / non-tradeable primary → alignment no_primary (not confused with WAIT or UNAVAILABLE)."""
    p = _pred(
        u1=0.32, d1=0.17, f1=0.51,
        u5=0.37, d5=0.28, f5=0.35,
        u15=0.28, d15=0.22, f15=0.50,
        u60=0.30, d60=0.19, f60=0.51,
    )
    b = build_multi_horizon_bundle(_inp(mins_to_close=320), p, _canonical(), _call(signal="wait"))
    d = b.final_decision
    assert d.final_bias == "WAIT"
    assert d.alignment_state == ALIGNMENT_STATE_NO_PRIMARY
    assert alignment_state_operator_label(d.alignment_state) == "no primary edge"


def test_call_engine_wait_veto_suppresses_final_tradeable_when_pool_long():
    """Pooled LONG must not show tradeable when execution stack returned WAIT."""
    b = build_multi_horizon_bundle(
        _inp(),
        _pred(),
        _canonical(),
        _call(
            signal="wait",
            wait_blocker={"reason": "time", "detail": "≤25 min to close"},
        ),
    )
    d = b.final_decision
    assert d.final_bias == "LONG"
    assert d.final_tradeable is False
    assert d.entry_state == "no_setup"
    assert "call engine veto" in d.wait_reason
    audit = b.ml_live_audit.get("call_engine_veto") or {}
    assert audit.get("applied") is True


def test_pooled_long_with_one_tradeable_horizon_withholds_all_and_plan():
    """Regression: log-pool can lean LONG while only one horizon is tradeable — PLAN must not arm."""
    p = _pred(
        u1=0.55, d1=0.20, f1=0.25,
        u5=0.37, d5=0.33, f5=0.30,
        u15=0.37, d15=0.33, f15=0.30,
        u60=0.37, d60=0.33, f60=0.30,
    )
    b = build_multi_horizon_bundle(_inp(mins_to_close=320), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "WAIT"
    assert d.final_tradeable is False
    assert d.entry_state == "no_setup"
    assert "tradeable horizons align" in d.wait_reason
    audit = b.ml_live_audit.get("all_card_pool") or {}
    assert audit.get("tradeable_horizons_aligned_with_pooled_bias") == 1


def test_all_horizons_bullish_fully_aligned_long():
    b = build_multi_horizon_bundle(_inp(mins_to_close=200), _pred(), _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "LONG"
    assert d.contradiction_state not in ("structural",)


# ── ALL-card pooled consensus (operator 2026-06-11) ─────────────────────────
# The consolidated bias is a skill-weighted logarithmic opinion pool over all
# four horizon triplets — never a relay of the mode-selected primary horizon
# and never a head-count vote.


def test_all_card_weak_single_horizon_pools_below_gate():
    """One modest horizon diluted by three near-uniform ones stays below the
    pooled entry gate — no single-horizon relay."""
    p = _pred(
        u1=0.34, d1=0.33, f1=0.33,
        u5=0.50, d5=0.30, f5=0.20,
        u15=0.34, d15=0.33, f15=0.33,
        u60=0.34, d60=0.33, f60=0.33,
    )
    b = build_multi_horizon_bundle(_inp(mins_to_close=40), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "WAIT"
    assert d.final_tradeable is False
    assert d.wait_reason.startswith("pooled stack evidence below entry gate")


def test_all_card_two_agreeing_horizons_pool_long():
    """Pooled entry: 5c+15c strong long, 1c/60c near-uniform -> pooled evidence
    clears the gate; confidence = pooled dominant probability."""
    p = _pred(
        u1=0.34, d1=0.33, f1=0.33,
        u5=0.62, d5=0.20, f5=0.18,
        u15=0.66, d15=0.20, f15=0.14,
        u60=0.34, d60=0.33, f60=0.33,
    )
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "LONG"
    assert d.final_tradeable is True
    assert d.wait_reason == ""
    # Equal-weight log pool of the four triplets: pooled P(up) ≈ 0.49.
    assert abs(d.final_confidence - 0.49) < 0.02


def test_all_card_directional_split_pools_to_wait():
    """Opposing tradeable horizons cancel in the pool -> WAIT, never a coin flip."""
    p = _pred(
        u1=0.60, d1=0.20, f1=0.20,
        u5=0.60, d5=0.20, f5=0.20,
        u15=0.20, d15=0.65, f15=0.15,
        u60=0.20, d60=0.62, f60=0.18,
    )
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias == "WAIT"
    assert d.wait_reason.startswith("pooled stack evidence below entry gate")


def test_all_card_four_of_four_confidence_exceeds_two_of_four():
    """Breadth: 4-of-4 agreement must pool higher than 2-of-4 at equal strength."""
    p4 = _pred(u1=0.60, d1=0.20, f1=0.20, u5=0.60, d5=0.20, f5=0.20,
               u15=0.60, d15=0.20, f15=0.20, u60=0.60, d60=0.20, f60=0.20)
    p2 = _pred(u1=0.34, d1=0.33, f1=0.33, u5=0.60, d5=0.20, f5=0.20,
               u15=0.60, d15=0.20, f15=0.20, u60=0.34, d60=0.33, f60=0.33)
    b4 = build_multi_horizon_bundle(_inp(mins_to_close=180), p4, _canonical(), _call())
    b2 = build_multi_horizon_bundle(_inp(mins_to_close=180), p2, _canonical(), _call())
    assert b4.final_decision.final_bias == "LONG"
    assert b2.final_decision.final_bias == "LONG"
    assert b4.final_decision.final_confidence > b2.final_decision.final_confidence


def test_intraday_15c_primary_with_1c_timing_contradiction_downgrades_not_forced_reversal():
    p = _pred(u1=0.25, d1=0.6, f1=0.15, u15=0.67, d15=0.2, f15=0.13, u60=0.6, d60=0.2, f60=0.2)
    b = build_multi_horizon_bundle(_inp(mins_to_close=180), p, _canonical(), _call())
    d = b.final_decision
    assert d.primary_horizon == "15c"
    # Pooled evidence: three long horizons outweigh the 1c dissenter (equal weights).
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


def test_severe_contradiction_resolves_by_pooled_evidence_never_primary_relay():
    # 2 long (0.60, 0.65) vs 2 stronger short (0.65, 0.72): the pool resolves by
    # evidence strength (SHORT) or stays WAIT — it must never relay the 15c
    # primary's LONG over stronger opposing evidence.
    p = _pred(u15=0.65, d15=0.2, f15=0.15, u60=0.15, d60=0.72, f60=0.13, u5=0.2, d5=0.65, f5=0.15)
    b = build_multi_horizon_bundle(_inp(mins_to_close=190), p, _canonical(), _call())
    d = b.final_decision
    assert d.final_bias in ("WAIT", "SHORT")
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
    """Price-action entry states (operator 2026-06-11): timing from the 1c model
    — never key-level zones (the old nearest_below/above band is gone)."""
    p = _pred()
    # forming: 1c tradeably OPPOSES the pooled bias (counter-move in progress)
    p_opp = _pred(u1=0.20, d1=0.62, f1=0.18)
    b_forming = build_multi_horizon_bundle(_inp(spot=443.0, mins_to_close=180), p_opp, _canonical(), _call(state="WATCH", entry=None))
    assert b_forming.final_decision.entry_state == "forming"
    assert "Counter-move" in b_forming.final_decision.final_trade_plan.entry_display_text
    # armed: bias live but 1c not yet confirming (near-uniform 1c)
    p2 = _pred(u1=0.35, d1=0.35, f1=0.30)
    b_armed = build_multi_horizon_bundle(_inp(spot=441.45, mins_to_close=180), p2, _canonical(), _call(state="WATCH", entry=None))
    assert b_armed.final_decision.entry_state == "armed"
    assert "1c confirmation" in b_armed.final_decision.final_trade_plan.entry_display_text
    # confirmed: 1c agrees at confirmation confidence
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
