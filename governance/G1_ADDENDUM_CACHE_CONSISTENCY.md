# G1 Addendum - Cache Consistency Investigation

## Purpose

`governance/G1_ADDENDUM_TRAINING_DEPENDENCY.md` established that parallel and cascade training share the on-disk LSTM tensor cache (`lstm_tensors.npz` under `models/cache/features/{feature_cache_key}/`) while transformer tensors use separate NPZ names for parallel vs cascade. This addendum asks whether that LSTM sharing is **correct** (intentionally identical cached payload) or a **hidden bug** (different effective inputs, same cache key). It also summarizes horizon path consistency for primary slugs and the XGB/LSTM/Transformer cache asymmetry. Findings are for G2 risk assessment only; no fixes are proposed.

## Method

Read-only static analysis of `ml_scheduler.py`, `lstm_data.py`, `lstm_model.py`, `training_cache.py`, `ml_horizon.py`, `ml_train.py`, and selected docs. Line numbers refer to the repository state at investigation time. Shell: `git log --grep=...` (read-only). No training, no tests, no edits to existing files.

---

## Q1 - Are parallel-LSTM and cascade-LSTM inputs identical?

### Dataset construction (`build_lstm_dataset`)

- **Function:** `lstm_data.py:599-607` (`def build_lstm_dataset(..., ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,)`).
- **Architecture parameter:** **None.** The signature and docstring (`lstm_data.py:599-628`) do not take `architecture`; there is no `if architecture == "cascade"` inside the builder body in the inspected region (`lstm_data.py:637-681` uses `label_col = outcome_column(hz)`, `extract_rth_snapshots(..., target_column=label_col)`, sliding windows, encodings).
- **Conclusion:** The **cached arrays** `X_5m`, `X_1m`, `X_conf`, and `y` produced by `build_lstm_dataset` are **the same function of** `(tickers, db_path, min_ts_utc, allowed_et_dates, ml_horizon_slug)` for both scheduler architectures. Parallel and cascade both call it with the same pattern (`ml_scheduler.py:608-613` and `ml_scheduler.py:990-995`).

### Parallel LSTM block (`ml_scheduler.py:603-646`)

- Loads or builds `ds` via `load_lstm_feature_cache` / `build_lstm_dataset` / `save_lstm_feature_cache` (`ml_scheduler.py:603-616`).
- Calls `train_lstm(..., dataset=ds, ..., architecture="parallel", ...)` when `ds` has samples (`ml_scheduler.py:622-633`), or `train_lstm` without `dataset` with `architecture="parallel"` in the `else` branch (`ml_scheduler.py:635-645`). In both branches **`xgb_probs` is not passed** (defaults `None` per `lstm_model.py:318`).

### Cascade LSTM block (`ml_scheduler.py:986-1039`)

- Same cache trio: `load_lstm_feature_cache` / `build_lstm_dataset` / `save_lstm_feature_cache` with the same `fdir`, `ticker`, `data_fp`, `fk` (`ml_scheduler.py:986-998`).
- Builds `xgb_probs_list` from the **cascade** `xgb_model` in `out_dir` (`ml_scheduler.py:926-984`, `935-946`, `983-984`).
- Calls `train_lstm(..., architecture="cascade", ...)` with **`xgb_probs`** only when `len(xgb_probs_list) == ds.n_samples` (`ml_scheduler.py:1025-1037`). On length mismatch, logs a warning and calls `train_lstm` **with** `dataset=ds` but **without** `xgb_probs` (`ml_scheduler.py:1010-1024`).

### Where cascade differs: inside `train_lstm`, not in the NPZ

- **Docstring:** `xgb_probs: optional (N, 3) for cascade — concatenated to confluence.` (`lstm_model.py:325-328`).
- **Implementation:** If `xgb_probs` is provided with shape `(N, 3)` matching `len(dataset.y)`, `X_conf = np.hstack([X_conf, xgb_probs.astype(np.float32)])` (`lstm_model.py:355-358`). Otherwise `X_conf` stays as loaded from `dataset`.

### Plain classification (per requested categories)

- **IDENTICAL (cached payload):** **Yes.** `build_lstm_dataset` output is architecture-agnostic; both branches persist the same tensor types to the same NPZ layout via `save_lstm_feature_cache` (`training_cache.py:366-401` saving `dataset.X_5m`, `X_1m`, `X_conf`, `y`).

