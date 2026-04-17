# Stack bundle authority report

Generated (UTC): 2026-04-16T04:56:55.781004+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_plus_transformer`
- **Runner-up**: `xgb_plus_lstm_plus_transformer`
- **Winner log loss**: 0.29200946407310996
- **Margin vs runner-up**: 0.02033589806452729
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: False
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: False
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: True
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: True

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 1000 | 0.33091302610383583 | 0.3333333333333333 | 0.3156047042302967 | 0.04811799639429598 |
| lstm_only | 1000 | 0.4593213210561143 | 0.4793692897141173 | 0.43485236211622197 | 0.021080475251072713 |
| transformer_only | 1000 | 0.38615764009020204 | 0.5586454084785565 | 0.5468794003596109 | 0.05617289143114493 |
| xgb_plus_lstm | 1000 | 0.3418195355297067 | 0.36787313539260147 | 0.3776227051330086 | 0.07269565044352143 |
| xgb_plus_transformer | 1000 | 0.29200946407310996 | 0.38046072083891885 | 0.4012415176727444 | 0.029959432653526023 |
| xgb_plus_lstm_plus_transformer | 1000 | 0.31234536213763725 | 0.4101423233792533 | 0.4476012982402759 | 0.06865897743150365 |
| fusion_without_mc | 1000 | 0.31472252941945755 | 0.4229533289600031 | 0.46629451450233916 | 0.0700667941347941 |
| full_fusion | 1000 | 0.4716098927721672 | 0.43314984360590586 | 0.4611147411147411 | 0.20967881182881187 |

### 15c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `xgb_plus_transformer`
- **Winner log loss**: 1.1224323437833672
- **Margin vs runner-up**: 0.09270043531048078
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: False
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: False
- **Edge vs uniform 3-class**: False
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 1000 | 1.1224323437833672 | 0.36035407674750997 | 0.2925300476882432 | 0.10038857871514582 |
| lstm_only | 1000 | 9.300868376891525 | 0.3441290081408872 | 0.20301911280728047 | 0.6105660822863856 |
| transformer_only | 1000 | 4.000063473087474 | 0.29791209759099563 | 0.2784672206228021 | 0.5345911120448184 |
| xgb_plus_lstm | 1000 | 1.3471701641915172 | 0.34445436672758484 | 0.1995641631625794 | 0.33080298622494664 |
| xgb_plus_transformer | 1000 | 1.215132779093848 | 0.294960167507385 | 0.27319457921098433 | 0.2348176437728749 |
| xgb_plus_lstm_plus_transformer | 1000 | 1.312096999422119 | 0.3800587757982868 | 0.2916022755096905 | 0.22978310309970962 |
| fusion_without_mc | 1000 | 1.330596520812553 | 0.37224663481211895 | 0.27917822197120373 | 0.251190083979084 |
| full_fusion | 1000 | 1.3577981169258195 | 0.3367959415245845 | 0.21839612886016116 | 0.24531510525910524 |
