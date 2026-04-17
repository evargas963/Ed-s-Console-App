# Target redesign — movement v1 (conditional direction + movement) — full report

**DB evaluated:** `data/ed_console.db` (governed anchor population per `load_rows` in `calibration/phase6_edge_discovery_governed_v1.py`).  
**Artifacts:** `data/movement_target_phase5_discrimination_v1.json`, `data/movement_target_phase6_edge_v1.json`, `data/phase65_movement_isolation_v1_report.json`, `data/phase65_movement_cleanup_v1_result.json`, `data/movement_threshold_search_report_v1.json`.

---

## 1. Target definitions

**Family A — conditional direction (primary)**  
For horizon `H`: `outcome_dir_{H} ∈ {up, down}` only when `|close[t+H]-close[t]| ≥ threshold_move_{H}`; otherwise `outcome_dir_{H}` is null and `valid_dir_{H}=0`. Training/evaluation of the direction head uses rows with `valid_dir_{H}=1` only.

**Family B — movement (secondary)**  
`outcome_move_{H} ∈ {move, no_move}` with `move` iff `|Δclose| ≥ threshold_move_{H}`. Trained on all rows with valid movement labels.

**Legacy target** `outcome_{H} ∈ {up, down, flat}` is unchanged and remains the default tri-class path.

---

## 2. Threshold search and selected thresholds by horizon

**Method:** `tools/select_movement_thresholds_percentile_v1.py` on empirical `abs(outcome_{H}_pts)` (RTH + weekday filters), candidates at percentiles 50 / 60 / 70 / 80. Full candidate tables: `data/movement_threshold_search_report_v1.json`. Persisted selection: `calibration/movement_target_thresholds_by_horizon_v1.json`.

**Selected (from report; all horizons `verdict: SELECTED`):**

| Horizon | Percentile | threshold_move_pts | Retained coverage | Dir imbalance | Notes |
|---------|------------|-------------------|-------------------|---------------|-------|
| 1c | 50 | 0.125 | ~0.504 | ~0.031 | Within 40/60–60/40 band |
| 3c | 50 | 0.18 | ~0.503 | ~0.045 | |
| 5c | 50 | 0.22 | ~0.502 | (see JSON) | |
| 8c | 50 | 0.26 | ~0.503 | | |
| 13c | 50 | 0.33 | ~0.501 | | |
| 15c | 50 | 0.35 | ~0.505 | | |
| 60c | 50 | 0.70 | ~0.501 | | |

Where the 80th percentile would drop coverage below 25%, it is excluded from selection (see per-horizon `candidates` in the JSON).

---

## 3. Coverage stats by horizon

**Threshold search population (labeling / RTH sample):** `n_eligible` ≈ 43k–44k per horizon in `movement_threshold_search_report_v1.json` with retained coverage ~50% at selected p50 (meets ≥25% and preferred ≥30% for p50).

**Governed snapshot population (`movement_target_phase5_discrimination_v1.json` → `label_statistics`):** Non-null `outcome_move_{H}` appears on **~5 664 / 62 066 (~9.1%)** of governed rows (same count across horizons in this export — movement columns not fully backfilled across the full governed grid). **Operational note:** refresh governed outcomes after threshold updates so `outcome_move_*` / `valid_dir_*` align with the active JSON.

---

## 4. Class balance stats by horizon

From `label_statistics` (governed rows with movement labels present), example **5c**: `move` 3 261 vs `no_move` 2 403; among `valid_dir=1`, **up** 1 646 vs **down** 1 615 (~50/50). Other horizons show similar near balance on the conditional set (see JSON per horizon).

**Original tri-class baseline (reference):** `data/phase5_discrimination_audit_v1_snapshot.json` — e.g. **5c** ~25.9% up / ~27.7% down / ~46.5% flat (flat-majority).

---

## 5. Schema / storage changes

**Labels (per horizon H):** `outcome_dir_{H}`, `outcome_move_{H}`, `valid_dir_{H}`, `threshold_move_{H}` (audit); legacy `outcome_move_thr_pts_{H}` where applicable.  
**Predictions:** `pred_dir_up_prob_{H}`, `pred_dir_down_prob_{H}`, `pred_move_prob_{H}`, `pred_no_move_prob_{H}` plus legacy mirrors `pred_{H}_dir_*`, `pred_{H}_move_*`.  
**Snapshot model:** `db.SnapshotRow` / migrations in `db.py`.

---

## 6. Training changes

- **Direction:** `ml_train.load_data` filters `CAST(valid_dir_{hz} AS INTEGER) = 1` when training on `outcome_dir_{hz}`.
- **Move:** trained on full eligible rows for `outcome_move_{hz}`.
- Artifacts: `xgb_{TICKER}_{hz}_dir.pkl`, `xgb_{TICKER}_{hz}_move.pkl` (+ meta JSON) under per-ticker model dirs.

---

## 7. Inference contract

