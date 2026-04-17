# Stack bundle authority report

Generated (UTC): 2026-04-16T16:08:25.740672+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 5c

- **Authoritative winner**: `full_fusion`
- **Runner-up**: `fusion_without_mc`
- **Winner log loss**: 0.9930986960959821
- **Margin vs runner-up**: 0.04779013417360989
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: None
- **MC improves vs fusion-without-MC**: True
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: None
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: True
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: True

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| fusion_without_mc | 200 | 1.040888830269592 | 0.39409722222222215 | 0.37345285446551274 | 0.08108850870350867 |
| full_fusion | 200 | 0.9930986960959821 | 0.39409722222222215 | 0.37345285446551274 | 0.17168890358457875 |
