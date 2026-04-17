# Phase 3 — Empirical threshold tuning & confidence calibration

## Scripts

```text
python -m calibration.analyze_phase3 --db data/ed_console.db
```

Output: `models/calibration_runs/phase3_analysis_<unix_ts>.json`

## What the analysis computes (when data exists)

| Track | Metric | Notes |
|--------|--------|--------|
| Confidence calibration | Reliability buckets by **canonical** `confidence` (from `canonical_json`) vs **5c outcome** hit rate | Requires `calibration_decision_log` + `canonical_json` |
| Brier | Multiclass Brier score: canonical `(p_up,p_down,p_flat)` vs `outcome_5c` | Same requirement |
| Regime | Mean `outcome_5c_pts` by `regime_primary` | Sample count per bucket always present in JSON |
| Threshold grid | Mean `outcome_5c_pts` for rows with `fusion_confidence_score >= t` | Only if `fusion_json` contains score |
| Probability buckets | Mean `outcome_5c_pts` by max canonical probability decile | Requires probabilities in `canonical_json` |

## Snapshots fallback (log empty)

If **no** `calibration_decision_log` rows have `outcome_5c`, the script adds **`snapshots_fallback`**: coarse stats using `snapshots.combined_signal` / `combined_conviction` vs `outcome_5c` for directional PnL proxy.

**Caveat (explicit):** `combined_*` is **not** identical to the full fusion row stored in the calibration log. Use this only to bound **order-of-magnitude** behavior until the log is populated.

### Example fallback snapshot (this workspace)

From `phase3_analysis_1775871456.json`:

- `snapshot_rows_labeled`: **21,703**
- `by_combined_conviction.low`: **21,626** rows — **21,625** are `wait`, **1** is `long`; **`n_pnl_computed` = 1** for directional PnL proxy (not statistically usable).
- `by_combined_conviction.medium`: **77** rows — all **`wait`** (`n_long`/`n_short` = 0).

**Interpretation:** The fallback proves labeled snapshots can be joined at scale; it does **not** support tiered confidence or threshold optimization — **directional n ≈ 0** under `combined_signal` in this historical extract.

## Institutional rules (enforced in reporting)

- Every statistic must carry an **n** (or be explicitly marked unusable).
- No substitute for empirical curves where the calibration log is empty: Phase 3 documents **what will be measured**, not fabricated ECE/Brier from sparse tiers.

## Next measurement steps (priority)

1. Enable **`ED_CALIBRATION_LOG=1`** on a controlled replay or live window.
2. Run **`calibration.backfill_outcomes`** after labels mature.
3. Re-run **`analyze_phase3`** and replace fallback sections with log-based reliability and Brier.
