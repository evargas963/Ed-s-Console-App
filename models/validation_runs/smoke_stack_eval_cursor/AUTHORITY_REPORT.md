# Stack bundle authority report

Generated (UTC): 2026-04-16T03:58:10.953874+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `fusion_without_mc`
- **Winner log loss**: 0.295145270810821
- **Margin vs runner-up**: 0.014397835849564056
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
| xgb_only | 400 | 0.295145270810821 | 0.3333333333333333 | 0.31762652705061084 | 0.042423661845829054 |
| transformer_only | 400 | 0.37392069901314373 | 0.41656676656676656 | 0.43408343549108547 | 0.05556118524665686 |
| meta_stack | 400 | 0.3581053085461566 | 0.3324175824175824 | 0.31716906946264745 | 0.05984101849900027 |
| fusion_without_mc | 400 | 0.30954310666038504 | 0.35908424908424913 | 0.36562167573994114 | 0.056205560025560035 |
| full_fusion | 400 | 0.4624110898645709 | 0.3554212454212455 | 0.3569825236491903 | 0.2070778922353922 |
