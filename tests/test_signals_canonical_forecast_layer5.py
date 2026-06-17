"""Layer 5 signals L91-102: canonical_forecast_from_fusion + non-tradable provenance gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from call_engine import compute_call
from prediction_engine import _forward_probs_from_canonical
from signal_types import NON_TRADABLE_CANONICAL_PROVENANCE, CanonicalForecast
from signals import canonical_forecast_from_fusion, canonical_forward_probs_for_display
from tests.mvp_test_fixtures import minimal_mvp_features
from tests.test_call_engine_chunk1_fail_closed import _strong_long_stack_input
from tests.test_call_engine_layer5_chunk2c import _rules_long, _pred


def test_non_tradable_provenance_includes_directional_missing_and_invalid():
    assert "fusion_directional_missing" in NON_TRADABLE_CANONICAL_PROVENANCE
    assert "fusion_directional_invalid" in NON_TRADABLE_CANONICAL_PROVENANCE
    assert "fusion_unavailable" in NON_TRADABLE_CANONICAL_PROVENANCE


def test_canonical_forecast_fusion_unavailable_placeholder():
    c = canonical_forecast_from_fusion(None)
    assert c.provenance == "fusion_unavailable"
    assert c.probability_up == pytest.approx(1.0 / 3.0)
    assert c.provenance in NON_TRADABLE_CANONICAL_PROVENANCE


def test_canonical_forecast_directional_missing_placeholder():
    fusion = SimpleNamespace(
        available=True,
        prob_up=None,
        prob_down=None,
        prob_flat=None,
    )
    c = canonical_forecast_from_fusion(fusion)
    assert c.provenance == "fusion_directional_missing"
    assert c.probability_flat == pytest.approx(1.0 / 3.0)


def test_forward_probs_withheld_for_non_tradable_canonical():
    c = canonical_forecast_from_fusion(None)
    assert canonical_forward_probs_for_display(c) == (None, None, None)
    assert _forward_probs_from_canonical(c) == (None, None, None)


def test_forward_probs_pass_through_tradable_canonical():
    c = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    assert canonical_forward_probs_for_display(c) == (0.6, 0.2, 0.2)


def test_compute_call_forces_wait_on_directional_missing_when_stack_would_be_long():
    fusion = SimpleNamespace(
        available=True,
        fusion_dominant_direction="up",
        dominant_direction="up",
        model_agreement=0.9,
        n_sources_active=3,
        fusion_confidence="high",
        mc_available=False,
    )
    canonical = canonical_forecast_from_fusion(
        SimpleNamespace(available=True, prob_up=None, prob_down=None, prob_flat=None)
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
        _strong_long_stack_input(),
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
    assert call.wait_blocker.get("provenance") == "fusion_directional_missing"


def test_unavailable_model_namespace_has_none_probs():
    from signals import _unavailable_model_namespace

    ns = _unavailable_model_namespace()
    assert ns.available is False
    assert ns.prob_up is None
    assert ns.prob_down is None
    assert ns.prob_flat is None
