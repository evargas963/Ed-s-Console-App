# Checkpoint + provenance lock (v1)

## 1. Checkpoint manifest

Canonical file: `data/checkpoint_manifest_v1.json`  
Fields: `checkpoint_id` `movement_pass_v1`, `created_utc`, `git_commit` (null if no repo), `git_changed_files_vs_head`, `db_path`, `artifact_root`, `reports_declaring_pass`, `relevant_scripts`, `code_state_files_pass_related`, `pass_state_metrics`.

## 2. PASS-state summary

From `data/checkpoint_manifest_v1.json` → `pass_state_metrics`: governed_total **62098**; coverage `overall_verdict` **PASS**; per-horizon `coverage_move` / `coverage_dir` **1.0**; backfill `row_move_ok` / `row_dir_ok` **62098**; `phase65_isolation_accepted_total` **38**; cleanup pipeline `initial_accepted` **50**, `after_hard_filter` **46**, `after_subsumption` **23**; `policy_usable_count` **23**.

## 3. Policy-usable inventory summary

Machine-readable: `data/policy_usable_inventory_v1.json` (23 slices; fields include `slice_id`, `horizon`, `family`, `dimensions`, `sample_size`, `accuracy`, `cleanup_classification`, `source_cleanup_path`, `source_isolation_path`, `isolation_verdict`, `oos`, `metrics`, `cloned_or_non_native_inference_touches_slice`, `clone_touch_detail`).  
Readable table: `data/policy_usable_inventory_v1_summary.md`.

## 4. Artifact provenance matrix summary

Machine-readable: `data/artifact_provenance_matrix_v1.json`  
Row count **308** (`models/active/**/xgb_*_{1c|3c|5c|8c|13c|15c|60c}_{move|dir}.pkl`). Counts: `cloned_y` **3**, `augmented_data_trained_y` **11** (heuristic: move triple + dir with `meta.samples` < 6 and not cloned), `minimum_row_exception_used_y` **55** (`meta.samples` < 80), `native_trained_y` **250** (not cloned, not augmented heuristic, samples ≥ 80). Per-row: paths, `loadable_y`, clone source fields where applicable.

## 5. Cloned-head classifications

| Artifact (absolute path under repo) | Classification |
|-------------------------------------|----------------|
| `models/active/TSL/xgb_TSL_15c_dir.pkl` | **ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY** |
| `models/active/TSL/xgb_TSL_60c_dir.pkl` | **ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY** |
| `models/active/PCG/xgb_PCG_60c_dir.pkl` | **ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY** |

Evidence: each `*_dir_meta.json` contains `cloned_from_horizon` and `clone_note`; `load_data` for those ticker/horizon/dir labels had **0** RTH rows in `snapshots_1m_normalized` (documented in `clone_note`).  
**Policy-usable overlap:** slice `global|horizon=60c|family=dir` has `cloned_or_non_native_inference_touches_slice` **true** in `data/policy_usable_inventory_v1.json` (governed inference uses these pkls for TSL and PCG at 60c dir). No other of the 23 slices flags `clone_touch` **true** in that inventory.

## 6. Cold-start inference validation

Artifact: `data/cold_start_inference_checkpoint_v1.json`  
Procedure: `reset_caches()`, clear `ml_predict._xgb_movehead_registry`, random governed row per sampled ticker, one random horizon per row, `_predict_xgb_movement_heads`; check finite probs and move/dir pair sums ≈ 1.  
Result: `all_ok` **true** (12 sample rows).

## 7. Evaluation protocol lock

Artifact: `data/evaluation_protocol_lock_v1.json`  
Locks: governed SQL predicate (coverage validator), column names checked, hard fail coverage **0.95**, warn target **0.99**, sum tolerance **0.002**, default integrity sample size **8000**; bundle command list; `policy_usable_definition` string; OOS reference path into isolation JSON; cleanup script path; warnings vs hard fails description.

## 8. Immediate blockers assessment

| Check | Classification |
|-------|----------------|
| Dedicated policy-usable inventory present | **NON-BLOCKER** |
| Cloned dir heads vs policy slice `global\|horizon=60c\|family=dir` | **NOTE** (documented in inventory + provenance; not native 60c dir for TSL/PCG) |
| Checkpoint / paths reproducible | **NON-BLOCKER** |
| Cold-start inconsistency | **NON-BLOCKER** (`all_ok` true) |
| Provenance / hidden substitution | **NON-BLOCKER** (matrix + clone list explicit) |

## 9. Final verdict

**READY_FOR_CALIBRATION**
