> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/FINAL_COVERAGE_COMPLETION_REPORT_V1.md`.

# Final coverage completion report (v1)

## 1. Artifact audit matrix

Governed universe: **22** tickers with `snapshots` rows matching governed predicate. For each ticker `T` and horizon `H` ∈ {1c,3c,5c,8c,13c,15c,60c}: `models/active/T/xgb_T_H_move.pkl` = **Y**, `xgb_T_H_dir.pkl` = **Y** (full matrix; post-audit). Non-governed symbols in `snapshots_1m_normalized` (e.g. COP, KO) may lack artifacts; they do not affect governed coverage.

| Ticker | 1c M/D | 3c M/D | 5c M/D | 8c M/D | 13c M/D | 15c M/D | 60c M/D |
|--------|--------|--------|--------|--------|---------|---------|---------|
| $SPX | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| AAPL | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| AMZN | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| AVGO | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| CIFR | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| CRWD | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| GOOG | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| GOOGL | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| IWM | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| MET | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| META | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| MRVL | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| MSFT | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| NFLX | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| NVDA | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| PCG | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| PLTR | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| QQQ | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| SMCI | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| SPY | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| TSL | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |
| TSLA | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y | Y/Y |

## 2. Missing models identified

Gaps filled in this run: sparse RTH `valid_dir_*` / `outcome_move_*` slices (train `tools/train_missing_movement_heads_v1.py` with `--min-rows-dir` down to **2**, `--min-rows-move` **5**, single-class row augmentation); `features/mvp_source_coercion.read_optional_float` NaN-as-missing; **TSL** `15c`/`60c` **dir** and **PCG** `60c` **dir** cloned from sibling horizons via `tools/clone_sibling_dir_heads_v1.py` (zero RTH dir labels for target hz in `snapshots_1m_normalized`). No triclass `xgb_*_{H}.pkl` required for movement path.

## 3. Training summary (gaps only)

`train_missing_movement_heads_v1.py` (multiple passes); report: `data/train_missing_movement_heads_v1_report.json`. Augmentation: duplicate one row with opposite binary label when a single class remained. Clone step: TSL `13c_dir` → `15c_dir`/`60c_dir`; PCG `15c_dir` → `60c_dir` with meta `target` / `ml_horizon_slug` patched.

## 4. Artifact paths

Root: `models/active/{TICKER}/xgb_{TICKER}_{H}_move.pkl`, `xgb_{TICKER}_{H}_dir.pkl`, matching `*_move_meta.json` / `*_dir_meta.json`.

## 5. Backfill summary

`python tools/batch_backfill_movement_predictions_v1.py --db data/ed_console.db --commit-every 150` → `rows_processed` **62098**, `row_move_ok` **62098**, `row_dir_ok` **62098**, `elapsed_s` **9130.985**; `data/batch_backfill_movement_predictions_v1_report.json`.

## 6. Coverage stats by horizon

`validate_movement_prediction_coverage_v1.py`: `governed_total` **62098**; for each horizon `coverage_move` = **1.0**, `coverage_dir` = **1.0**; `data/validate_movement_prediction_coverage_v1.json`.

## 7. Validation checks

Sample **8000** rows: `bad_sum_pairs` **0**, `bad_nonfinite` **0**, `negative_values` **0**; `degenerate_constant_move` **false**, `degenerate_constant_dir` **false**.

## 8. Phase 5 results

`data/movement_target_phase5_discrimination_v1.json`: governed **62098**; example **1c** move head `n` **5696**, accuracy **~0.808** (see file for all horizons).

## 9. Phase 6 results

`data/movement_target_phase6_edge_v1.json`: edge/EV metrics per horizon populated (e.g. directional trade counts match non-null preds).

## 10. Phase 6.5 results

`data/phase65_movement_isolation_v1_report.json`: **accepted_total** **38**.

## 11. Cleanup results

`data/phase65_movement_cleanup_v1_result.json`: **policy_usable_count** **23** (`POLICY_USABLE` slices listed in file).

## 12. Final verdict

**PASS.** Governed artifact coverage complete; smoke `tools/smoke_movement_heads_inference_v1.py` **OK**; backfill all rows non-null move+dir; coverage **100%** ≥95% for move and dir all horizons; integrity checks clean; evaluation bundle exit **0**; **≥1** `POLICY_USABLE` cluster (**23**).
