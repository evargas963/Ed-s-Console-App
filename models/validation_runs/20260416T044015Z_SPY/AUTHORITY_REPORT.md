# Stack bundle authority report

Generated (UTC): 2026-04-16T04:42:13.335263+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 15c

- **Authoritative winner**: `xgb_only`
- **Runner-up**: `xgb_plus_transformer`
- **Winner log loss**: 1.1584972914288585
- **Margin vs runner-up**: 0.017084449475124996
- **Full fusion beats XGB+meta stack (log loss)**: None
- **Full fusion beats XGB-only (log loss)**: False
- **MC improves vs fusion-without-MC**: True
- **Bayesian fusion improves vs meta stack**: None
- **Bayesian fusion improves vs explicit weighted triplet**: True
- **Edge vs uniform 3-class**: False
- **Deployable (heuristic)**: False
- **Policy calibration may proceed (heuristic)**: True
- **Trade plan work may proceed (heuristic)**: False

| config | n | log_loss | bal_acc | macro_F1 | ECE |
|--------|---|----------|---------|----------|-----|
| xgb_only | 100 | 1.1584972914288585 | 0.25396825396825395 | 0.18095238095238098 | 0.16952818048729185 |
| lstm_only | 100 | 5.631512726004433 | 0.35173160173160173 | 0.24812030075187966 | 0.4613851859639819 |
| transformer_only | 100 | 3.4884540220302798 | 0.313997113997114 | 0.2537507928270772 | 0.47295622019389216 |
| xgb_plus_lstm | 100 | 1.2963986894987058 | 0.35173160173160173 | 0.2490942028985507 | 0.35760547827336475 |
| xgb_plus_transformer | 100 | 1.1755817409039835 | 0.32352092352092354 | 0.2700024362362025 | 0.10592984109991846 |
| xgb_plus_lstm_plus_transformer | 100 | 1.287949122232027 | 0.332972582972583 | 0.2637646591134963 | 0.2058092747765127 |
| fusion_without_mc | 100 | 1.306636057142739 | 0.3253968253968254 | 0.25793650793650796 | 0.22486058984058988 |
| full_fusion | 100 | 1.247539576514339 | 0.3268398268398269 | 0.2498876404494382 | 0.1940608778808779 |
