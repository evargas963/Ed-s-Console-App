# Stack bundle authority report

Generated (UTC): 2026-04-16T15:32:31.501227+00:00

Primary metric: **multiclass log loss** (lower is better).
Paired rows: only timestamps where every requested mode produced probabilities.

## Per horizon

### 60c

- **Authoritative winner**: `fusion_without_mc`
- **Runner-up**: `xgb_plus_lstm_plus_transformer`
- **Winner log loss**: 0.44467134126389013
- **Margin vs runner-up**: 0.01123853062519542
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
| xgb_only | 1000 | 0.8802305534888017 | 0.5026464646464647 | 0.4887135141102461 | 0.11818269378723797 |
| lstm_only | 1000 | 1.8811932920469612 | 0.830983164983165 | 0.8230570413778695 | 0.10106887806317272 |
| transformer_only | 1000 | 1.0634816672955643 | 0.8688956228956229 | 0.8659238295840425 | 0.08567241790939212 |
| xgb_plus_lstm | 1000 | 0.5534830602917994 | 0.830922558922559 | 0.8253019021599078 | 0.17747778535747444 |
| xgb_plus_transformer | 1000 | 0.5570943398887699 | 0.871070707070707 | 0.8729852784806068 | 0.24469432497040916 |
| xgb_plus_lstm_plus_transformer | 1000 | 0.45590987188908555 | 0.8725723905723907 | 0.8752173425702837 | 0.1671496652541386 |
| fusion_without_mc | 1000 | 0.44467134126389013 | 0.8686734006734008 | 0.8714261743034023 | 0.15209827482427485 |
| full_fusion | 1000 | 0.5299907419940374 | 0.868107744107744 | 0.8704858924588187 | 0.22583212115312115 |
