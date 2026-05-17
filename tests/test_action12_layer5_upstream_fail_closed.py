"""Action 12.x Layer 5: upstream engines fail-closed (MC, fusion, adjustment, signals)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import monte_carlo
from bayesian_fusion import FusionPayload, _model_direction_triplet, fuse
from mc_fusion_adjustment import fuse_payload_apply_mc_adjustment, normalize_mc
from signals import canonical_forecast_from_fusion

ROOT = Path(__file__).resolve().parent.parent


def test_mc_feature_dict_omits_missing_features():
    out = monte_carlo.MonteCarloOutput(available=True, simulation_ok=True, fallback_used=False)
    fd = out.mc_feature_dict()
    assert "directional_bias" not in fd
    assert "tail_risk" not in fd
    assert fd["source"] == "derived_mc_normalized"


def test_normalize_mc_returns_none_when_feature_missing():
    assert normalize_mc({"expected_move": 1.0, "volatility": 0.5}, 100.0) is None


def test_fusion_payload_defaults_are_none_not_fabricated():
    p = FusionPayload(available=False)
    assert p.reversal_posterior is None
    assert p.prob_up is None
    assert p.dominant_outcome is None


def test_model_triplet_none_when_probs_missing_on_available_model():
    m = SimpleNamespace(available=True, prob_up=0.5, prob_down=None, prob_flat=0.5)
    assert _model_direction_triplet(m) is None


def test_fuse_directional_none_when_models_unavailable():
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    off = SimpleNamespace(available=False)
    mc = SimpleNamespace(available=False)
    r = fuse(regime, off, off, off, mc, rules)
    assert r.available is True
    assert r.prob_up is None
    assert r.reversal_posterior is not None


def test_canonical_forecast_missing_directional_triplet():
    fusion = SimpleNamespace(
        available=True,
        prob_up=None,
        prob_down=None,
        prob_flat=None,
    )
    c = canonical_forecast_from_fusion(fusion)
    assert c.provenance == "fusion_directional_missing"


def test_mc_post_fusion_skips_when_mc_features_incomplete():
    fusion = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
    )
    mc = SimpleNamespace(
        available=True,
        mc_feature_dict=lambda: {"expected_move": 1.0, "source": "derived_mc_normalized"},
    )
    out = fuse_payload_apply_mc_adjustment(fusion, mc, 100.0)
    assert out.prob_up == 0.5
