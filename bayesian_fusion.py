"""
bayesian_fusion.py
Single posterior-updating and trust-weighting layer.

Phase 6 of the Canonical Implementation Roadmap.

Combines evidence from:
  - regime_engine.py       (environment classification)
  - xgboost_model.py       (structured tabular evidence)
  - lstm_model.py           (sequence evidence)
  - monte_carlo.py          (path/range evidence)
  - rules_engine.py         (deterministic structure evidence)

Produces:
  - Posterior probabilities for 6 outcome families
  - Trust weights per evidence source
  - Dominant posterior call
  - Evidence/contradiction summaries
  - Fusion confidence

Consumed by:
  - prediction_engine.py (future: replace/augment statistical lookups)
  - call_engine.py (future: posterior-aware trade sizing)
  - market_state.py (display)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
import os
from typing import Any, Optional

from numeric_contract import direction_from_normalized_triplet, float_finite_or_none

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FusionPayload:
    """Structured output from Bayesian fusion."""
    available:              bool

    # Posterior probabilities for outcome families (None when fusion unavailable)
    breakout_posterior:     Optional[float] = None
    pinning_posterior:      Optional[float] = None
    continuation_posterior: Optional[float] = None
    reversal_posterior:     Optional[float] = None
    vol_expansion_posterior: Optional[float] = None
    mean_reversion_posterior: Optional[float] = None

    # Trust weights per source (0–1, sum to 1 within active sources)
    weight_xgboost:        float = 0.0
    weight_lstm:           float = 0.0
    weight_transformer:    float = 0.0
    weight_monte_carlo:    float = 0.0
    weight_rules:          float = 0.0
    weight_regime:         float = 0.0

    # Dominant posterior
    dominant_outcome:      Optional[str] = None
    dominant_probability:  Optional[float] = None
    fusion_confidence:     Optional[str] = None
    fusion_confidence_score: Optional[float] = None

    # Evidence quality
    n_sources_available:   int   = 0
    n_sources_active:      int   = 0           # sources that produced real output

    # Summaries
    evidence_summary:      list  = field(default_factory=list)
    contradiction_summary: list  = field(default_factory=list)
    fusion_summary:        str   = ""

    # Monte Carlo pass-through (useful for downstream)
    mc_available:          bool  = False
    mc_containment:        Optional[float] = None
    mc_expansion:          Optional[float] = None
    mc_efe:                Optional[float] = None  # expected favorable excursion
    mc_eae:                Optional[float] = None  # expected adverse excursion
    mc_upper_50:           Optional[float] = None
    mc_lower_50:           Optional[float] = None
    mc_paths:              Optional[int]   = None  # path count for interpretability
    mc_horizon:            Optional[int]   = None  # horizon (bars)
    mc_vol_source:         Optional[str]   = None  # 'garch' or 'blend'  (VOLATILITY source)
    mc_sigma_value:        Optional[float] = None  # ANNUALIZED decimal vol, post regime mult (path-independent)
    # DRIFT provenance — the sibling axis to mc_vol_source. 'ml_conditioned' when the unified-stack
    # team authorized a directional prior, 'base_neutral' when MC ran with no prior (drift == 0).
    # Durable, because every persisted ML column stores layer `available` while the team gate keys
    # on triplet COMPLETENESS: a base-neutral row can carry three available layers, so without this
    # a stored row is genuinely ambiguous. See tests/test_mc_base_neutral_mode_v1.py.
    mc_conditioning:       Optional[str]   = None

    # Model agreement (XGB + LSTM + Transformer + MC directional alignment)
    model_agreement:       Optional[float] = None
    model_agreement_label: Optional[str] = None

    # Directional fusion (weighted P(up), P(down), P(flat) from models)
    prob_up:               Optional[float] = None
    prob_down:             Optional[float] = None
    prob_flat:             Optional[float] = None
    dominant_direction:    Optional[str] = None

    # Audit: how Monte Carlo enters fusion (not only stored on payload — used in math below)
    fusion_mc_contribution: Optional[dict] = None

    # Post-fusion MC context adjustment (mc_fusion_adjustment); never used as a probability source in fuse()
    mc_post_fusion_audit: Optional[dict] = None

    # Optional audit: signal_layer_v1 → directional blend (production path when DB bars present)
    signal_layer_v1_fusion: Optional[dict] = None

    # Explicit model participation audit (no silent omission)
    contributing_models: list = field(default_factory=list)
    missing_models: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# REGIME-AWARE TRUST WEIGHTS
# ══════════════════════════════════════════════════════════════════════════════

# Base trust weights (before regime adjustment)
BASE_WEIGHTS = {
    "xgboost":     0.25,
    "lstm":        0.20,
    "transformer": 0.15,
    "monte_carlo": 0.10,
    "rules":       0.15,
    "regime":      0.05,
}

# Regime-specific weight adjustments (multipliers)
REGIME_WEIGHT_ADJUSTMENTS = {
    "pinning": {
        "rules": 1.5, "monte_carlo": 1.3, "xgboost": 0.8, "transformer": 0.9,
    },
    "acceleration": {
        "lstm": 1.3, "monte_carlo": 1.2, "transformer": 1.1, "rules": 0.7,
    },
    "breakout": {
        "lstm": 1.2, "xgboost": 1.1, "transformer": 1.1, "rules": 0.8,
    },
    "mean_reversion": {
        "rules": 1.4, "monte_carlo": 1.3, "xgboost": 1.0, "transformer": 1.0,
    },
    "vol_compression": {
        "monte_carlo": 1.5, "rules": 1.2, "xgboost": 0.9, "transformer": 0.9,
    },
    "vol_expansion": {
        "monte_carlo": 1.4, "lstm": 1.1, "transformer": 1.0,
    },
    "trend_continuation": {
        "lstm": 1.4, "xgboost": 1.1, "transformer": 1.1, "rules": 0.8,
    },
    "reversal_prone": {
        "rules": 1.3, "monte_carlo": 1.2, "xgboost": 0.9, "transformer": 1.0,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PRIOR SELECTION
# ══════════════════════════════════════════════════════════════════════════════

# Default priors for outcome families (uninformative, near-uniform)
DEFAULT_PRIORS = {
    "breakout":       0.15,
    "pinning":        0.25,
    "continuation":   0.20,
    "reversal":       0.15,
    "vol_expansion":  0.10,
    "mean_reversion": 0.15,
}

# Regime-conditioned prior adjustments
REGIME_PRIORS = {
    "pinning":          {"pinning": 0.40, "mean_reversion": 0.25, "breakout": 0.10, "continuation": 0.10, "reversal": 0.10, "vol_expansion": 0.05},
    "acceleration":     {"continuation": 0.30, "breakout": 0.25, "vol_expansion": 0.15, "reversal": 0.10, "pinning": 0.10, "mean_reversion": 0.10},
    "breakout":         {"breakout": 0.35, "continuation": 0.25, "vol_expansion": 0.15, "reversal": 0.10, "pinning": 0.10, "mean_reversion": 0.05},
    "mean_reversion":   {"mean_reversion": 0.35, "pinning": 0.25, "continuation": 0.15, "reversal": 0.10, "breakout": 0.10, "vol_expansion": 0.05},
    "vol_compression":  {"pinning": 0.30, "mean_reversion": 0.20, "breakout": 0.15, "continuation": 0.15, "vol_expansion": 0.10, "reversal": 0.10},
    "vol_expansion":    {"vol_expansion": 0.30, "continuation": 0.25, "breakout": 0.15, "reversal": 0.15, "pinning": 0.10, "mean_reversion": 0.05},
    "trend_continuation": {"continuation": 0.40, "breakout": 0.15, "reversal": 0.15, "vol_expansion": 0.10, "pinning": 0.10, "mean_reversion": 0.10},
    "reversal_prone":   {"reversal": 0.35, "mean_reversion": 0.20, "pinning": 0.15, "continuation": 0.10, "breakout": 0.10, "vol_expansion": 0.10},
}


# ══════════════════════════════════════════════════════════════════════════════
# EVIDENCE → LIKELIHOOD TRANSLATION
# ══════════════════════════════════════════════════════════════════════════════

def _resolved_regime_label(regime) -> Optional[str]:
    """Classified regime primary, or None when absent / unknown (fail-closed for fusion trust)."""
    if regime is None:
        return None
    raw = getattr(regime, "primary", None)
    if raw is None:
        return None
    label = str(raw).strip().lower()
    if not label or label == "unknown":
        return None
    return label


def _model_dominant_class(out) -> Optional[str]:
    """Dominant class from normalized model triplet only (ignore upstream label)."""
    if not getattr(out, "available", False):
        return None
    triplet = _model_direction_triplet(out)
    if triplet is None:
        return None
    up, down, flat = triplet
    return direction_from_normalized_triplet(up, down, flat)


def _optional_support(out, attr: str) -> Optional[float]:
    return float_finite_or_none(getattr(out, attr, None))


def _model_direction_triplet(out) -> Optional[tuple[float, float, float]]:
    """Read normalized (up, down, flat) from an available model output; None if attrs missing."""
    if not getattr(out, "available", False):
        return None
    up = getattr(out, "prob_up", None)
    down = getattr(out, "prob_down", None)
    flat = getattr(out, "prob_flat", None)
    if up is None or down is None or flat is None:
        return None
    up = float_finite_or_none(up)
    down = float_finite_or_none(down)
    flat = float_finite_or_none(flat)
    if up is None or down is None or flat is None:
        return None
    tot = up + down + flat
    if tot <= 0 or not math.isfinite(tot):
        return None
    return up / tot, down / tot, flat / tot


def _translate_xgb_evidence(xgb_out, direction_hint: str) -> dict:
    """Convert XGBoost output into likelihood contributions per outcome family."""
    if not getattr(xgb_out, "available", False):
        return {}

    triplet = _model_direction_triplet(xgb_out)
    if triplet is None:
        return {}
    up, down, flat = triplet
    directional = max(up, down)

    cont = _optional_support(xgb_out, "continuation_support")
    rev = _optional_support(xgb_out, "reversal_support")
    if cont is None or rev is None:
        return {}
    return {
        "breakout":       directional * 0.8,
        "continuation":   cont,
        "reversal":       rev,
        "pinning":        flat * 0.8,
        "vol_expansion":  directional * 0.5,
        "mean_reversion": flat * 0.6,
    }


def _translate_lstm_evidence(lstm_out, direction_hint: str) -> dict:
    """Convert LSTM output into likelihood contributions."""
    if not getattr(lstm_out, "available", False):
        return {}

    triplet = _model_direction_triplet(lstm_out)
    if triplet is None:
        return {}
    up, down, flat = triplet
    directional = max(up, down)

    cont = _optional_support(lstm_out, "continuation_support")
    rev = _optional_support(lstm_out, "reversal_support")
    if cont is None or rev is None:
        return {}
    return {
        "breakout":       directional * 0.7,
        "continuation":   cont,
        "reversal":       rev,
        "pinning":        flat * 0.8,
        "vol_expansion":  directional * 0.4,
        "mean_reversion": flat * 0.6,
    }


def _translate_transformer_evidence(transformer_out, direction_hint: str) -> dict:
    """Convert Transformer output into likelihood contributions."""
    if not getattr(transformer_out, "available", False):
        return {}

    triplet = _model_direction_triplet(transformer_out)
    if triplet is None:
        return {}
    up, down, flat = triplet
    directional = max(up, down)

    cont = _optional_support(transformer_out, "continuation_support")
    rev = _optional_support(transformer_out, "reversal_support")
    if cont is None or rev is None:
        return {}
    return {
        "breakout":       directional * 0.7,
        "continuation":   cont,
        "reversal":       rev,
        "pinning":        flat * 0.8,
        "vol_expansion":  directional * 0.4,
        "mean_reversion": flat * 0.6,
    }


def _translate_rules_evidence(rules, regime) -> dict:
    """Convert rules engine output into likelihood contributions."""
    sig = getattr(rules, "signal", "wait")
    conv = getattr(rules, "conviction", "low")

    conv_mult = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(conv, 0.3)

    if sig in ("long", "short"):
        return {
            "breakout":       0.3 * conv_mult,
            "continuation":   0.7 * conv_mult,
            "reversal":       0.1 * conv_mult,
            "pinning":        0.2 * (1 - conv_mult),
            "vol_expansion":  0.3 * conv_mult,
            "mean_reversion": 0.1,
        }
    else:  # wait
        return {
            "breakout":       0.1,
            "continuation":   0.1,
            "reversal":       0.2,
            "pinning":        0.5,
            "vol_expansion":  0.1,
            "mean_reversion": 0.4,
        }


@dataclass(frozen=True)
class FusionTickCache:
    """
    Per-tick, regime+rules fusion prep shared across all governed horizons.

    Priors, regime weight adjustments, and rules→likelihood mapping depend only on
    (regime, rules) for a single decision tick, while XGB/LSTM/transformer/MC
    evidence differs per horizon.
    """

    regime_label: Optional[str]
    direction_hint: str
    priors: dict[str, float]
    weight_adjustments: dict[str, float]
    rules_evidence: dict[str, float]


def build_fusion_tick_cache(regime, rules) -> FusionTickCache:
    """Build shared fusion prep once per tick; pass into fuse(..., fusion_tick_cache=...)."""
    regime_label = _resolved_regime_label(regime)
    direction_hint = getattr(rules, "signal", "wait")
    priors = (
        dict(REGIME_PRIORS[regime_label])
        if regime_label in REGIME_PRIORS
        else dict(DEFAULT_PRIORS)
    )
    weight_adjustments = dict(REGIME_WEIGHT_ADJUSTMENTS.get(regime_label or "", {}))
    rules_evidence = dict(_translate_rules_evidence(rules, regime))
    return FusionTickCache(
        regime_label=regime_label,
        direction_hint=direction_hint,
        priors=priors,
        weight_adjustments=weight_adjustments,
        rules_evidence=rules_evidence,
    )


# ══════════════════════════════════════════════════════════════════════════════
# POSTERIOR UPDATE
# ══════════════════════════════════════════════════════════════════════════════

def _bayesian_update(priors: dict, evidence_list: list, weights: list) -> dict:
    """
    Update priors with weighted evidence using multiplicative Bayesian update.

    For each outcome family:
      posterior(o) ∝ prior(o) × Π_i [ evidence_i(o) ^ weight_i ]

    Then normalize so posteriors sum to 1.
    """
    outcomes = list(priors.keys())
    posteriors = {o: priors[o] for o in outcomes}

    for evidence, weight in zip(evidence_list, weights):
        if not evidence:
            continue
        for o in outcomes:
            if o not in evidence:
                continue
            likelihood = evidence[o]
            lh = float_finite_or_none(likelihood)
            if lh is None:
                continue
            posteriors[o] *= max(0.01, lh) ** weight

    # Normalize
    total = sum(posteriors.values())
    if total > 0:
        posteriors = {o: v / total for o, v in posteriors.items()}
    else:
        # Fallback to priors
        posteriors = dict(priors)

    return posteriors


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def fuse(
    regime,
    xgb_out,
    lstm_out,
    transformer_out,
    mc_out,
    rules,
    *,
    signal_layer_v1: Optional[dict[str, Any]] = None,
    fusion_tick_cache: Optional[FusionTickCache] = None,
) -> FusionPayload:
    """
    Combine all evidence sources into a posterior probability bundle.

    Called after all models run. Consumes whatever is available —
    gracefully handles missing/fallback sources by excluding them
    from the update.

    Args:
        regime:         RegimePayload from regime_engine
        xgb_out:        XGB output (prob_up/down/flat, dominant_class, available)
        lstm_out:       LSTM output (same interface)
        transformer_out: Transformer output (same interface)
        mc_out:         MonteCarloOutput from monte_carlo (pass-through / diagnostics only; not blended as a model)
        rules:          RulesCard from rules_engine
        fusion_tick_cache: Optional prep from build_fusion_tick_cache(regime, rules) when fusing
                            multiple horizons for the same tick (skips repeated priors/rules-evidence work).

    Returns:
        FusionPayload with setup-family posteriors, directional probs, and summaries.
    """
    try:
        return _fuse_impl(
            regime,
            xgb_out,
            lstm_out,
            transformer_out,
            mc_out,
            rules,
            signal_layer_v1=signal_layer_v1,
            fusion_tick_cache=fusion_tick_cache,
        )
    except Exception as e:
        log.warning("bayesian_fusion: fusion failed: %s", e)
        return FusionPayload(
            available=False,
            fusion_summary=f"Fusion error: {e}",
        )


def _fuse_impl(
    regime,
    xgb_out,
    lstm_out,
    transformer_out,
    mc_out,
    rules,
    *,
    signal_layer_v1: Optional[dict[str, Any]] = None,
    fusion_tick_cache: Optional[FusionTickCache] = None,
) -> FusionPayload:
    """Internal fusion implementation."""

    if fusion_tick_cache is not None:
        regime_label = fusion_tick_cache.regime_label
        direction_hint = fusion_tick_cache.direction_hint
        priors = fusion_tick_cache.priors
        adjustments = fusion_tick_cache.weight_adjustments
    else:
        regime_label = _resolved_regime_label(regime)
        direction_hint = getattr(rules, "signal", "wait")

        # ── Select priors based on regime ─────────────────────────────────────────
        priors = (
            dict(REGIME_PRIORS[regime_label])
            if regime_label in REGIME_PRIORS
            else dict(DEFAULT_PRIORS)
        )

        # ── Compute regime-aware trust weights ────────────────────────────────────
        adjustments = dict(REGIME_WEIGHT_ADJUSTMENTS.get(regime_label or "", {}))
    weights = {}
    for source, base_w in BASE_WEIGHTS.items():
        mult = adjustments.get(source, 1.0)
        weights[source] = base_w * mult

    # Zero out weights for unavailable sources
    source_available = {
        "xgboost":     getattr(xgb_out, "available", False),
        "lstm":        getattr(lstm_out, "available", False),
        "transformer": getattr(transformer_out, "available", False),
        # Monte Carlo is intentionally excluded from fusion weights and likelihoods;
        # it is applied only as post-fusion context (see mc_fusion_adjustment).
        "monte_carlo": False,
        "rules":       True,  # always available
        "regime":      regime_label is not None,
    }

    for source, avail in source_available.items():
        if not avail:
            weights[source] = 0.0

    # Normalize active weights to sum to 1
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}

    n_sources = sum(1 for v in source_available.values() if v)
    n_active = sum(1 for s, a in source_available.items() if a and s not in ("rules", "regime"))

    contributing_models = sorted(s for s, a in source_available.items() if a)
    missing_models = sorted(
        s for s, a in source_available.items() if (not a) and s in ("xgboost", "lstm", "transformer")
    )

    # ── Translate evidence ────────────────────────────────────────────────────
    evidence_list = []
    weight_list = []

    xgb_ev = _translate_xgb_evidence(xgb_out, direction_hint)
    if xgb_ev:
        evidence_list.append(xgb_ev)
        weight_list.append(weights["xgboost"])

    lstm_ev = _translate_lstm_evidence(lstm_out, direction_hint)
    if lstm_ev:
        evidence_list.append(lstm_ev)
        weight_list.append(weights["lstm"])

    transformer_ev = _translate_transformer_evidence(transformer_out, direction_hint)
    if transformer_ev:
        evidence_list.append(transformer_ev)
        weight_list.append(weights["transformer"])

    rules_ev = (
        fusion_tick_cache.rules_evidence
        if fusion_tick_cache is not None
        else _translate_rules_evidence(rules, regime)
    )
    evidence_list.append(rules_ev)
    weight_list.append(weights["rules"])

    # ── Bayesian update ──────────────────────────────────────────────────────
    posteriors = _bayesian_update(priors, evidence_list, weight_list)

    # ── Determine dominant outcome ───────────────────────────────────────────
    dominant = max(posteriors, key=posteriors.get)
    dominant_prob = posteriors[dominant]

    # ── Fusion confidence ────────────────────────────────────────────────────
    sorted_probs = sorted(posteriors.values(), reverse=True)
    gap = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0
    if dominant_prob >= 0.35 and gap >= 0.10 and n_sources >= 3:
        conf = "high"
        conf_score = min(1.0, dominant_prob + gap * 0.5)
    elif dominant_prob >= 0.25 and gap >= 0.05:
        conf = "medium"
        conf_score = min(0.7, dominant_prob + gap * 0.3)
    else:
        conf = "low"
        conf_score = min(0.4, dominant_prob)

    # ── PHASE 1 DAMPENING — conservative until calibration data exists ────────
    # Count approved PREDICTIVE models (XGB/LSTM), not all sources.
    # MC and rules are always available — they don't count as ensemble diversity.
    # A model with available=True passed approval and is producing real output.
    n_predictive_approved = 0
    if getattr(xgb_out, "available", False):
        n_predictive_approved += 1
    if getattr(lstm_out, "available", False):
        n_predictive_approved += 1
    # Damp 1: fewer than 2 approved predictive models → cap at medium
    if n_predictive_approved < 2 and conf == "high":
        conf = "medium"
        conf_score = min(conf_score, 0.65)

    # Damp 2: only 1 approved model → cap confidence score at 0.55
    if n_predictive_approved <= 1:
        conf_score = min(conf_score, 0.55)

    # Damp 3: placeholder calibration penalty — tracked OPEN_ITEMS FUSION-CALIBRATION-PENALTY-PLACEHOLDER
    # [REAL-GATE: telemetry] until 60+ days empirical calibration replaces placeholder likelihoods.
    CALIBRATION_PENALTY = 0.85
    conf_score *= CALIBRATION_PENALTY

    # Damp 4 applied after contradictions are computed (see below)

    # ── Model agreement (XGB + LSTM + Transformer only; MC excluded) ───────────
    model_dirs = []
    for _out in (xgb_out, lstm_out, transformer_out):
        _dc = _model_dominant_class(_out)
        if _dc is not None:
            model_dirs.append(_dc)

    if model_dirs:
        from collections import Counter
        most_common = Counter(model_dirs).most_common(1)[0]
        agreement = most_common[1] / len(model_dirs)
        agree_label = "high" if agreement >= 0.75 else "medium" if agreement >= 0.5 else "low"
    else:
        agreement = None
        agree_label = None

    # ── Directional fusion: weighted P(up), P(down), P(flat) ───────────────────
    dir_sources = []
    dir_weights = []
    for src, out in [
        ("xgboost", xgb_out),
        ("lstm", lstm_out),
        ("transformer", transformer_out),
    ]:
        if not getattr(out, "available", False):
            continue
        w = weights.get(src, 0.0)
        if w <= 0:
            continue
        triplet = _model_direction_triplet(out)
        if triplet is None:
            continue
        dir_sources.append(triplet)
        dir_weights.append(w)

    prob_up = prob_down = prob_flat = None
    dominant_dir = None
    if dir_sources and dir_weights:
        total_w = sum(dir_weights)
        if total_w > 0:
            prob_up = sum(s[0] * w for s, w in zip(dir_sources, dir_weights)) / total_w
            prob_down = sum(s[1] * w for s, w in zip(dir_sources, dir_weights)) / total_w
            prob_flat = sum(s[2] * w for s, w in zip(dir_sources, dir_weights)) / total_w
            tot = prob_up + prob_down + prob_flat
            if tot > 0:
                prob_up /= tot
                prob_down /= tot
                prob_flat /= tot
                dominant_dir = direction_from_normalized_triplet(prob_up, prob_down, prob_flat)
            else:
                prob_up = prob_down = prob_flat = None
                dominant_dir = None

    # ── signal_layer_v1 directional blend (1m bars ≤ decision_ts; no lookahead) ──
    signal_layer_v1_fusion: Optional[dict] = None
    if signal_layer_v1:
        from features.signal_layer_v1 import meta_n_bars_int, signal_layer_v1_to_direction_probs

        nb = meta_n_bars_int(signal_layer_v1)
        if nb >= 25 and prob_up is not None and prob_down is not None and prob_flat is not None:
            triplet = signal_layer_v1_to_direction_probs(signal_layer_v1)
            if triplet is not None:
                _env_blend = os.environ.get("ED_SIGNAL_LAYER_FUSION_BLEND", "0.0")
                w_sl = float_finite_or_none(_env_blend)
                if w_sl is None:
                    log.debug(
                        "ED_SIGNAL_LAYER_FUSION_BLEND ignored (malformed) value=%r",
                        _env_blend,
                    )
                    w_sl = 0.0
                w_sl = max(0.0, min(1.0, w_sl))
                su, sd, sf = triplet
                prob_up = (1.0 - w_sl) * prob_up + w_sl * su
                prob_down = (1.0 - w_sl) * prob_down + w_sl * sd
                prob_flat = (1.0 - w_sl) * prob_flat + w_sl * sf
                tot = prob_up + prob_down + prob_flat
                if tot > 0:
                    prob_up /= tot
                    prob_down /= tot
                    prob_flat /= tot
                    dominant_dir = direction_from_normalized_triplet(prob_up, prob_down, prob_flat)
                signal_layer_v1_fusion = {
                    "blend_weight": round(w_sl, 4),
                    "prior_triplet": {"up": round(su, 4), "down": round(sd, 4), "flat": round(sf, 4)},
                    "post_triplet": {
                        "up": round(prob_up, 4),
                        "down": round(prob_down, 4),
                        "flat": round(prob_flat, 4),
                    },
                }

    # ── Evidence summaries ───────────────────────────────────────────────────
    evidence = []
    contradictions = []

    if getattr(mc_out, "available", False):
        if mc_out.containment_prob and mc_out.containment_prob > 0.6:
            evidence.append(f"MC: {mc_out.containment_prob:.0%} containment — supports pinning/range")
        elif mc_out.expansion_prob and mc_out.expansion_prob > 0.5:
            evidence.append(f"MC: {mc_out.expansion_prob:.0%} expansion probability")

    if getattr(xgb_out, "available", False):
        _xgb_dom = _model_dominant_class(xgb_out)
        if _xgb_dom is not None:
            evidence.append(f"XGB: {_xgb_dom} ({xgb_out.confidence_label} confidence)")

    if regime_label is not None:
        _rc = getattr(regime, "confidence", None) or "—"
        evidence.append(f"Regime: {regime_label} ({_rc})")

    if direction_hint in ("long", "short"):
        evidence.append(f"Rules: {direction_hint} lean")
    else:
        evidence.append("Rules: no directional lean")

    # Contradictions
    if model_dirs and agreement is not None and agreement < 0.5:
        contradictions.append(f"Model disagreement: {model_dirs}")
    if regime_label == "pinning" and direction_hint in ("long", "short"):
        contradictions.append("Pinning regime vs directional rules lean")

    # ── Damp 4: contradiction penalty (relocated below) ──────────────────────
    if contradictions:
        conf_score *= 0.90
        if len(contradictions) >= 2:
            conf_score *= 0.90

    # Re-classify confidence after all dampening
    if conf_score >= 0.65:
        conf = "high"
    elif conf_score >= 0.35:
        conf = "medium"
    else:
        conf = "low"

    # ── Summary text ─────────────────────────────────────────────────────────
    OUTCOME_LABELS = {
        "breakout": "breakout", "pinning": "pinning",
        "continuation": "continuation", "reversal": "reversal",
        "vol_expansion": "volatility expansion",
        "mean_reversion": "mean reversion",
    }
    dom_label = OUTCOME_LABELS.get(dominant, dominant)
    summary = f"Posterior favors {dom_label} ({dominant_prob:.0%}). "
    if n_active > 0:
        summary += f"{n_active} model(s) active. "
    if agree_label is not None:
        summary += f"Agreement: {agree_label}."

    # ── MC pass-through ──────────────────────────────────────────────────────
    mc_avail = getattr(mc_out, "available", False)
    _assum = getattr(mc_out, "assumptions", None) or {}
    mc_paths = getattr(mc_out, "n_paths", None) if mc_avail else None
    mc_horizon = getattr(mc_out, "horizon_bars", None) if mc_avail else None
    mc_vol_source = ("garch" if _assum.get("garch_active") else "blend") if mc_avail else None
    # ANNUALIZED decimal vol, post regime mult — unit is path-independent at the
    # producer (monte_carlo SIGMA UNIT CONTRACT); legacy keys kept as fallback.
    mc_sigma_value = (_assum.get("sigma_annualized") or _assum.get("scaled_sigma")
                      or _assum.get("blended_sigma")) if mc_avail else None
    # Drift provenance rides the producer's own assumption manifest, same as the vol source above.
    mc_conditioning = _assum.get("mc_conditioning") if mc_avail else None

    return FusionPayload(
        available=True,
        breakout_posterior=round(posteriors["breakout"], 3),
        pinning_posterior=round(posteriors["pinning"], 3),
        continuation_posterior=round(posteriors["continuation"], 3),
        reversal_posterior=round(posteriors["reversal"], 3),
        vol_expansion_posterior=round(posteriors["vol_expansion"], 3),
        mean_reversion_posterior=round(posteriors["mean_reversion"], 3),
        weight_xgboost=round(weights.get("xgboost", 0), 3),
        weight_lstm=round(weights.get("lstm", 0), 3),
        weight_transformer=round(weights.get("transformer", 0), 3),
        weight_monte_carlo=0.0,
        weight_rules=round(weights.get("rules", 0), 3),
        weight_regime=round(weights.get("regime", 0), 3),
        dominant_outcome=dominant,
        dominant_probability=round(dominant_prob, 3),
        fusion_confidence=conf,
        fusion_confidence_score=round(conf_score, 3),
        n_sources_available=n_sources,
        n_sources_active=n_active,
        evidence_summary=evidence,
        contradiction_summary=contradictions,
        fusion_summary=summary,
        mc_available=mc_avail,
        mc_containment=getattr(mc_out, "containment_prob", None) if mc_avail else None,
        mc_expansion=getattr(mc_out, "expansion_prob", None) if mc_avail else None,
        mc_efe=getattr(mc_out, "expected_favorable_excursion", None) if mc_avail else None,
        mc_eae=getattr(mc_out, "expected_adverse_excursion", None) if mc_avail else None,
        mc_upper_50=getattr(mc_out, "upper_50", None) if mc_avail else None,
        mc_lower_50=getattr(mc_out, "lower_50", None) if mc_avail else None,
        mc_paths=mc_paths,
        mc_horizon=mc_horizon,
        mc_vol_source=mc_vol_source,
        mc_sigma_value=mc_sigma_value,
        mc_conditioning=mc_conditioning,
        model_agreement=round(agreement, 3) if agreement is not None else None,
        model_agreement_label=agree_label,
        prob_up=round(prob_up, 3) if prob_up is not None else None,
        prob_down=round(prob_down, 3) if prob_down is not None else None,
        prob_flat=round(prob_flat, 3) if prob_flat is not None else None,
        dominant_direction=dominant_dir,
        fusion_mc_contribution=None,
        mc_post_fusion_audit=None,
        signal_layer_v1_fusion=signal_layer_v1_fusion,
        contributing_models=contributing_models,
        missing_models=missing_models,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("bayesian_fusion.py — self-test")
    # Create minimal mock objects
    from types import SimpleNamespace
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    xgb = SimpleNamespace(available=False)
    lstm = SimpleNamespace(available=False)
    transformer = SimpleNamespace(available=False)
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.6,
        expansion_prob=0.4,
        path_dispersion=2.5,
        expected_favorable_excursion=1.5,
        expected_adverse_excursion=1.6,
        upper_50=572.0,
        lower_50=568.0,
        mc_feature_dict=lambda: {
            "expected_move": 1.0,
            "volatility": 2.5,
            "skew": 0.0,
            "tail_risk": 0.1,
            "directional_bias": 0.0,
            "source": "derived_mc_normalized",
        },
    )
    result = fuse(regime, xgb, lstm, transformer, mc, rules)
    print(f"  Dominant: {result.dominant_outcome} ({result.dominant_probability:.0%})")
    print(f"  Confidence: {result.fusion_confidence}")
    print(f"  Sources: {result.n_sources_available} available, {result.n_sources_active} active models")
    print(f"  Summary: {result.fusion_summary}")
    print("  OK")
