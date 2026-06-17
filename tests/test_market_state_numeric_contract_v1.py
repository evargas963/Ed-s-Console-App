"""FIND-MS-1..10 paired-fix — numeric_contract across build_market_state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from market_state import _f_ms, _ms_price_disp, build_market_state
from tests.test_build_market_state_spot_fail_closed import _base_kwargs, _fake_compute_signals


def _sig_out_with_pred(**pred_kw):
    pred = SimpleNamespace(
        headline="test",
        horizon_prob_bars=None,
        eval_accuracy_oos=None,
        eval_log_loss_oos=None,
        eval_pnl_realized_contract_oos=None,
        eval_realized_contract_metrics_oos=None,
        forward_prob_up=pred_kw.get("forward_prob_up"),
        forward_prob_down=pred_kw.get("forward_prob_down", 0.2),
        forward_prob_flat=pred_kw.get("forward_prob_flat", 0.2),
        forward_direction="up",
        forward_confidence="medium",
        forward_provenance="test",
        samples_used=10,
        model_note="",
        model_version="rules_v1",
        model_source=None,
        avg_5c_pts=1.0,
        avg_15c_pts=None,
        avg_60c_pts=None,
        timeframe_reads={},
        reversal_risk=None,
        reversal_label="",
        reversal_shortfall=None,
        reversal_severity="",
        model_outputs=pred_kw.get("model_outputs"),
        up_prob_1c=0.34,
        down_prob_1c=0.34,
        flat_prob_1c=0.34,
        up_prob_5c=0.34,
        down_prob_5c=0.34,
        flat_prob_5c=0.34,
        up_prob_15c=0.34,
        down_prob_15c=0.34,
        flat_prob_15c=0.34,
        up_prob_60c=0.34,
        down_prob_60c=0.34,
        flat_prob_60c=0.34,
        movement_head_probs=None,
        fusion_policy_snapshot_cols=None,
        historical_5c_dominant_dir=None,
        historical_5c_dominant_prob=None,
        empirical_confidence=None,
        mh_prob_source_by_horizon={},
    )

    out = MagicMock()
    out.predictive = pred
    out.canonical_forecast = None
    out.rules = None
    out.call = None
    out.fusion = pred_kw.get("fusion")
    out.vol_regime = pred_kw.get("vol_regime")
    out.regime = None
    out.stack_decision_path = None
    out.multi_horizon_bundle = None
    out.calibration_payload = None
    out.pred_override_source = None
    return out


@patch("signals.compute_signals")
def test_nan_spot_degraded_no_signals_and_disp_em_dash(mock_cs):
    mock_cs.side_effect = _fake_compute_signals
    ms = build_market_state(**_base_kwargs(spot=float("nan")))
    assert ms.spot_disp == "—"
    assert "Spot unavailable" in ms.call_headline
    mock_cs.assert_not_called()


@patch("signals.compute_signals")
def test_mc_iv_level_nan_skips_positive_gate(mock_cs):
    mock_cs.side_effect = _fake_compute_signals
    build_market_state(**_base_kwargs(mc_iv_level=float("nan")))
    inp = mock_cs.call_args[0][0]
    assert inp.iv_level is None


@patch("signals.compute_signals")
def test_forward_prob_nan_surfaces_none_on_ms(mock_cs):
    mock_cs.return_value = _sig_out_with_pred(forward_prob_up=float("nan"))
    ms = build_market_state(**_base_kwargs())
    assert ms.forward_prob_up is None


@patch("signals.compute_signals")
def test_fusion_prob_nan_surfaces_none(mock_cs):
    fusion = SimpleNamespace(
        available=True,
        dominant_outcome="breakout",
        dominant_probability=0.6,
        fusion_confidence="medium",
        fusion_confidence_score=0.5,
        fusion_summary="",
        breakout_posterior=0.2,
        pinning_posterior=0.2,
        continuation_posterior=0.2,
        reversal_posterior=0.2,
        vol_expansion_posterior=0.1,
        mean_reversion_posterior=0.1,
        model_agreement=0.8,
        model_agreement_label="high",
        n_sources_active=3,
        prob_up=float("nan"),
        prob_down=0.2,
        prob_flat=0.2,
        dominant_direction="up",
        evidence_summary=[],
        contradiction_summary=[],
        fusion_mc_contribution=None,
        mc_available=False,
    )
    mock_cs.return_value = _sig_out_with_pred(fusion=fusion)
    ms = build_market_state(**_base_kwargs())
    assert ms.fusion_available is True
    assert ms.fusion_prob_up is None


@patch("signals.compute_signals")
def test_ml_layer_probs_nan_returns_none(mock_cs):
    model_outputs = {
        "xgb": {
            "available": True,
            "up": float("nan"),
            "down": 0.3,
            "flat": 0.2,
            "dominant": "up",
            "confidence": "high",
            "approved": True,
        },
        "lstm": {"available": False},
        "transformer": {"available": False},
    }
    mock_cs.return_value = _sig_out_with_pred(model_outputs=model_outputs)
    ms = build_market_state(**_base_kwargs())
    assert ms.ml_layer_probs["xgb"] is None


@patch("signals.compute_signals")
def test_vol_regime_nan_multipliers_none(mock_cs):
    vr = SimpleNamespace(
        vol_regime="elevated",
        summary="test",
        conviction_multiplier=float("nan"),
        risk_multiplier=float("inf"),
    )
    mock_cs.return_value = _sig_out_with_pred(vol_regime=vr)
    ms = build_market_state(**_base_kwargs())
    assert ms.vol_regime_conviction_mult is None
    assert ms.vol_regime_risk_mult is None


@patch("signals.compute_signals")
def test_call_display_nan_entry_em_dash(mock_cs):
    call = SimpleNamespace(
        signal="long",
        conviction="high",
        entry=float("nan"),
        stop=440.0,
        target=445.0,
        target2=None,
        reward_risk=2.0,
        headline="test",
        reasoning="test",
        rules_pred_agree=True,
        time_warning="",
        size_note="",
    )
    out = _sig_out_with_pred()
    out.call = call
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.entry_disp == "—"


@patch("market_state.recommend_option_expression", return_value=("nan CALL", None, {}))
@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_rec_strike_non_finite_sets_no_trade(_mock_cs, _mock_oe):
    ms = build_market_state(**_base_kwargs())
    assert ms.is_no_trade is True
    assert ms.rec_strike is None


@patch("signals.compute_signals")
def test_final_confidence_nan_none(mock_cs):
    bundle = MagicMock()
    bundle.final_decision = MagicMock(final_confidence=float("nan"))
    out = _sig_out_with_pred()
    out.multi_horizon_bundle = bundle
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.final_confidence is None


def test_f_ms_and_price_disp_helpers():
    assert _f_ms(float("nan")) is None
    assert _f_ms(float("inf")) is None
    assert _f_ms(441.25) == pytest.approx(441.25)
    assert _ms_price_disp(float("nan")) == "—"
    assert _ms_price_disp(441.25) == "441.25"
