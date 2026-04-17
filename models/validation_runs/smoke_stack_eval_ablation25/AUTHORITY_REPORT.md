# Stack bundle authority report

Generated (UTC): 2026-04-16T03:59:45.434952+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `meta_stack`
- **Winner log loss**: 0.4180856256293126
- **Margin vs runner-up**: 0.015562070084808255
- **Full fusion beats XGB+meta stack (log loss)**: False
- **Full fusion beats XGB-only (log loss)**: False
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: False
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 25 | 0.4180856256293126 | 0.5 | 0.3120567375886525 | 0.04277202143040031 |
| meta_stack | 25 | 0.4336476957141209 | 0.5 | 0.3120567375886525 | 0.057553218857012166 |
| fusion_without_mc | 25 | 0.5371767534422716 | 0.5 | 0.3120567375886525 | 0.2236092076492077 |
| full_fusion | 25 | 0.6979976591616007 | 0.45454545454545453 | 0.2962962962962963 | 0.260974301014301 |
