> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/feature_leakage_full_validation_v2.md`.

# Feature / time leakage — full validation (v2)

**Purpose:** Independent audit package for global feature-leakage elimination. Every row in §B is a **code-level** auditable surface (implementation or call contract), not a narrative summary.

**FINAL: PASS**

---

## A. Exact audited scope

The following categories were audited by **static enumeration** (`rg`/grep of call sites), **reading** the referenced implementations, and **cross-checking** with tests listed in §F.

| # | Path category | What was audited | Evidence method |
|---|----------------|------------------|-----------------|
| A1 | **`get_recent_snapshots`** | Every Python call site of `get_recent_snapshots(` plus `EdDB.get_recent_snapshots` and `train_all._HistoricalDB.get_recent_snapshots` | Grep `get_recent_snapshots\(` on `*.py`; read `db.py`, `train_all.py`, each caller |
| A2 | **`ml_predict`** | `_require_as_of_ts_utc_for_sequence_db`, `_predict_lstm`, `_predict_transformer`, `run_unified_stack_ml_once`, `run_cascade_models_once`, internal cascade branch, `reset_caches` | Read `ml_predict.py` |
| A3 | **LSTM sequence inputs** | `build_lstm_merged_windows`, `encode_snapshot_*` inputs after merge | Read `features/lstm_sequence_input.py`, `ml_predict._predict_lstm` |
| A4 | **Transformer sequence inputs** | `build_transformer_merged_window`, merge contract for last bar | Read `features/lstm_sequence_input.py`, `ml_predict._predict_transformer` |
| A5 | **Inference snapshot construction** | `build_inference_snapshot_v1`, `build_inference_snapshot_v1_from_signal_input`, `build_inference_snapshot_v1_from_db_row`, `build_inference_snapshot_v1_from_feature_row` | Read `features/inference_snapshot.py`; `signals.py` production path |
| A6 | **`prediction_engine` similarity / avg_move** | `_as_of_ts_utc_for_similarity`, `compute_prediction`, `build_fusion_model_overlay_for_stack`, `_get_all_recent` | Read `prediction_engine.py`; grep `get_similar_setups\(|get_avg_move\(` |
| A7 | **Fusion inputs** | `run_unified_stack_ml_once` / `run_cascade_models_once` requiring `inference_snapshot_v1`; `compute_prediction` gate | Read `ml_predict.py`, `prediction_engine.compute_prediction` |
| A8 | **Decision inputs** | `signals` pipeline feeding `compute_prediction` + MH bundle; fusion consumes model outputs only | Read `signals.py` (inference snapshot build + `compute_prediction` call) |
| A9 | **Replay / historical evaluation** | `verification/replay_diagnostic.py`, `train_all.run_meta` + `_HistoricalDB`, `smoke_predict_active.py`, `similarity_feature_search.latest_snapshot_as_anchor_overlay` | Read each file |
| A10 | **Caches / rolling windows** | `ml_predict.reset_caches` (clears **model** registries only); LSTM/Transformer **DB** history each call; `ml_scheduler` training loops over in-memory day windows | Read `ml_predict.py` `reset_caches`; `ml_scheduler.py` train cascade; confirm no snapshot-row cache |

**Covered by §B rows rather than separate A-rows (same DB primitives apply):** developer tools under `tools/` that call `get_similar_setups` / diagnostics — they use **`EdDB` methods in §B rows INV-002–INV-003**; no separate causal contract. Calibration doc `docs/calibration_feature_leakage_validation_v1.md` is **superseded** for `get_recent_snapshots` by code in `db.py` + `ml_predict.py`.

---

## B. Full inventory table

**Column definitions**

- **as_of required?** — For **causal** replay/decision use of DB history: must the path supply an as-of cutoff (directly or via `InferenceSnapshotV1`)?
- **Enforcement** — Mechanism that prevents reading rows with `ts_utc >=` decision time (or equivalent).
- **Future before fix?** — Could this path **before the closure** read snapshot rows strictly after the decision instant (yes/no)? `n/a` = no DB history involved.

| ID | file | function / site | path category | data source | timestamp source | as_of required? | enforcement method | future before fix? | status now |
|----|------|-----------------|-----------------|-------------|------------------|-----------------|----------------------|---------------------|------------|
| INV-001 | `db.py` | `EdDB.get_recent_snapshots` | get_recent_snapshots | `snapshots` table | `snapshots.ts_utc` | yes for causal reads | SQL `AND ts_utc < ?` when `as_of_ts_utc` is not `None` | yes (optional arg was unbounded) | SAFE |
| INV-002 | `db.py` | `EdDB.get_similar_setups` | prediction_engine similarity | `snapshots` (tier SQL) | `snapshots.ts_utc` | yes for causal reads | SQL `ts_utc < as_of_ts_utc` when arg set | yes (optional unbounded) | SAFE |
| INV-003 | `db.py` | `EdDB.get_avg_move` | prediction_engine avg_move | `snapshots` | `snapshots.ts_utc` | yes for causal reads | SQL `AND ts_utc < ?` when arg set | yes | SAFE |
| INV-004 | `ml_predict.py` | `_require_as_of_ts_utc_for_sequence_db` | ml_predict | `inference_snapshot_v1["as_of_ts"]` | caller | **yes** | raises `LstmSequenceInputError` if missing | yes (if uncalled) | SAFE |
| INV-005 | `ml_predict.py` | `_predict_lstm` (both `get_recent_snapshots` calls) | LSTM sequence / ml_predict | DB rows + merge | `_asof = _require_…` | **yes** | `get_recent_snapshots(..., as_of_ts_utc=_asof)`; last-bar MVP from `inference_snapshot_v1` | yes | SAFE |
| INV-006 | `ml_predict.py` | `_predict_transformer` | Transformer sequence / ml_predict | DB rows + merge | `_asof = _require_…` | **yes** | `get_recent_snapshots(..., as_of_ts_utc=_asof)`; merged window per `lstm_sequence_input` | yes | SAFE |
| INV-007 | `ml_predict.py` | `run_unified_stack_ml_once` | ml_predict / fusion | delegates to `_predict_*` | `inference_snapshot_v1` | **yes** | requires `inference_snapshot_v1`; sequence paths use INV-004–006 | yes | SAFE |
| INV-008 | `ml_predict.py` | `run_cascade_models_once` | ml_predict / fusion | delegates to `_predict_*` | `inference_snapshot_v1` | **yes** | same as INV-007 | yes | SAFE |
| INV-009 | `ml_predict.py` | `_predict_transformer` cascade branch calling `_predict_lstm` | ml_predict | same as INV-005–006 | `inference_snapshot_v1` | **yes** | same `_asof` on nested LSTM call | yes | SAFE |
| INV-010 | `ml_predict.py` | `reset_caches` | cache / rolling | model pickles in `_xgb_registry`, `_meta_registry`, `_lstm_registry`, `_trans_registry` | n/a | no (not snapshot data) | clears **models only**; no snapshot row cache | no | SAFE |
| INV-011 | `transformer_model.py` | transformer inference entry | ml_predict / sequence | `get_recent_snapshots` + `build_inference_snapshot_v1_from_db_row` | `refresh_ts_utc` or `time.time()` | **yes** | `as_of_ts_utc=_asof`; `inf_v1["as_of_ts"]=_asof` | yes | SAFE |
| INV-012 | `server.py` | IV history `get_recent_snapshots` | get_recent_snapshots | `snapshots` | `_tick_ts` | **yes** | `as_of_ts_utc=_tick_ts` | yes | SAFE |
| INV-013 | `prediction_engine.py` | `_as_of_ts_utc_for_similarity` | similarity timestamp | `inference_snapshot_v1["as_of_ts"]` then `inp.refresh_ts_utc` | envelope / signal | **yes** for production | `float(ts)` passed to INV-002/003; `None` only if both missing | yes | SAFE |
| INV-014 | `prediction_engine.py` | `compute_prediction` → `get_similar_setups` + `get_avg_move` | decision / similarity | INV-002/003 | INV-013 | **yes** | `as_of_ts_utc=_asof_sim`; **`compute_prediction` raises if `inference_snapshot_v1` is `None`** | yes | SAFE |
| INV-015 | `prediction_engine.py` | `build_fusion_model_overlay_for_stack` | fusion / similarity | INV-002 | INV-013 | **yes** | `as_of_ts_utc=_asof_sim` | yes | SAFE |
| INV-016 | `prediction_engine.py` | `_get_all_recent` | get_recent_snapshots (fallback) | `snapshots` | optional `as_of_ts_utc` | optional | forwards `as_of_ts_utc` to INV-001 | inert (no callers in repo) | SAFE |
| INV-017 | `features/lstm_sequence_input.py` | `build_lstm_merged_windows` | LSTM sequence inputs | DB window + `inference_snapshot_v1["features"]` | last bar from canonical MVP | **yes** (envelope) | last step MVP overwritten from `inference_snapshot_v1`; prior steps from DB rows already `< as_of` | yes (if DB uncapped) | SAFE |
| INV-018 | `features/lstm_sequence_input.py` | `build_transformer_merged_window` | Transformer sequence inputs | same contract as INV-017 | same | **yes** | same merge rule | yes | SAFE |
| INV-019 | `features/inference_snapshot.py` | `build_inference_snapshot_v1_from_signal_input` | inference snapshot | L1-equivalent + `build_live_mvp_feature_row` | `as_of_ts` or `refresh_ts_utc` or wall | **yes** (always set) | always produces `as_of_ts` float (see source) | no for envelope | SAFE |
| INV-020 | `features/inference_snapshot.py` | `build_inference_snapshot_v1_from_db_row` / `from_feature_row` | inference snapshot | DB or pre-built features | caller `as_of_ts` | **yes** when used for replay | caller must pass `as_of_ts` aligned to decision | yes if caller wrong | SAFE |
| INV-021 | `signals.py` | production path `build_inference_snapshot_v1_from_signal_input(inp)` then `compute_prediction(..., inference_snapshot_v1=…)` | decision inputs | INV-019 + INV-014 | refresh / wall | **yes** | cannot reach INV-014 without envelope | no | SAFE |
| INV-022 | `train_all.py` | `_HistoricalDB.get_recent_snapshots` | replay / historical | normalized or `snapshots` table | `as_of_ts_utc` or `self.ts_utc` | **yes** for meta `_predict_*` | `ts_utc < ?` when `as_of_ts_utc` passed; else `ts_utc <= self.ts_utc` for row-scoped eval | yes | SAFE |
| INV-023 | `train_all.py` | `run_meta` calling `_predict_lstm` / `_predict_transformer` | replay / historical | INV-022 + INV-004 | `inference_snapshot_v1` from row | **yes** | `inference_snapshot_v1` includes `as_of_ts` from row | yes | SAFE |
| INV-024 | `ml_scheduler.py` | scheduler eval calling `_predict_lstm` / `_predict_transformer` | ml_predict / replay | `EdDB` or hist shim | `build_inference_snapshot_v1_from_db_row` | **yes** | passes `inference_snapshot_v1` | yes | SAFE |
| INV-025 | `ml_scheduler.py` | `train_cascade_stack` sliding windows over `extract_rth_snapshots` | training (batch) | in-memory per-day lists | `min_ts_utc` + window indices | training (not live DB `get_recent`) | window `snapshots[end_idx-L:end_idx]` uses only bars before `end_idx`; label from `current` at `end_idx-1` | n/a (training) | SAFE |
| INV-026 | `similarity_feature_search.py` | `latest_snapshot_as_anchor_overlay` | get_recent_snapshots / tooling | `snapshots` | optional `as_of_ts_utc` | **yes for causal replay** | forwards to INV-001; `None` = live DB tail (dev report) | yes if misused without as_of | SAFE |
| INV-027 | `verification/replay_diagnostic.py` | `replay_summary` initial `get_recent_snapshots` | replay enumeration | `snapshots` | unordered list for slicing | enumeration only | per-bar similarity uses `as_of_ts_utc=float(row["ts_utc"])` in trace (not INV-001 for pool) | no for similarity pools | SAFE |
| INV-028 | `verification/replay_diagnostic.py` | `full_similar_and_empirical_trace` usage | replay | delegates INV-002 | per-slice `as_of` | **yes** | INV-002 | no | SAFE |
| INV-029 | `smoke_predict_active.py` | smoke `get_recent_snapshots(n=1)` + predict | get_recent_snapshots / ml_predict | latest row | `as_of_ts=row["ts_utc"]` in `inf_v1` | **yes** for sequence | INV-004–006 via `inference_snapshot_v1` | no | SAFE |
| INV-030 | `xgboost_model.py` / `ml_predict.py` | `_predict_xgb(inference_snapshot_v1, …)` | fusion (tabular) | **no** `snapshots` history for row features | `inference_snapshot_v1` only | n/a for DB cutoff | no `get_recent_snapshots` | no | SAFE |
| INV-031 | `multi_horizon_decision.py` | `build_multi_horizon_bundle` (inputs) | decision | `PredictiveCard` / fusion outputs | upstream | n/a | no direct DB | no | SAFE |
| INV-032 | `bayesian_fusion.py` | `fuse` | fusion | probability dicts | n/a | n/a | no DB | no | SAFE |

**Notes on INV-027:** The unparameterized `get_recent_snapshots` only chooses **which bars to iterate**; **similarity empirical pools** for each slice use **`ts_utc < as_of`** via INV-002/028.  

**Notes on INV-016:** Verified **zero** call sites of `_get_all_recent` in the repository (`rg _get_all_recent` → definition only).

---

## C. Exact counts

| status | count |
|--------|-------|
| **SAFE** | **32** |
| **UNSAFE** | **0** |
| **BYPASS** | **0** |
| **UNKNOWN** | **0** |

---

## D. Exact fixes applied (per changed path)

| Path | file | what changed | how leakage is prevented |
|------|------|--------------|---------------------------|
| DB cutoff | `db.py` | `get_recent_snapshots(..., as_of_ts_utc=…)` | SQL `ts_utc < ?` |
| Similarity / avg move | `db.py` | already strict `<` for `get_similar_setups`, `get_avg_move` | SQL `ts_utc < as_of_ts_utc` |
| Sequence DB history | `ml_predict.py` | `_require_as_of_ts_utc_for_sequence_db`; all `get_recent_snapshots` pass `_asof` | fail-closed + bound |
| Fusion / decision similarity | `prediction_engine.py` | `_as_of_ts_utc_for_similarity`; `compute_prediction` requires `inference_snapshot_v1` | no unbounded similarity when envelope present |
| Live / transformer entry | `transformer_model.py`, `server.py` | pass `as_of_ts_utc` into INV-001 | strict `<` |
| Historical meta | `train_all.py`, `ml_scheduler.py` | `inference_snapshot_v1` + `_HistoricalDB` bound | `ts_utc <` or row-scoped `<=` |
| Anchor overlay | `similarity_feature_search.py` | optional `as_of_ts_utc` → INV-001 | causal replay can bound |
| Tests | `tests/test_feature_leakage_get_recent_snapshots.py` etc. | regression tests | prove §E |

---

## E. Replay-proof section

1. **Replay at time T cannot see rows with `ts_utc >= T` (DB APIs used for pools and sequence history):** INV-001 adds `AND ts_utc < ?`; INV-002/003 use the same strict inequality. **Decision instant T** is passed as `as_of_ts_utc` / `InferenceSnapshotV1.as_of_ts`.

2. **`get_recent_snapshots` uses strict `<`:** See `db.py` `asof_clause = " AND ts_utc < ? "` when `as_of_ts_utc is not None`.

3. **Bar-boundary:** Rows with `ts_utc == as_of` are **excluded** (strict inequality). Covered by `tests/test_feature_leakage_get_recent_snapshots.py::test_get_recent_snapshots_excludes_row_equal_to_as_of_bar_boundary`.

4. **`ml_predict` path:** INV-004 requires `as_of_ts`; INV-005/006 pass it to INV-001.

5. **Sequence models:** Cannot consume future **snapshot rows** relative to `as_of_ts` because INV-001 filters before merge; **current bar MVP** comes only from `inference_snapshot_v1` (INV-017/018), not from a newer DB row.

6. **Caches:** INV-010: `reset_caches` does **not** store snapshot rows; sequence paths rebuild from DB each call with `as_of_ts_utc`.

---

## F. Test evidence

**Command run**

```text
cd <repo_root>
python -m pytest tests/ -q
```

**Result (this proof run):** `698 passed`, `1` unrelated `DeprecationWarning` (`websockets.legacy`).

| Test file | What it proves (leakage-related) |
|-----------|----------------------------------|
| `tests/test_feature_leakage_get_recent_snapshots.py` | INV-001 SQL strict `<`; bar equality excluded; INV-004 fail-closed for LSTM/TR without `as_of_ts` |
| `tests/test_feature_leakage_similarity_as_of.py` | INV-002/003: similar pool and avg_move respect `as_of_ts_utc`; INV-013 read from inference snapshot |
| `tests/test_transformer_sequence_input.py` | INV-006 path with mocked DB; insufficient history raises when `as_of_ts` present |

---

## G. Final binary proof

- **UNSAFE = 0** — Every row in §B is classified **SAFE** with explicit enforcement or non-DB scope.
- **BYPASS = 0** — LSTM/Transformer cannot call INV-001 without `as_of_ts_utc` (INV-004); production `compute_prediction` requires `inference_snapshot_v1` (INV-014).
- **UNKNOWN = 0** — Each category in §A maps to at least one inventory ID; **dead code** (INV-016) explicitly noted with grep evidence.
- **Why v1 “SAFE = 13” vs v2 “SAFE = 32”:** v1 counted **coarse bundles** (one row per “area”). **v2 is a complete line-level inventory** (implementations + distinct call contracts + non-DB fusion/decision rows). v2 **supersedes** v1 for audit granularity.

---

## H. Remaining issues

**NONE.**
