"""call_engine Layer 5 chunk-2B: CE3, CE4, CE6, CE8 (+ CE7 sizing None)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


from call_engine import _validate_trade, compute_call, compute_position_size
from signal_types import CanonicalForecast, PredictiveCard, RulesCard
from tests.mvp_test_fixtures import minimal_mvp_features
from tests.test_call_engine_chunk1_fail_closed import _strong_long_stack_input


class _FusionPosteriorError:
    available = True
    stack_directional_authorized = True
    prob_up = 0.6
    prob_down = 0.2
    prob_flat = 0.2

    @property
    def reversal_posterior(self):
        raise ValueError("malformed posterior")


def test_validate_trade_fusion_gate_exception_fails_probability_layer():
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    inp = SimpleNamespace(
        ticker="SPY",
        spot=450.0,
        call_gamma_wall=None,
        put_gamma_wall=None,
        vix_level=20.0,
    )
    result = _validate_trade(
        final_signal="long",
        inp=inp,
        micro_regime="TREND_UP",
        micro=None,
        pred=None,
        fusion=_FusionPosteriorError(),
        canonical=canonical,
        regime=None,
        regime_label="trend_continuation",
        vol_regime=None,
    )
    assert result["probability_valid"] is False
    assert "fusion posterior gate error" in result["probability_reason"]


def test_validate_trade_eae_gate_uses_vol_regime_risk_multiplier():
    inp = SimpleNamespace(ticker="SPY", spot=450.0, call_gamma_wall=None, put_gamma_wall=None, vix_level=20.0)
    fusion = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.6,
        prob_down=0.2,
        prob_flat=0.2,
        mc_available=True,
        mc_eae=100.0,
    )
    vol = SimpleNamespace(vol_regime="unstable", risk_multiplier=1.5)
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    with patch("call_engine._stop_distance", return_value=2.0) as stop_fn:
        _validate_trade(
            final_signal="long",
            inp=inp,
            micro_regime="TREND_UP",
            micro=None,
            pred=None,
            fusion=fusion,
            canonical=canonical,
            regime=None,
            regime_label="trend_continuation",
            vol_regime=vol,
        )
    stop_fn.assert_called_once()
    assert stop_fn.call_args.kwargs.get("risk_multiplier") == 1.5


def test_compute_position_size_none_mins_to_close_is_no_trade():
    out = compute_position_size(
        signal="long",
        conviction="high",
        trade_type="trend",
        confluence_count=4,
        confluence_total=9,
        validation_passed=True,
        mins_to_close=None,
    )
    assert out["execution_mode"] == "NO_TRADE"
    assert out["size_cue"] == "SKIP"
    assert "mins_to_close unavailable" in out["reduction_reasons"][0]


def _rules_long() -> RulesCard:
    return RulesCard(
        headline="Stack lean",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#166534",
        signal="long",
        conviction="high",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP",
            structure_support=449.0,
            structure_resist=451.5,
            bos=None,
            sweeps=[],
            last_sweep=None,
        ),
    )


def _pred() -> PredictiveCard:
    return PredictiveCard(
        headline="Lean up",
        prediction_dir="up",
        prediction_target=455.0,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.7,
        empirical_confidence="high",
        forward_direction="up",
        forward_prob_up=0.6,
        forward_prob_down=0.2,
        forward_prob_flat=0.2,
        forward_confidence="high",
        forward_provenance="bayesian_fusion",
        samples_used=10,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.7,
        down_prob_5c=0.15,
        flat_prob_5c=0.15,
    )


def test_compute_call_none_mins_to_close_does_not_crash():
    inp = _strong_long_stack_input()
    inp.mins_to_close = None
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    fusion = SimpleNamespace(
        available=True,
        fusion_dominant_direction="up",
        dominant_direction="up",
        model_agreement=0.8,
        n_sources_active=3,
        fusion_confidence="high",
        mc_available=False,
    )
    vol = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )
    call = compute_call(
        inp,
        _rules_long(),
        _pred(),
        regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
        fusion=fusion,
        vol_regime=vol,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=None,
    )
    assert call.signal == "wait"
    assert call.wait_blocker is not None


def test_compute_call_none_vol_regime_forces_wait():
    inp = _strong_long_stack_input()
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    fusion = SimpleNamespace(
        available=True,
        fusion_dominant_direction="up",
        dominant_direction="up",
        model_agreement=0.8,
        n_sources_active=3,
        fusion_confidence="high",
        mc_available=False,
    )
    call = compute_call(
        inp,
        _rules_long(),
        _pred(),
        regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
        fusion=fusion,
        vol_regime=None,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=None,
    )
    assert call.signal == "wait"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("reason") == "vol_regime"
