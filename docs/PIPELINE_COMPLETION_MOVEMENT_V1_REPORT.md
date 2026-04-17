# Pipeline completion report (movement inference + persistence)

## 1. Schema updates

- `ml_horizon.ML_HORIZON_SLUGS` extended to `("1c","3c","5c","8c","13c","15c","60c")` so migrations and inference align with `ml_train.HORIZONS`.
- `EdDB._migrate_schema()` (run via `from db import EdDB; EdDB()`) adds for each slug `H` on `snapshots` / `snapshots_1m_normalized`: `pred_{H}_dir_*`, `pred_{H}_move_*`, `pred_dir_*_{H}`, `pred_move_*_{H}` (REAL, additive-only).

## 2. Inference pipeline description

- `tools/batch_backfill_movement_predictions_v1.py`: loads governed anchor rows (same predicate as `calibration.phase6_edge_discovery_governed_v1.load_rows`), builds `InferenceSnapshotV1` via `build_inference_snapshot_v1_from_db_row`, clamps negative `spread` to absolute value for MVP validity, sets horizon with `ml_predict.set_ml_infer_horizon_slug`, runs `ml_predict._predict_xgb_movement_heads` once per horizon per row, batches `UPDATE snapshots SET … WHERE snapshot_id=?` (commit every N rows). Skips DB write when all prediction columns would remain NULL.

## 3. Backfill execution summary

- Command: `python tools/batch_backfill_movement_predictions_v1.py --db data/ed_console.db --commit-every 150`
- Governed rows with anchor: **62098**; **2898** rows produced all-null preds (no usable movement heads for that row/ticker, e.g. `$SPX` folder has no `.pkl` artifacts; partial ticker/horizon training gaps).
- Rows with at least some non-null preds: **59200** (62098 − 2898). Per-batch stats: `row_move_ok` **52843**, `row_dir_ok` **41754** (dir lower when some horizons lack trained `_dir` heads).
- Elapsed **~7988 s** (~2.2 h wall); report: `data/batch_backfill_movement_predictions_v1_report.json`

## 4. Coverage stats by horizon

- Source: `data/validate_movement_prediction_coverage_v1.json` after `python tools/validate_movement_prediction_coverage_v1.py --db data/ed_console.db`
- Governed total: **62098**. Validator threshold: **95%** non-null per column family (`tools/validate_movement_prediction_coverage_v1.py`).
- **Move** (`pred_move_prob_{H}`): ~**85–91%** depending on horizon (short horizons ~91.3%; **60c** ~85.1%).
- **Dir** (`pred_dir_up_prob_{H}`): ~**67–80%** (short horizons ~76–80%; **60c** ~67.2%).
- Tool exit code **3**, `overall_verdict`: **FAIL** (below 95% bar). Gaps are expected where training did not emit both heads for every ticker/horizon.

## 5. Validation checks (NaN, sum-to-1, distributions)

- Sample: **8000** rows; **0** bad sum pairs, **0** non-finite, **0** negative values.
- `pred_move_prob_5c` (n=8000): mean **0.664**, std **0.144**, min **0.159**, max **0.893**; not degenerate constant.
- `pred_dir_up_prob_5c` (n=7577): mean **0.537**, std **0.029**; not degenerate constant.

## 6. Phase 5 results

- `data/movement_target_phase5_discrimination_v1.json`: movement and direction heads report non-zero `n` (e.g. move head **n=5136** for **1c** evaluation slice); discrimination metrics populated. See file for per-horizon gates and deciles.

## 7. Phase 6 results

- `data/movement_target_phase6_edge_v1.json`: edge / EV metrics populated per horizon (e.g. **1c** `n` **47050** directional rows with preds). Simple long-vs-model comparisons and bootstrap CIs are in the JSON; not a trading recommendation.

## 8. Phase 6.5 results

- `data/phase65_movement_isolation_v1_report.json`: **accepted_total: 31** (slices passing isolation/eligibility with non-null movement predictions).

## 9. Phase 6.5 cleanup results

- `data/phase65_movement_cleanup_v1_result.json`: **policy_usable_count: 22** after hard filter + subsumption (mix of **move** and **dir** families; see `policy_usable` list in JSON).

## 10. Final verdict

**FAIL (coverage gate).** The **95%** governed-population coverage rule in `validate_movement_prediction_coverage_v1` is not met for move or dir columns at any horizon, despite successful batch persistence and **22** `POLICY_USABLE` slices in cleanup.

**What would move this to PASS:** complete per-ticker/horizon training for both `_move` and `_dir` heads (or document an intentional lower bar and relax the validator), fix tickers with empty dirs (e.g. **`$SPX`** training data / NaN coercion), re-run `train_all_movement_heads_v1` → batch backfill → coverage → evaluation bundle.