- **DIFFERENT (final tensors seen by the LSTM network):** **Yes, by design, after load.** Cascade may append three XGB probability columns to `X_conf` inside `train_lstm` (`lstm_model.py:355-358`); parallel does not. That difference is **not stored in** `lstm_tensors.npz`; it is applied at training time.

- **DIFFERENT (silently) / BUG:** **Not supported by static reading** for the **cached** arrays: the cache does not claim to store cascade-augmented `X_conf`. The identity pipeline does not need an `architecture` field to distinguish two different **cached** tensors if both architectures read the same pre-augmentation arrays by construction.

- **DIFFERENT (correctly partitioned) via identity:** **Partitioning is by `feature_cache_key` directory + post-load augmentation**, not by separate NPZ filenames per architecture. `compute_feature_cache_key` explicitly uses the literal `"shared_features"` (`training_cache.py:182-185`) and **does not** include `architecture`.

- **UNKNOWN without runtime:** Whether any **live** row ordering mismatch (`len(xgb_probs_list) != ds.n_samples`, `ml_scheduler.py:1010-1013`) occurs often enough to push cascade through the no-`xgb_probs` fallback while still using a cache built under different row filtering is **not** derivable from static reading alone (see Open questions).

---

## Q2 - Cache identity check sufficiency

### `_feature_identity_matches` (`training_cache.py:349-363`)

- Reads `feature_cache_identity.json`, checks `_canonical_lineage_identity_ok(d)` (`training_cache.py:357-358`), then compares `feature_cache_key`, `ticker`, and normalized `data_fingerprint` (`training_cache.py:359-362`).
- **No `architecture` field** in the predicate.

### Identity file payload (`training_cache.py:329-346`)

- `_write_feature_identity` stores `ticker`, `feature_cache_key`, `data_fingerprint`, feature/preprocessing/label versions, plus `training_canonical_lineage_header()` (`training_cache.py:329-345`). **No `architecture` key** in the written payload.

### `compute_feature_cache_key` (`training_cache.py:167-201`)

- Docstring: **"Shared LSTM / parallel-Transformer / cascade-input tensor cache identity."** (`training_cache.py:170`).
- Hash inputs: `ticker`, `"shared_features"`, canonical contract/timeframe, `data_fp` min/max/row_count/table/timeframe, feature/preprocessing/label versions, **`target_column`**, rolling window constant, `code_fp` (`training_cache.py:182-199`).
- **`target_column` encodes horizon** via the caller (`ml_scheduler.py:1368-1378` uses `target_column = outcome_column(hz_sched)` for `compute_feature_cache_key(ticker, data_fp, code_fp, target_column=target_column)`). Different primary horizons → different `target_column` strings → different `fk` → different cache directories.

### Contrast: `compute_scheduler_cache_key` **does** include architecture

- `compute_scheduler_cache_key(..., architecture, ...)` concatenates `architecture` into the hash (`training_cache.py:119-126`, `143-163`, field at line **146**).

### Answer: cross-architecture load of "wrong" **base** tensors?

**NO (for the cached LSTM tensors themselves),** given the same `ticker`, `data_fp`, `feature_key` (`fk`), and canonical lineage: `build_lstm_dataset` does not branch on architecture, so the serialized `X_5m`/`X_1m`/`X_conf`/`y` are the same object family for that key. Cascade then optionally augments `X_conf` **after** load (`lstm_model.py:355-358`).

**YES (possible semantic mismatch at training intent level)** when the cascade branch hits **`len(xgb_probs_list) != ds.n_samples`** and trains `architecture="cascade"` **without** `xgb_probs` (`ml_scheduler.py:1010-1024`): the code still uses the shared `ds` but **skips** XGB concatenation that cascade is otherwise designed to use (`lstm_model.py:355-356`). That is an **explicit fallback path** (warning logged), not a silent identity miss. Whether it is frequent or harmful is **UNKNOWN** without runtime counts.

---

## Q3 - Horizon code path consistency

### Primary horizons definition (`ml_horizon.py`)

- `PRIMARY_DECISION_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")` (`ml_horizon.py:49`).
- `normalize_ml_horizon_slug` rejects invalid slugs (`ml_horizon.py:79-93`).

### Scheduler horizon selection (`ml_scheduler.py`)

- `run_once(..., ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG)` then `hz_sched = normalize_ml_horizon_slug(ml_horizon_slug)` (`ml_scheduler.py:1256-1268`).
- CLI / `__main__` uses `ED_ML_SCHEDULER_HORIZON` defaulting to `DEFAULT_ML_HORIZON_SLUG` (`ml_scheduler.py:2195`, `2251`). **No hard-coded loop over all four primaries inside a single `run_once` invocation** in the inspected code; one slug per run unless callers invoke multiple times.

