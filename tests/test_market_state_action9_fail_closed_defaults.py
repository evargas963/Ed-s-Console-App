"""Action 9: MarketState must not fabricate validation, forward, fusion, or vol-regime defaults."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from market_state import MarketState, build_market_state, derive_zone


def test_market_state_unpopulated_fields_are_none_not_sentinels():
    ms = MarketState()
    assert ms.validation_passed is None
    assert ms.structure_valid is None
    assert ms.forward_prob_up is None
    assert ms.forward_prob_down is None
    assert ms.forward_prob_flat is None
    assert ms.vol_regime_conviction_mult is None
    assert ms.vol_regime_risk_mult is None
    assert ms.fusion_dominant_prob is None
    assert ms.fusion_prob_up is None
    assert ms.fusion_breakout is None


def test_derive_zone_expansion_without_net_delta_is_pin_neutral():
    assert derive_zone("expansion", None) == "pin_neutral"
    assert derive_zone("expansion", 0.0) == "breakout"
    assert derive_zone("expansion", -1.0) == "breakdown"


@patch("signals.compute_signals")
def test_build_market_state_call_validation_defaults_fail_closed(mock_cs):
    mock_cs.return_value = MagicMock(
        rules=None,
        call=SimpleNamespace(
            signal="wait",
            conviction="low",
            entry=None,
            stop=None,
            target=None,
            target2=None,
            reward_risk=None,
            reward_risk2=None,
            headline="",
            reasoning="",
            rules_pred_agree=False,
            time_warning=None,
            size_note="",
        ),
        predictive=None,
        fusion=None,
        vol_regime=None,
        regime=None,
        stack_decision_path=None,
        multi_horizon_bundle=None,
        calibration_payload=None,
    )
    ms = build_market_state(
        ticker="SPY",
        selected_exp="2026-06-20",
        session_label="RTH",
        spot=100.0,
        bid=99.9,
        ask=100.1,
        consensus_summary=None,
        contracts_use=[],
        walls=[],
        totals=[],
        price_levels=MagicMock(vwap=None, today_open=None, today_high=None, today_low=None),
        mkt_ctx=MagicMock(
            spy_chg_pct=0.1,
            qqq_chg_pct=0.1,
            iwm_chg_pct=0.1,
            vix=None,
            pcr=None,
            pcr_arrow="",
            pcr_color="",
            pcr_label="",
            vix_regime="",
            vix_color="",
            vix_implication="",
            confluence=None,
            qqq_confluence=None,
        ),
        live_on=True,
        zone_since_bars=0,
        prev_zone=None,
    )
    assert ms.validation_passed is None
    assert ms.structure_valid is None


@patch("signals.compute_signals")
def test_build_market_state_fusion_probs_no_sentinel_defaults(mock_cs):
    fusion = MagicMock()
    fusion.available = True
    fusion.dominant_outcome = "breakout"
    fusion.fusion_confidence = "high"
    fusion.fusion_summary = "ok"
    fusion.model_agreement_label = "high"
    fusion.n_sources_active = 3
    fusion.dominant_direction = "up"
    fusion.evidence_summary = []
    fusion.contradiction_summary = []
    fusion.fusion_mc_contribution = None
    fusion.mc_available = False
    # Omit prob_* and posteriors — must stay None on MarketState
    for attr in (
        "dominant_probability",
        "fusion_confidence_score",
        "breakout_posterior",
        "prob_up",
        "prob_down",
        "prob_flat",
        "model_agreement",
    ):
        if hasattr(fusion, attr):
            delattr(fusion, attr)

    mock_cs.return_value = MagicMock(
        rules=None,
        call=None,
        predictive=None,
        fusion=fusion,
        vol_regime=None,
        regime=None,
        stack_decision_path=None,
        multi_horizon_bundle=None,
        calibration_payload=None,
    )
    ms = build_market_state(
        ticker="SPY",
        selected_exp="2026-06-20",
        session_label="RTH",
        spot=100.0,
        bid=99.9,
        ask=100.1,
        consensus_summary=None,
        contracts_use=[],
        walls=[],
        totals=[],
        price_levels=MagicMock(vwap=None, today_open=None, today_high=None, today_low=None),
        mkt_ctx=MagicMock(
            spy_chg_pct=0.1,
            qqq_chg_pct=0.1,
            iwm_chg_pct=0.1,
            vix=None,
            pcr=None,
            pcr_arrow="",
            pcr_color="",
            pcr_label="",
            vix_regime="",
            vix_color="",
            vix_implication="",
            confluence=None,
            qqq_confluence=None,
        ),
        live_on=True,
        zone_since_bars=0,
        prev_zone=None,
    )
    assert ms.fusion_available is True
    assert ms.fusion_prob_up is None
    assert ms.fusion_dominant_prob is None
