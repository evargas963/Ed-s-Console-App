"""Action 12.x Layer 5: upstream engines fail-closed (MC, fusion, adjustment, signals)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import monte_carlo

ROOT = Path(__file__).resolve().parent.parent


def test_mc_feature_dict_omits_missing_features():
    out = monte_carlo.MonteCarloOutput(available=True, simulation_ok=True, fallback_used=False)
    fd = out.mc_feature_dict()
    assert "directional_bias" not in fd
    assert "tail_risk" not in fd
    assert fd["source"] == "derived_mc_normalized"








def test_bayesian_update_skips_missing_evidence_keys():
    from bayesian_fusion import _bayesian_update

    priors = {"a": 0.5, "b": 0.5}
    only_a = _bayesian_update(priors, [{"a": 0.99}], [1.0])
    with_neutral_b = _bayesian_update(priors, [{"a": 0.99, "b": 0.5}], [1.0])
    assert only_a["b"] > with_neutral_b["b"]


def test_resolved_regime_label_none_for_unknown_primary():
    from bayesian_fusion import _resolved_regime_label

    assert _resolved_regime_label(SimpleNamespace(primary="unknown")) is None
    assert _resolved_regime_label(SimpleNamespace(primary="pinning")) == "pinning"


def test_lstm_evidence_empty_when_support_attrs_missing():
    from bayesian_fusion import _translate_lstm_evidence

    m = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
    )
    assert _translate_lstm_evidence(m, "wait") == {}




