# Stack bundle authority report

Generated (UTC): 2026-04-16T16:54:38.893214+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 60c

- **Authoritative winner**: `fusion_without_mc`
- **Runner-up**: `full_fusion`
- **Winner log loss**: 0.44467134126389013
- **Margin vs runner-up**: 0.0041058197116699
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: None
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: None
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_plus_transformer | 1000 | 0.5570943398887699 | 0.871070707070707 | 0.8729852784806068 | 0.24469432497040916 |
| fusion_without_mc | 1000 | 0.44467134126389013 | 0.8686734006734008 | 0.8714261743034023 | 0.15209827482427485 |
| full_fusion | 1000 | 0.44877716097556003 | 0.8686734006734008 | 0.8714261743034023 | 0.13077130743782697 |
