"""Parity tests for FusionTickCache (shared per-tick fusion prep across horizons)."""

from types import SimpleNamespace

import bayesian_fusion


def _sample_outputs():
    xgb = SimpleNamespace(
        available=True,
        prob_up=0.4,
        prob_down=0.35,
        prob_flat=0.25,
        dominant_class="up",
        confidence_label="medium",
        continuation_support=0.2,
        reversal_support=0.1,
    )
    lstm = SimpleNamespace(
        available=True,
        prob_up=0.38,
        prob_down=0.37,
        prob_flat=0.25,
        continuation_support=0.18,
        reversal_support=0.12,
    )
    tr = SimpleNamespace(
        available=False,
        prob_up=0.33,
        prob_down=0.33,
        prob_flat=0.34,
        continuation_support=0.0,
        reversal_support=0.0,
    )
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.55,
        expansion_prob=0.45,
        n_paths=1000,
        horizon_bars=20,
        assumptions={"garch_active": False, "blended_sigma": 1.2},
    )
    return xgb, lstm, tr, mc


def test_fuse_with_fusion_tick_cache_matches_baseline():
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    xgb, lstm, tr, mc = _sample_outputs()
    sl = {"meta.n_bars": 30}

    baseline = bayesian_fusion.fuse(
        regime, xgb, lstm, tr, mc, rules, signal_layer_v1=sl
    )
    cache = bayesian_fusion.build_fusion_tick_cache(regime, rules)
    cached = bayesian_fusion.fuse(
        regime,
        xgb,
        lstm,
        tr,
        mc,
        rules,
        signal_layer_v1=sl,
        fusion_tick_cache=cache,
    )
    assert baseline == cached


def test_fusion_tick_cache_fields_match_direct_lookups():
    regime = SimpleNamespace(primary="breakout", confidence="high")
    rules = SimpleNamespace(signal="long", conviction="high")
    cache = bayesian_fusion.build_fusion_tick_cache(regime, rules)

    assert cache.regime_label == "breakout"
    assert cache.direction_hint == "long"
    assert cache.priors == bayesian_fusion.REGIME_PRIORS["breakout"]
    assert cache.weight_adjustments == bayesian_fusion.REGIME_WEIGHT_ADJUSTMENTS["breakout"]
    assert cache.rules_evidence == bayesian_fusion._translate_rules_evidence(rules, regime)
