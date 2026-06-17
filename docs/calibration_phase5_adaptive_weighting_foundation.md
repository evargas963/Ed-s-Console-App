> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/calibration_phase5_adaptive_weighting_foundation.md`.

# Phase 5 — Adaptive weighting foundation (evidence + future framework)

## Purpose

Prepare **empirical** evidence for later **market-state-aware** model/fusion weighting — without implementing production weight mutation in this pass.

## Evidence collected (or to be collected)

| Signal | Source | Status in this repo snapshot |
|--------|--------|--------------------------------|
| Regime × mean move | `calibration_decision_log.regime_primary` × `outcome_5c_pts` | Pending — needs populated log + labeled outcomes |
| Model trust by regime | Parsed from `model_outputs_json` + regime | Pending |
| Structural pattern × regime | `zone` / `vwap_side` in log + outcomes | Pending |

Phase 3’s **`regime_buckets`** block will populate automatically once the log exists.

## Findings so far

- **Static fusion weights** (`bayesian_fusion.BASE_WEIGHTS` + regime adjustments) remain the **implemented** policy.
- **No empirical proof** yet that static weights are optimal in all regimes — the calibration log is empty; **do not** claim superiority of adaptive weights without sample counts.

## Recommended future framework (grounded, not speculative)

1. **Stratify** all scored metrics by `regime_primary` × `vol_regime` × `session_bucket` with **minimum n per cell** (reuse `MIN_SAMPLES_STATISTICAL` or stricter for trading).
2. **Compute** per-stratum Brier / reliability for each model head (XGB, LSTM, Transformer) and for **fusion** — promoted only if fusion beats the best single head **out of sample**.
3. **Weight proposal:** map measured calibration error to a **dampened** trust adjustment (e.g. cap movement per week) to avoid overfitting tape noise.
4. **Explicit kill-switch:** if sample size in a stratum is below threshold, **revert** to global static weights for that stratum.

## Where static weighting may be inferior

Hypothesis only until measured: regimes where **LSTM** sequence memory should dominate fast trend days vs **rules**-heavy pinning days — testable once per-model outcomes are logged and labeled.

## Separation

- **Current implementation:** static Bayesian fusion as shipped.
- **Future recommendation:** adaptive weighting **after** Phase 3 shows stable per-regime calibration curves with adequate **n**.
