# Stack bundle authority report

Generated (UTC): 2026-04-16T13:29:16.863569+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 5c

- **Authoritative winner**: `xgb_plus_transformer`
- **Runner-up**: `fusion_without_mc`
- **Winner log loss**: 0.589678513013768
- **Margin vs runner-up**: 0.004440670158886606
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: True
- **MC improves vs fusion-without-MC**: False
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: False
- **Edge vs uniform 3-class**: True
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 1000 | 0.743677094404355 | 0.33527131782945735 | 0.27852493986602117 | 0.08456354816704348 |
| lstm_only | 1000 | 1.2160642722023154 | 0.5918223975636766 | 0.5511638863546477 | 0.0924053457412845 |
| transformer_only | 1000 | 0.697399335810927 | 0.737078488372093 | 0.6434467041864661 | 0.11920798109534778 |
| xgb_plus_lstm | 1000 | 0.6685579463332008 | 0.49008893964562567 | 0.517893404890439 | 0.0914370926533193 |
| xgb_plus_transformer | 1000 | 0.589678513013768 | 0.6005658222591362 | 0.6336676236910924 | 0.13153977927146393 |
| xgb_plus_lstm_plus_transformer | 1000 | 0.5942760490088629 | 0.595047411406423 | 0.6172946677118648 | 0.1137198632394634 |
| fusion_without_mc | 1000 | 0.5941191831726546 | 0.601750761351052 | 0.6206284917599243 | 0.10779755879855882 |
| full_fusion | 1000 | 0.7213540749554173 | 0.6463050249169435 | 0.6307181711988727 | 0.18262074571074566 |
