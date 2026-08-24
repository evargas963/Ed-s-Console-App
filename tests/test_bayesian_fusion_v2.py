"""bayesian_fusion posterior math and no-fabricated-certainty locks (v2).

Extends test_bayesian_fusion_fail_closed / _numeric_contract_v1 / _tick_cache:
  - _bayesian_update on hand-computed inputs (exact posteriors),
  - degenerate priors (all-zero -> priors returned, never invented mass),
  - likelihood floor and zero-weight behavior,
  - fuse() end-to-end posterior on a rules-only tick (hand-computed numbers),
  - missing evidence: no directional probs, no agreement, capped confidence —
    fusion never fabricates certainty from absent inputs,
  - Monte Carlo strictly excluded from posterior math (pass-through only),
  - regime "unknown" == regime absent,
  - weighted directional fusion on hand-computed two-model input.

Model outputs are SimpleNamespace stand-ins carrying the exact serve contract
attributes (prob_up/down/flat, continuation_support, ...) — the established
style for this seam (tests/test_fusion_tick_cache.py); no market-data fixture
exists or applies at this layer.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bayesian_fusion import DEFAULT_PRIORS, _bayesian_update, fuse

UNAVAILABLE = SimpleNamespace(available=False)


def _rules_wait():
    return SimpleNamespace(signal="wait", conviction="medium")


def _xgb(up, down, flat, cont=0.2, rev=0.1, conf="medium"):
    return SimpleNamespace(
        available=True,
        prob_up=up,
        prob_down=down,
        prob_flat=flat,
        continuation_support=cont,
        reversal_support=rev,
        confidence_label=conf,
        dominant_class="up",
    )


# ── _bayesian_update: hand-computed posterior math ───────────────────────────

def test_update_weight_one_is_exact_prior_times_likelihood():
    priors = {"a": 0.5, "b": 0.5}
    out = _bayesian_update(priors, [{"a": 0.8, "b": 0.2}], [1.0])
    # a: .5*.8=.4, b: .5*.2=.1 -> normalized .8/.2
    assert out["a"] == pytest.approx(0.8)
    assert out["b"] == pytest.approx(0.2)


def test_update_weight_half_takes_square_root_of_likelihood():
    priors = {"a": 0.5, "b": 0.5}
    out = _bayesian_update(priors, [{"a": 0.8, "b": 0.2}], [0.5])
    # sqrt(.8)/sqrt(.2) = 2 exactly -> a=2/3, b=1/3
    assert out["a"] == pytest.approx(2.0 / 3.0)
    assert out["b"] == pytest.approx(1.0 / 3.0)


def test_update_zero_weight_evidence_changes_nothing():
    priors = {"a": 0.7, "b": 0.3}
    out = _bayesian_update(priors, [{"a": 0.01, "b": 0.99}], [0.0])
    assert out == pytest.approx(priors)


def test_update_zero_likelihood_is_floored_at_one_percent_not_annihilated():
    priors = {"a": 0.5, "b": 0.5}
    out = _bayesian_update(priors, [{"a": 0.0, "b": 1.0}], [1.0])
    # a floored to .01: a=.005, b=.5 -> a=.01/1.01, b=1/1.01
    assert out["a"] == pytest.approx(0.01 / 1.01)
    assert out["b"] == pytest.approx(1.0 / 1.01)
    assert out["a"] > 0.0  # evidence can never drive an outcome to exactly zero


def test_update_no_evidence_returns_priors_unchanged():
    priors = dict(DEFAULT_PRIORS)
    assert _bayesian_update(priors, [], []) == pytest.approx(priors)


def test_update_degenerate_all_zero_priors_falls_back_to_priors():
    priors = {"a": 0.0, "b": 0.0}
    out = _bayesian_update(priors, [{"a": 0.9, "b": 0.9}], [1.0])
    # Total mass 0 -> fall back to the prior dict; never invents probability.
    assert out == priors


def test_update_evidence_missing_an_outcome_leaves_that_outcome_prior_scaled():
    priors = {"a": 0.5, "b": 0.5}
    out = _bayesian_update(priors, [{"a": 0.5}], [1.0])
    # a: .5*.5=.25, b untouched .5 -> a=1/3, b=2/3
    assert out["a"] == pytest.approx(1.0 / 3.0)
    assert out["b"] == pytest.approx(2.0 / 3.0)


# ── fuse(): rules-only tick, hand-computed end-to-end posterior ──────────────

def test_fuse_rules_only_posterior_matches_hand_computation():
    # regime=None -> DEFAULT_PRIORS; only source is rules (weight normalizes to 1).
    # Rules "wait" likelihoods: breakout .1, continuation .1, reversal .2,
    # pinning .5, vol_expansion .1, mean_reversion .4.
    # posterior ∝ prior*lh: .015, .02, .03, .125, .01, .06; total .26.
    payload = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.available is True
    assert payload.weight_rules == pytest.approx(1.0)
    assert payload.breakout_posterior == pytest.approx(0.058)        # .015/.26
    assert payload.continuation_posterior == pytest.approx(0.077)    # .02/.26
    assert payload.reversal_posterior == pytest.approx(0.115)        # .03/.26
    assert payload.pinning_posterior == pytest.approx(0.481)         # .125/.26
    assert payload.vol_expansion_posterior == pytest.approx(0.038)   # .01/.26
    assert payload.mean_reversion_posterior == pytest.approx(0.231)  # .06/.26
    assert payload.dominant_outcome == "pinning"
    assert payload.dominant_probability == pytest.approx(0.481)


def test_fuse_posteriors_always_sum_to_one():
    payload = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    total = (
        payload.breakout_posterior
        + payload.pinning_posterior
        + payload.continuation_posterior
        + payload.reversal_posterior
        + payload.vol_expansion_posterior
        + payload.mean_reversion_posterior
    )
    assert total == pytest.approx(1.0, abs=0.005)  # rounding to 3dp only


# ── No fabricated certainty from absent inputs ───────────────────────────────

def test_fuse_with_no_models_fabricates_no_direction_and_caps_confidence():
    payload = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    # No model triplets -> no directional probabilities, no agreement.
    assert payload.prob_up is None
    assert payload.prob_down is None
    assert payload.prob_flat is None
    assert payload.dominant_direction is None
    assert payload.model_agreement is None
    assert payload.model_agreement_label is None
    # Zero approved predictive models: score capped at .55 then damped by .85
    # (payload rounds to 3dp: 0.4675 -> 0.468).
    assert payload.fusion_confidence != "high"
    assert payload.fusion_confidence_score <= round(0.55 * 0.85, 3)
    assert payload.n_sources_active == 0
    assert payload.missing_models == ["lstm", "transformer", "xgboost"]
    assert payload.contributing_models == ["rules"]


def test_fuse_available_model_with_unusable_triplet_contributes_nothing():
    # available=True but prob_up missing: excluded from evidence and direction.
    broken = SimpleNamespace(
        available=True,
        prob_up=None,
        prob_down=0.3,
        prob_flat=0.2,
        continuation_support=0.2,
        reversal_support=0.1,
        confidence_label="medium",
    )
    payload = fuse(None, broken, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.available is True
    assert payload.prob_up is None
    assert payload.dominant_direction is None
    assert payload.model_agreement is None
    # The unusable model still absorbs its normalized trust weight (it claims
    # available=True), so the rules exponent shrinks and the posterior moves
    # TOWARD the prior — weaker certainty, never stronger. Dominant call and
    # its ordering against the rules-only baseline lock that direction.
    baseline = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.dominant_outcome == baseline.dominant_outcome == "pinning"
    assert payload.dominant_probability < baseline.dominant_probability
    assert payload.dominant_probability > DEFAULT_PRIORS["pinning"]
    assert "xgboost" in payload.contributing_models  # participation is audited


def test_fuse_single_model_confidence_never_reaches_high():
    # Even a maximally confident lone model is dampened below "high".
    strong = _xgb(0.97, 0.02, 0.01, cont=0.9, rev=0.05, conf="high")
    payload = fuse(None, strong, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.available is True
    assert payload.fusion_confidence in ("low", "medium")
    assert payload.fusion_confidence_score <= round(0.55 * 0.85, 3)


# ── Monte Carlo is pass-through context, never a posterior source ────────────

def test_fuse_mc_availability_never_moves_the_posterior():
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.7,
        expansion_prob=0.3,
        expected_favorable_excursion=1.0,
        expected_adverse_excursion=1.2,
        upper_50=101.0,
        lower_50=99.0,
        n_paths=500,
        horizon_bars=10,
        assumptions={"garch_active": True, "scaled_sigma": 0.2},
    )
    with_mc = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, mc, _rules_wait())
    without_mc = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert with_mc.weight_monte_carlo == 0.0
    for attr in (
        "breakout_posterior", "pinning_posterior", "continuation_posterior",
        "reversal_posterior", "vol_expansion_posterior", "mean_reversion_posterior",
        "dominant_outcome", "dominant_probability", "fusion_confidence_score",
    ):
        assert getattr(with_mc, attr) == getattr(without_mc, attr), attr
    # But the MC pass-through block is faithfully populated.
    assert with_mc.mc_available is True
    assert with_mc.mc_containment == 0.7
    assert with_mc.mc_expansion == 0.3
    assert with_mc.mc_paths == 500
    assert with_mc.mc_horizon == 10
    assert with_mc.mc_vol_source == "garch"
    assert with_mc.mc_sigma_value == 0.2
    # And absent MC leaves the pass-through empty, not defaulted.
    assert without_mc.mc_available is False
    assert without_mc.mc_containment is None
    assert without_mc.mc_paths is None


# ── Degenerate regimes ───────────────────────────────────────────────────────

def test_fuse_unknown_regime_label_treated_exactly_as_absent_regime():
    unknown = SimpleNamespace(primary="unknown", confidence="high")
    a = fuse(unknown, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    b = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert a.weight_regime == 0.0
    assert a.pinning_posterior == b.pinning_posterior
    assert a.dominant_outcome == b.dominant_outcome
    assert a.n_sources_available == b.n_sources_available == 1


def test_fuse_attributeless_rules_object_defaults_to_wait_evidence():
    payload = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, object())
    baseline = fuse(None, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.available is True
    assert payload.pinning_posterior == baseline.pinning_posterior
    assert payload.dominant_outcome == baseline.dominant_outcome


# ── Directional fusion: hand-computed weighted blend ─────────────────────────

def test_fuse_single_model_directional_probs_pass_through():
    payload = fuse(None, _xgb(0.5, 0.3, 0.2), UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.prob_up == pytest.approx(0.5)
    assert payload.prob_down == pytest.approx(0.3)
    assert payload.prob_flat == pytest.approx(0.2)
    assert payload.dominant_direction == "up"


def test_fuse_two_model_directional_blend_uses_base_weight_ratio():
    # xgboost base weight .25, lstm .20 -> blend ratio 5:4 (regime None => no adj).
    xgb = _xgb(0.6, 0.2, 0.2)
    lstm = SimpleNamespace(
        available=True,
        prob_up=0.2,
        prob_down=0.6,
        prob_flat=0.2,
        continuation_support=0.2,
        reversal_support=0.1,
    )
    payload = fuse(None, xgb, lstm, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    # up = (.25*.6+.20*.2)/.45 = .4222; down = (.25*.2+.20*.6)/.45 = .3778; flat = .2
    assert payload.prob_up == pytest.approx(0.422)
    assert payload.prob_down == pytest.approx(0.378)
    assert payload.prob_flat == pytest.approx(0.2)
    assert payload.dominant_direction == "up"
    # Two disagreeing models -> agreement exactly 1/2 ("medium", not flagged:
    # the disagreement contradiction requires agreement strictly below 0.5).
    assert payload.model_agreement == pytest.approx(0.5)
    assert payload.model_agreement_label == "medium"


def test_fuse_unnormalized_model_triplet_is_normalized_before_blending():
    raw = _xgb(2.0, 1.0, 1.0)  # sums to 4 -> (.5, .25, .25)
    payload = fuse(None, raw, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, _rules_wait())
    assert payload.prob_up == pytest.approx(0.5)
    assert payload.prob_down == pytest.approx(0.25)
    assert payload.prob_flat == pytest.approx(0.25)