### Per-component, per-architecture

| Component | Parallel (`train_parallel_candidate`) | Cascade (`train_cascade_candidate`) | Horizon handling |
|-----------|--------------------------------------|-------------------------------------|-------------------|
| XGB | `train_ticker(..., ml_horizon_slug=hz)` (`ml_scheduler.py:594-600`) | same (`ml_scheduler.py:926-933`) | `hz` threaded; `load_data` / labels via `outcome_column(hz)` upstream (`ml_scheduler.py:521-522`, `832-833`) |
| LSTM dataset | `build_lstm_dataset(..., ml_horizon_slug=hz)` (`ml_scheduler.py:608-613`) | same (`ml_scheduler.py:990-995`) | `label_col` / `outcome_column(hz)` inside builder (`lstm_data.py:637-638`) |
| LSTM train | `train_lstm(..., ml_horizon_slug=hz, architecture="parallel")` (`ml_scheduler.py:623-632`) | `train_lstm(..., architecture="cascade", ml_horizon_slug=hz)` (`ml_scheduler.py:1014-1037`) | Checkpoint paths use `hz` inside `train_lstm` (`lstm_model.py:352-353`, `403`) |
| Transformer | `prepare_transformer_data(..., ml_horizon_slug=hz)` + parallel cache (`ml_scheduler.py:654-674`) | `prepare_transformer_data(..., ml_horizon_slug=hz)` (`ml_scheduler.py:1041-1047`) | Same `hz` argument pattern |

### Horizon-specific branch outside cache (observed discrepancy)

- `force_retrain` active compliance check runs **only** when `hz_sched == DEFAULT_ML_HORIZON_SLUG` (`ml_scheduler.py:1737-1741`). That is a **1c-only** special case for promotion-related behavior, **not** for LSTM cache build/load.

### Missing combinations

Static reading shows **no** branch that omits LSTM or XGB for one primary horizon while retaining it for another inside the two training functions; horizon enters via `hz` / `target_column` / artifact filenames (`xgb_{T}_{hz}.pkl`, etc.). **UNKNOWN** without exhaustive matrix testing: whether secondary horizons (`3c`, `8c`, `13c`) are exercised by the same entry points in production configs.

---

## Q4 - Asymmetry intent

### LSTM: shared cache (`training_cache.py`)

- Module docstring lists a single features subtree with `lstm_tensors.npz` alongside parallel and cascade transformer artifacts (`training_cache.py:4-9`).
- `compute_feature_cache_key` docstring labels the key **shared** across LSTM and transformer caches (`training_cache.py:170`).
- **Verdict:** **INTENTIONAL** for LSTM+parallel-transformer+cascade-input **keying** at the feature-dataset layer, documented in code.

### Transformer: separate NPZ names (`training_cache.py`)

- `TRANSFORMER_NPZ_NAME = "transformer_parallel_tensors.npz"` vs `CASCADE_TF_NPZ_NAME = "cascade_transformer_xgb_lstm.npz"` (`training_cache.py:37-38`).
- Cascade cache helpers bind XGB meta + LSTM `.pt` shas (`training_cache.py:497-503`, `516-521`).
- **Verdict:** **INTENTIONAL** — filenames and `cascade_tensor_bind_slug` document distinct **input tensors** for cascade transformer vs parallel.

### XGB: no feature-cache NPZ

- `ml_train.py` references `training_cache` for fingerprint/normalization (`ml_train.py:587`, `698`) but **no** `save_*xgb*` in `training_cache.py` in the inspected layout (tensor caches are LSTM + transformer variants only, `training_cache.py:4-9`).
- **Verdict:** **INTENTIONAL or pragmatic default** — **no strong doc comment** in `ml_train.py` stating "XGB is too cheap to cache"; absence of XGB NPZ cache is **ACCIDENTAL** from a documentation perspective but **coherent** with `training_cache.py` scope (feature **tensor** cache, not tabular XGB training rows).

### Architecture spec (`docs/architecture_parallel_vs_cascade_competition_spec.md`)

- Allows **shared canonical cached tensors** for fair comparison (`docs/architecture_parallel_vs_cascade_competition_spec.md:44-48`, `65-68`).
- Describes cascade staged inputs (XGB probs into later stages) (`docs/architecture_parallel_vs_cascade_competition_spec.md:57-63`).

