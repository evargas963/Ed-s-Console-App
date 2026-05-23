> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/target_redesign_movement_v1_report.md`.

# Target redesign — movement v1

## 1. Target definitions

- **Legacy (unchanged):** `outcome_{H} ∈ {up, down, flat}` from `classify_direction(Δclose, anchor_close)`.
- **TARGET 1 — conditional direction:** `outcome_dir_{H} ∈ {up, down}` when `|Δclose| ≥ threshold_pts(H)`; else `NULL`.
- **TARGET 2 — movement:** `outcome_move_{H} ∈ {move, no_move}` on full sample; `move` iff `|Δclose| ≥ threshold_pts(H)`.
- **Audit:** `outcome_move_thr_pts_{H}` stores the threshold applied at label time.

## 2. Threshold selection

`threshold_pts = max(anchor_close × min_fraction_of_anchor, atr × atr_multiplier)` with positive floor.

- Defaults in `calibration/movement_target_threshold_v1.json`.
- Re-fit from data: `python tools/calibrate_movement_threshold_v1.py --db data/ed_console.db` (targets ~42% move rate by default; adjusts balance among up/down among moves).

## 3. Coverage stats

Run after `EdDB.refresh_all_governed_bar_anchor_outcomes_v1()` (or live `fill_outcomes`) and optional `snapshot_normalizer` materialize:

```sql
SELECT
  AVG(outcome_move_5c IS NOT NULL) AS move_label_coverage,
  AVG(outcome_dir_5c IS NOT NULL)  AS dir_conditional_rate
FROM snapshots WHERE timeframe='1m';
```

## 4. Class balance

```sql
SELECT outcome_move_5c, COUNT(*) FROM snapshots WHERE timeframe='1m' GROUP BY 1;
SELECT outcome_dir_5c, COUNT(*) FROM snapshots WHERE outcome_dir_5c IS NOT NULL GROUP BY 1;
```

## 5. Training changes

- `ml_train.py --target-mode triclass|dir|move` (default `triclass`).
- `dir`: label `outcome_dir_{H}`; trains only rows with non-null direction; artifact `xgb_{TICKER}_{H}_dir.pkl`.
- `move`: label `outcome_move_{H}`; full eligible sample; artifact `xgb_{TICKER}_{H}_move.pkl`.
- `--horizon` selects `H`. `load_data` uses the matching label column via `training_label_where_clause`.

## 6. Inference output

`ml_predict.run_base_models_once` adds `movement_head_probs` when artifacts exist for the active ML horizon:

- `pred_{H}_dir_up_prob`, `pred_{H}_dir_down_prob`
- `pred_{H}_move_prob`, `pred_{H}_no_move_prob`

Probabilities renormalized per head; omitted if models missing. Persisted on snapshots via `PredictiveCard.movement_head_probs` → `MarketState` → `server` snapshot kwargs (and `signals._build_snapshot_dict` for non-server paths).

## 7. Evaluation results (Phase 5 / 6 / 6.5)

**Not re-executed in this workspace** (no governed DB + trained dual heads in-repo).

After labels backfill, train dir/move XGB heads, run live or batch inference to populate `pred_*`, then:

- `python -m calibration.eval_movement_targets_phase_style_v1 --db data/ed_console.db --horizon 5c`
- Extend or duplicate `tools/_phase5_discrimination_audit_v1.py` / `calibration/phase6_edge_discovery_governed_v1.py` / `calibration/phase65_edge_isolation_v1.py` to consume binary columns and `pred_*_dir_*` / `pred_*_move_*` (parallel to legacy 3-class paths).

## 8. Comparison vs original target

| Aspect | Legacy `outcome_{H}` | `outcome_dir_{H}` | `outcome_move_{H}` |
|--------|----------------------|-------------------|---------------------|
| Flat dominance | Yes | Removed from conditional set | Explicit second head |
| Training rows | All with label | Subset (moved only) | All with label |
| Interpretation | 3-way next bar | Direction given tradable move | Timing / gating |

## 9. Final verdict

**Implementation: complete** (labels, schema, training modes, XGB inference heads, persistence hooks).

**Success criteria (recall, effect size, confidence monotonicity, POLICY_USABLE slices): pending** full data refresh, dual-head training, populated `pred_*` columns, and re-run of discrimination / edge / isolation stacks on the new surface.
