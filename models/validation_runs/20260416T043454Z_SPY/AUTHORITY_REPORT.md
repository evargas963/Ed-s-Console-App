# Stack bundle authority report

Generated (UTC): 2026-04-16T04:35:48.464468+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `xgb_plus_transformer`
- **Winner log loss**: 0.4630184842752556
- **Margin vs runner-up**: 0.009289108839971194
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: False
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: False
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 50 | 0.4630184842752556 | 0.3333333333333333 | 0.3082437275985663 | 0.020817381997013835 |
| lstm_only | 50 | 0.9362206814514142 | 0.2816537467700258 | 0.2571428571428571 | 0.16301099827077004 |
| transformer_only | 50 | 0.5808433500546655 | 0.35788113695090434 | 0.356060606060606 | 0.12690224725948246 |
| xgb_plus_lstm | 50 | 0.5676587312154484 | 0.3333333333333333 | 0.3082437275985663 | 0.16956961545745614 |
| xgb_plus_transformer | 50 | 0.4723075931152268 | 0.3333333333333333 | 0.3082437275985663 | 0.05328464545352643 |
| xgb_plus_lstm_plus_transformer | 50 | 0.5531794159034444 | 0.3333333333333333 | 0.3082437275985663 | 0.19086386698461869 |
| fusion_without_mc | 50 | 0.5632390402707813 | 0.3333333333333333 | 0.3082437275985663 | 0.20588821354821363 |
| full_fusion | 50 | 0.7009538664714451 | 0.3178294573643411 | 0.30036630036630035 | 0.2631907749107749 |