### `lstm_model.py` header

- States support for parallel vs cascade with different confluence handling (`lstm_model.py:1-5`).

### Git history (this clone)

- `git log --all --oneline --grep="cache"` / `--grep="transformer"` returned only recent unrelated commits in this environment. **No** commit-message proof of original cache design beyond current files.

### Overall asymmetry classification

- **INTENTIONAL:** Shared `fk` for LSTM base tensors + **separate** cascade transformer tensor artifacts + **explicit** `train_lstm` XGB concat (`lstm_model.py:355-358`, `training_cache.py:170`, `37-38`).
- **HALF-IMPLEMENTED:** **Not evidenced** as an abandoned partial migration: LSTM sharing aligns with docstring `"shared_features"`; transformer split is complete with distinct loaders in `ml_scheduler.py` (`648-663` vs `1059-1062`).

---

## Q5 - Verdict on cache safety for G2

**Classification: SAFE (for the LSTM NPZ as designed), with explicit caveats.**

**Reasoning (ties Q1-Q4):**

1. Cached content is **architecture-agnostic** by construction (`lstm_data.py:599-607`, `ml_scheduler.py:608-613`, `990-995`).
2. Cascade-specific **XGB probability channels** are merged **after** cache load in `train_lstm` (`lstm_model.py:355-358`), not in the NPZ.
3. `compute_scheduler_cache_key` already separates **full-run** identity by `architecture` (`training_cache.py:146`), while `compute_feature_cache_key` intentionally omits it for **shared feature tensors** (`training_cache.py:170`, `182-185`).
4. The **mismatch fallback** (`ml_scheduler.py:1010-1024`) is a **known** alternate code path (logged), not a silent identity failure.

**UNCLEAR sub-area (does not flip verdict to UNSAFE without evidence):** operational frequency and impact of the mismatch fallback.

---

## Implications for G2

- **SAFE:** G2 may proceed without a **mandatory** pre-G2 cache-layer rewrite **for LSTM NPZ sharing**, provided G2 documentation / invariants explicitly state:
  - `lstm_tensors.npz` stores **pre-XGB-concat** tensors only;
  - cascade XGB channels are applied in `train_lstm` (`lstm_model.py:355-358`);
  - `compute_feature_cache_key` is **intentionally** architecture-free (`training_cache.py:170`, `182-185`).
- **Not in G2 scope by default:** Changing `compute_feature_cache_key` or `_feature_identity_matches` to add `architecture` would **invalidate** existing caches and duplicate storage; treat as a **separate** cache-design change unless product owners require stricter on-disk separation.
- **If** runtime traces show heavy use of `ml_scheduler.py:1010-1024` fallback, a **follow-on** task (not prescriptive here) could analyze whether cascade training quality is degraded; still not the same class of bug as "wrong NPZ bytes for architecture."

---

## Open questions for runtime tracing

1. **Frequency of `xgb_probs_list` vs `ds.n_samples` mismatch**  
   - **Where:** log already exists at `ml_scheduler.py:1012-1013`.  
   - **Capture:** count per (ticker, horizon) run; correlate with `used_feature_cache` flag.  
   - **Interpret:** high rate implies cascade often trains without XGB concat despite cascade intent.

2. **Byte-identical `ds` for parallel-first vs cascade-first same day**  
   - **Where:** after `build_lstm_dataset` in both branches, optional hash of `ds.X_conf.tobytes()` (temporary instrumentation — not implemented in this task).  
   - **Interpret:** identical hashes confirm ordering of parallel vs cascade does not change builder inputs when cache misses.

3. **Horizon matrix smoke**  
   - **What:** run scheduler (or unit path) once per `PRIMARY_DECISION_HORIZONS` slug (`ml_horizon.py:49`) with small ticker subset.  
   - **Look for:** any cache dir collisions or `normalize_ml_horizon_slug` failures (`ml_horizon.py:87-92`).

4. **Resume checkpoint `arch_ok` / `xgb_probs_fp`**  
   - **Where:** `lstm_model.py:427-432` compares resume blob to current `architecture` and `_lstm_xgb_probs_fp(xgb_probs)`.  
   - **Interpret:** confirms training-time state distinguishes cascade vs parallel even when NPZ is shared.

---

**File created:** `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md` only (this task).  
**No `.py` or pre-existing `.md` modified.**  
**Commands:** `git log --grep=...` (read-only).

**RESULT: PASS**