**Option 1 (implemented):** When movement XGB heads load, **direction probabilities are emitted for every scored row** (same engineered snapshot as training). **Evaluation** of `outcome_dir_{H}` still restricts to `valid_dir_{H}=1`. Documented in `ml_predict._predict_xgb_movement_heads` and `calibration/movement_target_eval_common_v1.py`.  
Binary heads are normalized to sum to 1; values clipped to finite non-negative.

---

## 8. Baselines used

**Move head:** majority (prior class), always_move, always_no_move, random coin (20 seeds) — see `binary_baselines_move` in Phase 5 / 6.5 movement modules.  
**Dir head (conditional sample):** conditional majority, always_up, always_down, random — `binary_baselines_dir`.

---

## 9. Phase 5 results (new targets)

**File:** `data/movement_target_phase5_discrimination_v1.json`.

- **Label statistics:** populated per horizon (coverage, move/no_move counts, `valid_dir` conditional n and up/down balance).
- **Model metrics (`move_head`, `dir_head`):** **n = 0** for all horizons — **no rows** had both labels and **persisted** `pred_move_prob_*` / `pred_dir_*` probabilities on snapshots (`pred_move_prob_5c` non-null count in DB = **0** at evaluation time).
- **Confidence / ranking (model-based):** not applicable until predictions exist.

---

## 10. Phase 6 results (new targets)

**File:** `data/movement_target_phase6_edge_v1.json`.  
**Result:** `n = 0` trades per horizon; `note: no_trades_or_no_predictions` — gated strategy requires movement + direction probabilities; none persisted.

---

## 11. Phase 6.5 results (new targets)

**File:** `data/phase65_movement_isolation_v1_report.json`.  
Global slices show `n_eligible = 0` for move/dir families because eligibility requires non-null movement head probabilities. **No ACCEPTED** slices from isolation under current persistence.

---

## 12. Phase 6.5 cleanup results (new targets)

**File:** `data/phase65_movement_cleanup_v1_result.json`.  
`policy_usable_count: 0` (no surviving clusters).

---

## 13. Comparison vs original target

| Dimension | Original (3-class) | Movement v1 (this run) |
|-----------|---------------------|-------------------------|
| Label dominance | Flat majority 35–61% by horizon | Direction conditional set roughly balanced when labels present |
| Phase 5 model metrics | Large `n` with `pred_*` triples | **No** persisted movement head preds → metrics empty |
| Phase 6 EV | Computed on tri-class preds | No gated trades without `pred_move`/`pred_dir` |
| Policy inventory | (see legacy phase65 report) | **0** POLICY_USABLE |

---

## 14. Horizon-by-horizon verdicts

| Horizon | outcome_move | outcome_dir | Notes |
|---------|--------------|-------------|-------|
| 1c | **INSUFFICIENT** (model) — no preds | **INSUFFICIENT** (model) — no preds | Labels + threshold search OK |
| 3c | **INSUFFICIENT** | **INSUFFICIENT** | |
| 5c | **INSUFFICIENT** | **INSUFFICIENT** | |
| 8c | **INSUFFICIENT** | **INSUFFICIENT** | |
| 13c | **INSUFFICIENT** | **INSUFFICIENT** | |
| 15c | **INSUFFICIENT** | **INSUFFICIENT** | |
| 60c | **INSUFFICIENT** | **INSUFFICIENT** | |

Threshold selection itself: **PASS** (per `movement_threshold_search_report_v1.json`). **INVALID_FOR_DIR_TARGET** was not required for these horizons in the stored search.

---

## 15. Tests added/run

- `tests/test_movement_target_v1.py` — labels + `valid_dir` / `threshold_move` on fixture DB.
- `tests/test_movement_target_v2_contract.py` — naming, `valid_dir` semantics, sum-to-one style checks.
- `tests/test_movement_target_phase_eval_contract_v1.py` — eval modules import + JSON contracts.

**Command:** `pytest tests/test_movement_target_v1.py tests/test_movement_target_v2_contract.py tests/test_movement_target_phase_eval_contract_v1.py` → **11 passed**.

**Bundle runner:** `python -m calibration.run_movement_target_evaluation_bundle_v1 --db data/ed_console.db`

---

## 16. Final verdict

**FAIL** (for the success gates in the locked brief).

**Satisfied:** Threshold search justified; schema and training/inference contracts implemented; backward-compatible parallel columns; Phase 5–6.5 **pipelines exist** and ran; tests added; Option 1 documented.

**Not satisfied:** No movement/direction probabilities **persisted** on production snapshots in this database → discrimination, edge, isolation, and cleanup cannot show model lift, recall, effect size, confidence monotonicity, or **POLICY_USABLE** slices. Movement outcome columns cover only a **small fraction** of governed rows until a full governed refresh/backfill completes.

**Required to reach PASS:** (1) Train movement heads per ticker/horizon; (2) run batch inference (or online path) to write `pred_move_prob_*` / `pred_no_move_prob_*` / `pred_dir_up_prob_*` / `pred_dir_down_prob_*` to snapshots; (3) complete `outcome_move_*` / `valid_dir_*` backfill for the governed population; (4) re-run `run_movement_target_evaluation_bundle_v1` and re-evaluate gates.

---

*Generated from codebase state and evaluation artifacts at report time.*
