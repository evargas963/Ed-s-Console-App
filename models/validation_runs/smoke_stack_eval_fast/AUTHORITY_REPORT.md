# Stack bundle authority report

Generated (UTC): 2026-04-16T03:58:43.571635+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `transformer_only`
- **Winner log loss**: 0.3744645186066492
- **Margin vs runner-up**: 0.07225461511841613
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: None
- **MC improves vs fusion-without-MC**: None
- **Bayesian fusion improves vs meta stack**: None
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: True
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: True

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 200 | 0.3744645186066492 | 0.3333333333333333 | 0.3120567375886525 | 0.034252060566675596 |
| transformer_only | 200 | 0.44671913372506533 | 0.4159382284382285 | 0.4227538613210647 | 0.07111702474788034 |
| meta_stack | 200 | 0.46444879505387116 | 0.3333333333333333 | 0.3120567375886525 | 0.08425892086392427 |
