"""call_engine Layer 5 chunk-2C: CE1/CE2/CE9 audit-trail log emission."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import call_engine as ce
from signal_types import CanonicalForecast, PredictiveCard, RulesCard
from tests.mvp_test_fixtures import minimal_mvp_features
from tests.test_call_engine_chunk1_fail_closed import _strong_long_stack_input


def _rules_long() -> RulesCard:
    return RulesCard(
        headline="trend",
        headline_1m="trend",
        detail="",
        zone_label="BREAKOUT",
        zone_color="#0f0",
        signal="long",
        conviction="high",
        alerts=[],
        micro=None,
    )


def _pred() -> PredictiveCard:
    return PredictiveCard(
        headline="",
        prediction_dir="up",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.6,
        empirical_confidence="medium",
        forward_direction="up",
        forward_prob_up=0.6,
        forward_prob_down=0.2,
        forward_prob_flat=0.2,
        forward_confidence="high",
        forward_provenance="fusion",
        samples_used=10,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.7,
        down_prob_5c=0.15,
        flat_prob_5c=0.15,
    )


def _canonical(*, confidence: str = "high") -> CanonicalForecast:
    return CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence=confidence,
        provenance="fusion",
    )


def test_ce1_stop_distance_logs_when_session_time_missing(caplog):
    inp = SimpleNamespace(spot=450.0, et_hour=None, et_minute=None, vix_level=20.0)
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._stop_distance(inp)
    assert any("et_hour/et_minute missing" in r.message for r in caplog.records)


def test_ce2_conviction_logs_invalid_confidence_substitution(caplog):
    canonical = _canonical(confidence="not_a_tier")
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._conviction_from_canonical_forecast(
            canonical,
            pred_agrees=True,
            final_signal="long",
        )
    assert any("invalid confidence" in r.message for r in caplog.records)


def test_ce2_conviction_logs_dominant_probability_fallback(caplog):
    canonical = _canonical()

    def _boom():
        raise TypeError("bad triplet")

    canonical.dominant_probability = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._conviction_from_canonical_forecast(
            canonical,
            pred_agrees=True,
            final_signal="long",
        )
    assert any("dominant_probability unavailable" in r.message for r in caplog.records)


def test_ce9_call_readiness_failure_logs_warning(caplog):
    inp = _strong_long_stack_input()
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
    with patch(
        "setup_readiness.compute_call_readiness",
        side_effect=RuntimeError("readiness module broken"),
    ):
        with caplog.at_level(logging.WARNING, logger="call_engine"):
            ce.compute_call(
                inp,
                _rules_long(),
                _pred(),
                regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
                fusion=fusion,
                vol_regime=vol,
                canonical=_canonical(),
                mvp_features=minimal_mvp_features(zone="breakout"),
                mh_policy=None,
            )
    assert any(r.levelname == "WARNING" and "call_readiness:" in r.message for r in caplog.records)


def test_ce9_put_readiness_failure_logs_warning(caplog):
    inp = _strong_long_stack_input()
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
    with patch(
        "setup_readiness.compute_call_readiness",
        return_value={
            "readiness_score": 50,
            "call_state": "WAIT",
            "forecast_state": "dormant",
            "reasons": [],
            "missing_conditions": [],
            "component_scores": {},
        },
    ), patch(
        "setup_readiness.compute_put_readiness",
        side_effect=RuntimeError("put readiness module broken"),
    ):
        with caplog.at_level(logging.WARNING, logger="call_engine"):
            ce.compute_call(
                inp,
                _rules_long(),
                _pred(),
                regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
                fusion=fusion,
                vol_regime=vol,
                canonical=_canonical(),
                mvp_features=minimal_mvp_features(zone="breakout"),
                mh_policy=None,
            )
    assert any(r.levelname == "WARNING" and "put_readiness:" in r.message for r in caplog.records)
