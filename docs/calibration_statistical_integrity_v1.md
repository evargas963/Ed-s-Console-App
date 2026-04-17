# Calibration statistical integrity (v1)

Fail-closed minimum sample rules for Phase 3 / Phase 4 calibration scripts so empirical means, hit rates, and Brier scores are not presented as actionable when cell counts are below the production empirical floor.

## A. Exact files changed

| File | Role |
|------|------|
| `calibration/statistical_integrity.py` | **New.** Central thresholds (aligned to `math_probabilities.MIN_SAMPLES_STATISTICAL`), `bucket_gate`, `gated_mean`, `thresholds_dict`, defensive `verify_phase3_no_numeric_leak` / `verify_phase4_no_numeric_leak`. |
| `calibration/analyze_phase3.py` | Gated reliability, regime, model×vol regime buckets, threshold grid cells, probability buckets, Brier; snapshot fallback conviction slices; `statistical_integrity` block + `binary_pass`. |
| `calibration/analyze_phase4.py` | Gated per-signal performance, MHAP means, snapshot baselines, log-vs-baseline comparison; `high_confidence_losses.descriptive_only`; `statistical_integrity` block + `binary_pass`. |
| `docs/calibration_statistical_integrity_v1.md` | This document. |

## B. Thresholds defined

All named buckets use **n ≥ 30**, matching **`MIN_SAMPLES_STATISTICAL`** in `math_probabilities` (same bar as empirical similarity / prediction withholding).

| Bucket / output | Constant | Min n |
|-----------------|----------|-------|
| Confidence (canonical) reliability | `MIN_N_CONFIDENCE_BUCKET` | 30 |
| Regime (`regime_primary`) | `MIN_N_REGIME_BUCKET` | 30 |
| Model-by-regime (here: `regime_primary` × `vol_regime`) | `MIN_N_MODEL_BY_REGIME_BUCKET` | 30 |
| Threshold grid cell (per fusion score floor) | `MIN_N_THRESHOLD_GRID_CELL` | 30 |
| Probability bucket expectancy | `MIN_N_PROBABILITY_BUCKET` | 30 |
| MHAP aligned / misaligned means | `MIN_N_MHAP_BUCKET` | 30 |
| Baseline means & log vs baseline comparison | `MIN_N_BASELINE_COMPARISON` | 30 |
| Decision signal mean PnL proxy | `MIN_N_DECISION_SIGNAL` | 30 |
| Snapshot fallback by `combined_conviction` | `MIN_N_SNAPSHOT_FALLBACK_CONVICTION` | 30 |
| Aggregate Brier | `MIN_N_BRIER_AGGREGATE` | 30 |
| High-confidence losses “not descriptive-only” gate | `MIN_SAMPLES_STATISTICAL` | 30 |

Full map: `calibration.statistical_integrity.thresholds_dict()`.

## C. Where they are enforced

- **Phase 3** (`analyze_phase3.analyze`): Every bucketed mean or hit rate is computed only if `sample_gate.sufficient_sample`; otherwise the metric is **`null`** and `sample_gate.status` is **`insufficient_sample`**. Threshold grid lists cells with gates only — **no “best threshold” selection** is emitted. Brier is omitted unless `brier_n` meets the aggregate minimum.
- **Phase 4** (`analyze_phase4.analyze`): Per-signal `mean_pnl_proxy`, MHAP means, baseline means, and **`decision_log_vs_baseline_comparison.delta_*`** are null or marked **`insufficient_sample`** unless both sides (where applicable) meet minima.
- **Verification**: `verify_phase3_no_numeric_leak` / `verify_phase4_no_numeric_leak` assert that no non-null numeric slipped through without a passing gate (defensive).

## D. Which outputs now fail closed

| Output | Behavior when n &lt; min |
|--------|-------------------------|
| `empirical_hit_rate`, `mean_max_class_probability` | `null` |
| `mean_5c_pts` (regime / model-by-regime) | `null` |
| `threshold_grid.thresholds_tried[].mean_5c_pts` | `null` |
| `probability_bucket_expectancy_5c_pts[].mean_pts` | `null` |
| `brier_canonical_vs_outcome_5c` | `null` (with `brier_sample_gate`) |
| `snapshots_fallback.by_combined_conviction.*.mean_pnl_proxy_5c` | `null` |
| `decision_performance_from_log.*.mean_pnl_proxy` | `null` |
| `mhap_alignment.*_mean_5c_pts` | `null` |
| Baseline means in `baselines_from_snapshots` | `null` |
| `decision_log_vs_baseline_comparison` | `status: insufficient_sample`, `delta_*` `null` unless both log and baseline gates pass |
| `high_confidence_losses` | `descriptive_only: true` when loss count &lt; 30 |

## E. Remaining weak-sample risks

- **Multiple comparisons**: Many buckets are tested; 30 is a floor for *marginal* stability, not FDR control.
- **Non-stationarity**: Samples are not assumed IID; regime drift can invalidate historical buckets even at n ≥ 30.
- **Cross-dataset baselines**: Log vs snapshot comparison mixes populations; gates only require sufficient **marginal** n on each side, not matched pairs.
- **Snapshot cap**: Phase 4 uses up to 200k labeled snapshots; provenance records cap-related exclusions.
- **MHAP parsing**: `alignment_state` string matching may mis-bucket if enums change.
- **Model-by-regime naming**: Implemented as **`regime_primary|vol_regime`** (vol from log), not per-XGB/LSTM weight — refine if you add explicit model attribution to the log.

## F. PASS / FAIL (binary)

| Check | Result |
|-------|--------|
| Scripts suppress or null misleading metrics when n &lt; 30 | **PASS** |
| `statistical_integrity.binary_pass` is **False** only on DB missing (`error`) or defensive verifier failure | **PASS** |
| Threshold grid does not emit an optimized “best” threshold from weak cells | **PASS** |

**Overall: PASS** — calibration Phase 3/4 analysis cannot overstate evidence from weak per-cell samples under the implemented gates.
