"""The Call stack: prediction layer must count WTS weak leans (low conf + prob>=0.45)."""
from __future__ import annotations

import sys
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from tests.mvp_test_fixtures import minimal_mvp_features


def _inp():
    from signal_types import SignalInput

    return SignalInput(
        ticker="SPY", timeframe="1m", expiry=None, dte=None,
        spot=450.0,
        candle_open=449.5, candle_high=450.2, candle_low=449.3, candle_close=450.0,
        candle_direction="up", candle_body_pts=0.5, candle_range_pts=0.9,
        vwap=449.8, vwap_side="above", vwap_dist_pts=0.2,
        zone="pin_bull", prev_zone="pin_bull",
        zone_since_bars=5, zone_since_bars_1m=5, zone_since_bars_5m=1,
        call_gamma_wall=452.0, put_gamma_wall=448.0, call_delta_wall=None, put_delta_wall=None,
        gamma_inflection=None, delta_inflection=None,
        call_oi_wall=None, put_oi_wall=None, call_vanna_wall=None, put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=2.0, dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None, dist_put_delta_wall=None,
        dist_gamma_inflection=None, dist_delta_inflection=None,
        dist_call_oi_wall=None, dist_put_oi_wall=None, dist_call_vanna_wall=None, dist_put_vanna_wall=None,
        nearest_above_name="CGW", nearest_above_val=452.0, nearest_above_dist=2.0,
        nearest_below_name="PGW", nearest_below_val=448.0, nearest_below_dist=2.0,
        net_gamma=1000.0, net_delta=200.0, net_vanna=None,
        charm_net=None, charm_direction="neutral", charm_drift_toward=450.0,
        charm_magnitude="moderate", dex_magnitude="moderate",
        iv_level=0.15, iv_direction="flat", realized_vol=None, atr=1.5,
        put_call_oi_ratio=1.0, oi_center=None,
        recent_crosses=[], ceiling_tests_today=0, floor_tests_today=0,
        spy_chg_pct=0.05, qqq_chg_pct=0.04, iwm_chg_pct=0.03,
        vix_level=18.0, mins_to_close=240.0,
        em_upper=452.0, em_lower=448.0,
        order_flow_score=0.0, order_flow_direction="neutral", order_flow_readiness="yellow",
    )


def test_low_conf_prediction_lean_counts_for_stack_threshold():
    """Only micro long + weak prediction lean → 2 stack votes → directional signal (not stuck on WAIT)."""
    from call_engine import compute_call
    from signal_types import RulesCard, PredictiveCard, CanonicalForecast

    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.47,
        probability_down=0.30,
        probability_flat=0.23,
        confidence="low",
        provenance="bayesian_fusion",
    )

    rules = RulesCard(
        headline="Test",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#fff",
        signal="long",
        conviction="low",
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
        historical_5c_dominant_prob=0.47,
        empirical_confidence="low",
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=40,
        model_note="weak lean",
        timeframe_reads={},
        up_prob_5c=0.47, down_prob_5c=0.30, flat_prob_5c=0.23,
    )
    regime = SimpleNamespace(primary="trend_continuation", confidence="medium")
    fusion = SimpleNamespace(
        available=True,
        dominant_direction="flat",
        fusion_dominant_direction="flat",
        model_agreement=0.72,
        n_sources_active=2,
        fusion_confidence="low",
        reversal_posterior=0.25,
        continuation_posterior=0.2,
        breakout_posterior=0.2,
        mc_available=True,
        mc_containment=0.45,
        mc_expansion=0.4,
        mc_eae=0.8,
        mc_efe=1.0,
    )
    vol_regime = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
    )

    call = compute_call(
        _inp(),
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    assert call.signal == "long", (
        f"expected long when micro+prediction weak lean reach stack threshold; got {call.signal!r} "
        f"headline={call.headline!r}"
    )


def test_setup_readiness_no_false_positive_on_no_alignment():
    from setup_readiness import compute_call_readiness

    out = compute_call_readiness({
        "regime": "trend_continuation",
        "trend": "bullish",
        "structure_confirmation": "pullback",
        "structure_higher_tf": "uptrend intact",
        "prediction_direction": "up",
        "prediction_dominant_prob": 0.55,
        "confluence_read": "no directional alignment",
        "validation_passed": True,
        "level_proximity": "near",
        "near_support": True,
        "breakout_ready": False,
    })
    cs = out["component_scores"].get("confluence_score", 15)
    assert cs <= 7, (
        "neutral confluence text must not score as 'aligned'; got confluence_score=%s" % cs
    )
