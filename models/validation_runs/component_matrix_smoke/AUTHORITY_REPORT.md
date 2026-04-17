# Stack bundle authority report

Generated (UTC): 2026-04-16T04:17:14.361784+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 1c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `xgb_plus_transformer`
- **Winner log loss**: 0.23496298367382681
- **Margin vs runner-up**: 0.059382235643335196
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
| xgb_only | 20 | 0.23496298367382681 | 0.5 | 0.3247863247863248 | 0.06565446216089454 |
| lstm_only | 20 | 0.960994356153358 | 0.7105263157894737 | 0.24881291547958215 | 0.2554702242848522 |
| transformer_only | 20 | 0.4558704130080905 | 0.5 | 0.3247863247863248 | 0.2844501491018015 |
| xgb_plus_lstm | 20 | 0.4352898591474273 | 0.5 | 0.3247863247863248 | 0.28271586217520867 |
| xgb_plus_transformer | 20 | 0.294345219317162 | 0.5 | 0.3247863247863248 | 0.14979972132924724 |
| xgb_plus_lstm_plus_transformer | 20 | 0.4385755259531524 | 0.5 | 0.3247863247863248 | 0.2831506497270565 |
| fusion_without_mc | 20 | 0.4543374277899018 | 0.5 | 0.3247863247863248 | 0.2947615095615096 |
| full_fusion | 20 | 0.6464407783396848 | 0.4473684210526316 | 0.30630630630630634 | 0.3110711288711289 |
