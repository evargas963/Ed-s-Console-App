"""Action 11.9: call_engine.py fail-closed on missing index quotes + fusion posteriors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from call_engine import (
    _cross_instrument_signal,
    _index_basket_vote,
    _validate_trade,
    compute_call,
)
from math_exposure_core import greek_bias
from signal_types import CanonicalForecast, PredictiveCard, RulesCard, SignalInput
from tests.mvp_test_fixtures import minimal_mvp_features

ROOT = Path(__file__).resolve().parent.parent
CALL_ENGINE = (ROOT / "call_engine.py").read_text(encoding="utf-8")

_FORBIDDEN_CALL_ENGINE_PATTERNS = (
    '(exp or 0) >= (cont or 0)',
    'float(etf_chg_pct or 0.0)',
    'inp.spy_chg_pct or 0.0',
    'inp.qqq_chg_pct or 0.0',
    'inp.iwm_chg_pct or 0.0',
    "return \"neutral\"  # not enough movement",
    "getattr(fusion, 'reversal_posterior', 0.0)",
    "getattr(fusion, 'continuation_posterior', 0.0)",
    "getattr(fusion, 'breakout_posterior', 0.0)",
    'inp.net_delta or 0.0',
    "getattr(fusion, 'model_agreement', 0.5)",
)

_DEFERRED_11_9B_PATTERNS: tuple[str, ...] = ()


def _minimal_inp(**overrides) -> SignalInput:
    base = dict(
        ticker="SPY",
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="pin_bull",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=452.0,
        put_gamma_wall=448.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=2.0,
        dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=452.0,
        nearest_above_dist=2.0,
        nearest_below_name="PGW",
        nearest_below_val=448.0,
        nearest_below_dist=2.0,
        net_gamma=1000.0,
        net_delta=200.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="neutral",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=1.0,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.05,
        qqq_chg_pct=0.04,
        iwm_chg_pct=0.03,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.0,
        order_flow_direction="neutral",
        order_flow_readiness="yellow",
    )
    base.update(overrides)
    return SignalInput(**base)


def test_call_engine_file_has_no_fail_open_high_priority_patterns():
    for pattern in _FORBIDDEN_CALL_ENGINE_PATTERNS:
        assert pattern not in CALL_ENGINE, f"fail-open pattern still present: {pattern}"


def test_index_label_none_when_all_three_indexes_missing():
    inp = _minimal_inp(spy_chg_pct=None, qqq_chg_pct=None, iwm_chg_pct=None)
    assert _cross_instrument_signal(inp) is None


def test_etf_chg_pct_none_does_not_fabricate_vote_from_zero():
    assert _index_basket_vote(None, None) == 0


def test_fusion_posterior_gate_blocks_long_when_reversal_posterior_missing():
    fusion = SimpleNamespace(available=True, model_agreement=0.9, n_sources_active=3)
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.5,
        probability_down=0.25,
        probability_flat=0.25,
        confidence="medium",
        provenance="test",
    )
    result = _validate_trade(
        final_signal="long",
        inp=_minimal_inp(),
        micro_regime="trend_up",
        micro=SimpleNamespace(is_compressing=False),
        pred={},
        fusion=fusion,
        canonical=canonical,
        regime=SimpleNamespace(primary="trend_continuation"),
        regime_label="trend_continuation",
    )
    assert result["probability_valid"] is False
    assert "reversal posterior unavailable" in result["probability_reason"]


def test_fusion_posterior_gate_blocks_short_when_posteriors_missing():
    fusion = SimpleNamespace(available=True, model_agreement=0.9, n_sources_active=3)
    canonical = CanonicalForecast(
        direction="down",
        probability_up=0.25,
        probability_down=0.5,
        probability_flat=0.25,
        confidence="medium",
        provenance="test",
    )
    result = _validate_trade(
        final_signal="short",
        inp=_minimal_inp(),
        micro_regime="trend_down",
        micro=SimpleNamespace(is_compressing=False),
        pred={},
        fusion=fusion,
        canonical=canonical,
        regime=SimpleNamespace(primary="trend_continuation"),
        regime_label="trend_continuation",
    )
    assert result["probability_valid"] is False
    assert "continuation/breakout posteriors unavailable" in result["probability_reason"]


def _fusion_for_call(**overrides):
    base = dict(
        available=True,
        dominant_direction="up",
        fusion_dominant_direction="up",
        model_agreement=0.72,
        n_sources_active=2,
        fusion_confidence="medium",
        reversal_posterior=0.25,
        continuation_posterior=0.2,
        breakout_posterior=0.2,
        mc_available=True,
        mc_containment=0.45,
        mc_expansion=0.4,
        mc_eae=0.8,
        mc_efe=1.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_net_delta_none_propagates_to_call_sizing_decision():
    inp_with = _minimal_inp(net_delta=500.0)
    inp_without = _minimal_inp(net_delta=None)
    assert greek_bias(inp_with.net_delta, inp_with.charm_direction, inp_with.put_call_oi_ratio,
                      dex_magnitude=inp_with.dex_magnitude, charm_magnitude=inp_with.charm_magnitude) == "bullish"
    assert greek_bias(inp_without.net_delta, inp_without.charm_direction, inp_without.put_call_oi_ratio,
                      dex_magnitude=inp_without.dex_magnitude, charm_magnitude=inp_without.charm_magnitude) == "neutral"

    rules = RulesCard(
        headline="Test",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#fff",
        signal="long",
        conviction="medium",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP",
            structure_support=448.0,
            structure_resist=452.0,
            bos=None,
            sweeps=[],
            last_sweep=None,
            is_compressing=False,
            compression_bars=0,
        ),
    )
    pred = PredictiveCard(
        headline="Lean UP",
        prediction_dir="up",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.55,
        empirical_confidence="medium",
        forward_direction="up",
        forward_prob_up=0.55,
        forward_prob_down=0.25,
        forward_prob_flat=0.20,
        forward_confidence="medium",
        forward_provenance="test",
        samples_used=40,
        model_note="test",
        timeframe_reads={},
        up_prob_5c=0.55, down_prob_5c=0.25, flat_prob_5c=0.20,
    )
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.55,
        probability_down=0.25,
        probability_flat=0.20,
        confidence="medium",
        provenance="test",
    )
    regime = SimpleNamespace(primary="trend_continuation", confidence="medium")
    vol_regime = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
    )
    kwargs = dict(
        rules=rules,
        pred=pred,
        regime=regime,
        fusion=_fusion_for_call(),
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    call_with = compute_call(inp_with, **kwargs)
    call_without = compute_call(inp_without, **kwargs)
    assert call_with.confluence_count > call_without.confluence_count
    assert "Greeks" in call_with.confluence_detail
    assert "Greeks" not in call_without.confluence_detail
