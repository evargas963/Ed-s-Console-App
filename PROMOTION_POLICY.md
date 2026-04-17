# Promotion Policy — Canonical 1m Training System

## Overview

Models are promoted from `models/parallel/{ticker}/` or `models/cascade/{ticker}/` to `models/active/{ticker}/` only when all criteria pass. Non-compliant active artifacts are flagged and can be replaced via `--force-retrain`.

## Promotion Criteria (all must pass)

| # | Criterion | Why |
|---|-----------|-----|
| 1 | Metadata present | Provenance required for auditability |
| 2 | `training_timeframe == "1m"` | Canonical 1m alignment |
| 3 | `target_column == "outcome_1c"` | Expected horizon |
| 4 | `target_definition` contains "1 min" | Canonical horizon semantics |
| 5 | `rows_used >= 500` | Minimum data for reliability |
| 6 | `eval_accuracy >= 0.34` | Above random (1/3) |
| 7 | `balanced_accuracy >= 0.33` (when computed) | Class-distribution-aware quality |
| 8 | `new eval_accuracy >= existing` | Improvement over current active |
| 9 | Tie-break: higher `balanced_accuracy` wins | Prefer balanced when accuracy ties |

## Metrics

- **eval_accuracy**: Ensemble accuracy on full RTH holdout (parallel or cascade).
- **balanced_accuracy**: (recall_up + recall_down + recall_flat) / 3. Mitigates class imbalance.
- **rows_used**: Training sample count from provenance.

## Force Retrain

When existing active artifacts lack provenance (predate governed pipeline):

```
python ml_scheduler.py --run-now --force-retrain
```

Skips criterion #8 (comparison vs existing) when existing is non-compliant.

## Verification

```
python verify_active_models.py
```

Exit 1 if any active artifact lacks provenance or fails compliance.

## Training Report (models/training_report.jsonl)

Each line (JSON) includes:

| Field | Description |
|-------|-------------|
| ticker | Symbol |
| model_type | "ensemble" |
| training_timeframe | "1m" |
| target_column | "outcome_1c" |
| target_definition | "outcome_1c ~1 min ahead" |
| train_start, train_end | Date range |
| rows_used | Sample count |
| eval_accuracy, eval_accuracy_cascade | Parallel vs cascade accuracy |
| balanced_accuracy, balanced_accuracy_cascade | Per-class recall avg |
| promoted | true/false |
| promotion_reason | Human-readable reason if promoted |
| rejection_reason | Reason if not promoted |
| timestamp | ET |
