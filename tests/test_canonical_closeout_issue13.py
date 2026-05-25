"""Issue 13 closeout: canonical-driven conviction + fusion-unavailable WAIT policy."""
from __future__ import annotations

import sys
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from tests.mvp_test_fixtures import minimal_mvp_features


def _inp_bullish_stack():
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
        dist_call_oi_wall=None, dist_put_oi_wall=None,
        dist_call_vanna_wall=None, dist_put_vanna_wall=None,
        nearest_above_name="CGW", nearest_above_val=452.0, nearest_above_dist=2.0,
        nearest_below_name="PGW", nearest_below_val=448.0, nearest_below_dist=2.0,
        net_gamma=1000.0, net_delta=500.0, net_vanna=None,
        charm_net=None, charm_direction="buying", charm_drift_toward=450.0,
        charm_magnitude="moderate", dex_magnitude="moderate",
        iv_level=0.15, iv_direction="flat", realized_vol=None, atr=1.5,
        put_call_oi_ratio=0.9, oi_center=None,
        recent_crosses=[], ceiling_tests_today=0, floor_tests_today=0,
        spy_chg_pct=0.3, qqq_chg_pct=0.35, iwm_chg_pct=0.25,
        vix_level=18.0, mins_to_close=120.0,
        em_upper=452.0, em_lower=448.0,
        order_flow_score=0.2, order_flow_direction="bullish", order_flow_readiness="yellow",
    )


def test_fusion_unavailable_provenance_forces_wait_even_when_stack_aligns():
    """Uniform posterior / fusion off → no directional The Call (provenance-driven)."""
    from call_engine import compute_call
    from signal_types import RulesCard, PredictiveCard, CanonicalForecast

    u = 1.0 / 3.0
    canonical = CanonicalForecast(
        direction="flat",
        probability_up=u,
        probability_down=u,
        probability_flat=u,
        confidence="low",
        provenance="fusion_unavailable",
    )
    rules = RulesCard(
        headline="Risk-on tape",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#fff",
        signal="long",
        conviction="high",
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
        headline="—",
        prediction_dir="flat",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.45,
        empirical_confidence="low",
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=30,
        model_note="test",
        timeframe_reads={},
    )
    regime = SimpleNamespace(primary="trend_continuation", confidence="medium")
    fusion = SimpleNamespace(available=False)
    vol_regime = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )
    call = compute_call(
        _inp_bullish_stack(),
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    assert call.signal == "wait", f"expected WAIT when fusion unavailable; got {call.signal!r}"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("reason") == "canonical_provenance", call.wait_blocker


def test_conviction_tier_from_canonical_not_stack_confluence():
    """High stack agreement must not produce high conviction if canonical is only low-tier."""
    from call_engine import compute_call
    from signal_types import RulesCard, PredictiveCard, CanonicalForecast

    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.36,
        probability_down=0.32,
        probability_flat=0.32,
        confidence="high",
        provenance="bayesian_fusion",
    )
    rules = RulesCard(
        headline="Test",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#fff",
        signal="long",
        conviction="high",
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
        headline="x",
        prediction_dir="up",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.36,
        empirical_confidence="low",
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=40,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.36, down_prob_5c=0.32, flat_prob_5c=0.32,
    )
    regime = SimpleNamespace(primary="trend_continuation", confidence="high")
    fusion = SimpleNamespace(
        available=True,
        dominant_direction="up",
        fusion_dominant_direction="up",
        model_agreement=0.9,
        n_sources_active=3,
        fusion_confidence="high",
        reversal_posterior=0.2,
        continuation_posterior=0.2,
        breakout_posterior=0.2,
        mc_available=True,
        mc_containment=0.4,
        mc_expansion=0.5,
        mc_eae=0.8,
        mc_efe=1.0,
    )
    vol_regime = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )
    call = compute_call(
        _inp_bullish_stack(),
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    assert call.signal == "long", "fixture should stack long with pred_agrees"
    assert call.conviction == "low", (
        f"marginal probability ~flat vs 1/3 → base tier low; got conviction={call.conviction!r}"
    )


def test_dominant_probability_returns_none_for_non_tradable_provenance():
    """LIVE-UI-A producer-side close: CanonicalForecast.dominant_probability() returns
    Optional[float] = None for any provenance ∉ TRADABLE_CANONICAL_PROVENANCE.

    The dataclass holds placeholder 1/3-each triplets for non-tradable cases (intentional
    fail-closed carrier shape from canonical_forecast_from_fusion). Returning the raw 0.333
    from the method lets ungated callers treat it as a real probability (>= threshold
    comparisons fire spuriously). Returning None forces explicit caller handling — any
    site that drops the gate fails loudly (TypeError on float comparison) instead of
    silently leaking the placeholder.
    """
    from signal_types import CanonicalForecast, NON_TRADABLE_CANONICAL_PROVENANCE, TRADABLE_CANONICAL_PROVENANCE

    # Every known non-tradable provenance must return None.
    for prov in NON_TRADABLE_CANONICAL_PROVENANCE:
        cf = CanonicalForecast(
            direction="up",
            probability_up=1 / 3,
            probability_down=1 / 3,
            probability_flat=1 / 3,
            confidence="low",
            provenance=prov,
        )
        assert cf.dominant_probability() is None, (
            f"non-tradable provenance {prov!r} leaked dominant_probability() = {cf.dominant_probability()!r}"
        )

    # debug_override:* class is also non-tradable per signals._debug_canonical_override.
    cf_debug = CanonicalForecast(
        direction="up",
        probability_up=0.8,  # operator-chosen direction with non-tradable provenance
        probability_down=0.1,
        probability_flat=0.1,
        confidence="high",
        provenance="debug_override:operator_force_up",
    )
    assert cf_debug.dominant_probability() is None, (
        "debug_override:* provenance leaked dominant_probability — operator-forced direction "
        "must NOT surface as a real prob"
    )

    # Empty / missing / unknown provenance also blocked.
    for prov in ("", "canonical_forecast_missing", "rules_only", "unknown_source"):
        cf = CanonicalForecast(
            direction="up",
            probability_up=0.7,
            probability_down=0.2,
            probability_flat=0.1,
            confidence="medium",
            provenance=prov,
        )
        assert cf.dominant_probability() is None, (
            f"unknown provenance {prov!r} leaked dominant_probability() — fail-closed allow-list bypassed"
        )

    # Tradable provenance must still return the real dominant probability.
    cf_ok = CanonicalForecast(
        direction="up",
        probability_up=0.62,
        probability_down=0.25,
        probability_flat=0.13,
        confidence="medium",
        provenance="bayesian_fusion",
    )
    assert cf_ok.dominant_probability() == 0.62, (
        f"tradable bayesian_fusion canonical did not return real dominant prob: "
        f"{cf_ok.dominant_probability()!r}"
    )

    # Lock the predicate identity: tradable allow-list is the SOLE positive set.
    assert TRADABLE_CANONICAL_PROVENANCE == frozenset({"bayesian_fusion"}), (
        "TRADABLE_CANONICAL_PROVENANCE expanded — re-audit every dominant_probability() caller "
        "before adding a new tradable provenance value"
    )
