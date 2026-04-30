# G1 Addendum — Training Dependency Investigation

## Purpose

G1 (`governance/G1_DIAGNOSIS.md`) established artifact contracts, drift, and governance bypass surfaces. It did **not** fully characterize whether **cascade training consumes anything produced by parallel training** in the same scheduler cycle beyond shared raw inputs. This addendum answers that question with static citations so G2 (cascade meta writer) can assume correct data-flow boundaries.

## Method

Read-only inspection of Python sources and markdown specs. Line numbers refer to the repository state at investigation time. Shell commands used: `Test-Path`, `Get-ChildItem`, `rg` (via workspace grep tool / PowerShell), `git log --grep=...` (read-only). No code edits, no training, no tests executed beyond those read-only commands.

---

## Q1 — Does cascade read parallel artifacts?

### Walk of `train_cascade_candidate` (`ml_scheduler.py:816-1201`)

- **Output / reads under candidate dir:** `out_dir` is the function argument; callers pass the cascade candidate leaf (`ml_scheduler.py:1219-1223` `_train_cascade` sets `dest = ... CASCADE_DIR / ticker` and calls `train_cascade_candidate(..., dest, ...)`).
- **Tabular data:** `df = load_data(...)` reads the SQLite DB, not `models/parallel/` (`ml_scheduler.py:913-918`).
- **XGB:** `train_ticker(..., model_dir=out_dir, ...)` writes and subsequent `open(xgb_path)` reads **under `out_dir`** only (`ml_scheduler.py:926-946`, `935-946`).
- **LSTM dataset:** `fdir = feature_cache_dir(fk)` (`ml_scheduler.py:890` with `fk` from caller). `load_lstm_feature_cache(fdir, ...)` / `save_lstm_feature_cache` use `models/cache/features/{feature_cache_key}/` (`training_cache.py:34`, `204-207`, `366-404`, `406-451`). Paths are under **cache**, not `models/parallel/<ticker>/`.
- **Cascade transformer tensor cache:** `load_cascade_transformer_tensor_cache` / `save_cascade_transformer_tensor_cache` (`ml_scheduler.py:1059-1174`) — cascade-specific NPZ naming per `training_cache.py:37-39` (`CASCADE_TF_NPZ_NAME`, `CASCADE_TF_IDENTITY_NAME`).
- **String "parallel" inside the function:** Only the **warning log** when `len(xgb_probs_list) != ds.n_samples` and `train_lstm(..., architecture="cascade")` is invoked without `xgb_probs` (`ml_scheduler.py:1010-1024`). That branch still uses `model_dir=out_dir` (cascade dir); it does **not** open `PARALLEL_DIR`.

### `run_once` ordering vs `train_cascade_candidate` internals

In `run_once`, parallel training runs **before** cascade for the same ticker when neither path is skipped (`ml_scheduler.py:1586-1608` then `ml_scheduler.py:1631-1648`). Both receive the **same** `feature_cache_key=fk` (`ml_scheduler.py:1378`, `1595`, `1640`). That affects **cache directory sharing** (Q3), not direct reads of `models/parallel/<ticker>/*.pkl` inside `train_cascade_candidate`.

### Search for reads from `models/parallel/<ticker>/` during cascade training

Within `train_cascade_candidate` (`ml_scheduler.py:816-1201`), there is **no** reference to `PARALLEL_DIR`, `parallel_out`, or a path literal `models/parallel`. Model I/O is `out_dir / ...` or `fdir / ...` (cache).

### Plain answer

**NO** — `train_cascade_candidate` does **not** read model checkpoints, manifests, or pickles from `models/parallel/<ticker>/`. It reads/writes cascade artifacts under `out_dir` (cascade candidate dir) and reads/writes **shared** disk cache under `models/cache/features/<feature_cache_key>/` per `training_cache.py:4-9` and `ml_scheduler.py:890`.

**PARTIAL** qualification (cache, not parallel artifacts): cascade may **reuse LSTM tensor cache files** that parallel training **wrote earlier in the same `run_once` iteration** (or on a prior run) because both use the same `fk` and `feature_cache_dir(fk)` (`ml_scheduler.py:1378`, `1595`, `1640`, `988-998`). That is **not** reading parallel **model** artifacts; it is reading **precomputed LSTM dataset tensors** from a shared cache directory. See Q3.

---

## Q2 — What do cascade `_predict_*` calls load?

### Resolver: `_model_dir_for_ticker` (`ml_predict.py:203-307`)

- With **`ED_XGB_STRICT_ACTIVE_ONLY` truthy** (default), resolution chooses only under `MODEL_DIR / f"active_{hz}" / ticker` or `MODEL_DIR / "active" / ticker` (`ml_predict.py:214-255`).
- With strict **off**, if `_INFER_ARCHITECTURE.get() == "cascade"`, base becomes `MODEL_DIR / "cascade" / ticker` (`ml_predict.py:256-264`).
- Otherwise (strict off, default parallel infer architecture), it may return `MODEL_DIR / "parallel" / ticker`, flat `MODEL_DIR`, or final `MODEL_DIR` (`ml_predict.py:265-307`).

### Loaders (`ml_predict.py:343-388`, `614-651`, `814-867`)

Each of `_load_xgb`, `_load_lstm`, `_load_transformer` sets `base = _model_dir_for_ticker(ticker)` and joins `base / f"xgb_{ticker}_{hz}.pkl"` (and sibling meta / `.pt` names) (`ml_predict.py:349-351`, `620-621`, `820-822`).

### Parallel meta assembly (`ml_scheduler.py:718-775`)

Before the inference loop:

```text
with _strict_off_for_candidate_inference():
    mp.MODEL_DIR = out_dir   # parallel candidate leaf
    mp.reset_caches()
```

(`ml_scheduler.py:725-727`.) Here `out_dir` is the **parallel** candidate directory passed into `train_parallel_candidate` (`ml_scheduler.py:505-508` signature; caller `ml_scheduler.py:801` uses `PARALLEL_DIR / ticker` by default).

So `_predict_*` during **parallel** meta assembly load from **parallel candidate dir** (via strict-off + `MODEL_DIR` set to that leaf, then `_model_dir_for_ticker` flat fallback `ml_predict.py:302-307` returning `MODEL_DIR` when artifacts exist there).

### Cascade training context

`train_cascade_candidate` **does not** call `_predict_xgb` / `_predict_lstm` / `_predict_transformer` in the current code (`ml_scheduler.py:816-1201` contains no such calls). **Hypothetical** future cascade meta (per `governance/G2_PLAN.md`) would mirror parallel meta and set `mp.MODEL_DIR = out_dir` with `out_dir` = cascade candidate dir; under `_strict_off_for_candidate_inference`, the same flat fallback applies, so loads resolve to **cascade-trained** files under that leaf, **not** `models/parallel/`.

### `_INFER_ARCHITECTURE`

Defined as a `ContextVar` defaulting to `"parallel"` (`ml_predict.py:71`). `_cascade_challenger_inference_scope` sets it to `"cascade"` for challenger paths (`ml_predict.py:90-91`). Parallel meta assembly in `ml_scheduler.py` does **not** wrap calls in `_cascade_challenger_inference_scope` (no reference in `ml_scheduler.py:718-775`). Whether cascade meta **must** use that scope in addition to strict-off is **unknowable from static reading alone** if `_model_dir_for_ticker` ever saw `MODEL_DIR` set to repo `models/` root instead of the leaf; G2 should validate with a one-ticker run trace (see Open questions).

### Plain answer

For **current** cascade training: **no** `_predict_*` calls occur, so no loader path is exercised there.

For **documented** parallel meta assembly: `_predict_*` loads checkpoints from **`mp.MODEL_DIR` when set to the parallel candidate leaf**, not from active, via `_model_dir_for_ticker` + non-strict fallback (`ml_predict.py:203-307`, `ml_scheduler.py:725-727`).

For **planned** cascade meta: same mechanism should load **cascade-trained** artifacts under the cascade candidate leaf, **not** parallel-trained weights, provided `mp.MODEL_DIR` points at `models/cascade/<ticker>/` the same way it points at `models/parallel/<ticker>/` today.

---

## Q3 — Shared cache layers

### `models/cache/`

- **Exists:** `Test-Path models/cache` returned `True` (investigation host).
- **File count:** `Get-ChildItem models/cache -Recurse -File` reported **274** files.
- **Python references:** `FEATURE_CACHE_ROOT` / `models/cache/features/...` appear in `training_cache.py`, `training_cache_policy.py`, `ml_scheduler.py` (grep `FEATURE_CACHE_ROOT` / `models/cache` limited to those three files in this repo).

### What `training_cache.py` names "cache"

Module docstring (`training_cache.py:1-14`) states it is **feature tensor cache + scheduler run manifest** — not the same thing as `scheduler_run_manifest.json` skip logic alone. Layout includes:

- `models/cache/features/{feature_cache_key}/` with `lstm_tensors.npz`, `lstm_dataset_meta.json`, `transformer_parallel_tensors.npz`, `cascade_transformer_xgb_lstm.npz`, etc. (`training_cache.py:4-9`, `34-39`).

`feature_cache_dir` (`training_cache.py:204-207`) creates that per-`fk` directory.

### LSTM feature cache — **shared** between architectures

`save_lstm_feature_cache` / `load_lstm_feature_cache` (`training_cache.py:366-451`) read/write `LSTM_NPZ_NAME` / `LSTM_META_NAME` in the **same** `cache_dir`. Identity file `feature_cache_identity.json` is matched with `_feature_identity_matches` (`training_cache.py:349-363`, `419-421`) using `ticker`, `data_fp`, and `feature_key` — **no `architecture` field** in that match.

**Writers:** whichever branch (`train_parallel_candidate` or `train_cascade_candidate`) first builds an LSTM dataset and saves cache (`ml_scheduler.py:616-617` parallel; `ml_scheduler.py:997-998` cascade).

**Readers:** the other architecture when `load_lstm_feature_cache` hits (`ml_scheduler.py:588-589` parallel; `ml_scheduler.py:988-989` cascade).

### Transformer caches — **not** symmetric

- **Parallel-only NPZ name:** `TRANSFORMER_NPZ_NAME = "transformer_parallel_tensors.npz"` (`training_cache.py:37`). Used from `train_parallel_candidate` via `load_transformer_parallel_cache` / `save_transformer_parallel_cache` (`ml_scheduler.py:648-663`).
- **Cascade:** `load_cascade_transformer_tensor_cache` / `save_cascade_transformer_tensor_cache` (`training_cache.py:38-39` names; `ml_scheduler.py:1059-1174`). Separate files under the same `fdir`.

So: **parallel transformer tensor cache is not loaded by `train_cascade_candidate`** (no call to `load_transformer_parallel_cache` in `ml_scheduler.py:816-1201`).

### `preload_historical_db_for_eval` (`train_all.py:335-360`)

- **Definition:** `train_all.py:335-360`.
- **Behavior:** One SQLite query; returns `PreloadedHistoricalDB` wrapping rows in memory (`train_all.py:360`).
- **Disk cache:** None. It exists to avoid repeated DB queries during evaluation loops (`train_all.py:341-345` docstring).

### Scheduler manifest skip (`scheduler_run_manifest.json`)

Per-ticker **parallel** and **cascade** candidate dirs each hold their own manifest (`training_cache.py:11-12`, `ml_scheduler.py:1385-1386`, `2044-2050` region for `save_run_manifest`). These are **not** shared across architectures; they coordinate **skip/retrain** decisions independently (`ml_scheduler.py:1495-1548` eligibility logic — separate `parallel_skip` / `cascade_skip`).

### Summary table (training-time)

| Layer | Location | What it stores | Writers | Readers | Shared parallel/cascade? |
|-------|----------|------------------|---------|---------|---------------------------|
| SQLite training rows | `DB_PATH` / normalized tables | Snapshots, labels | ingest pipelines | both `load_data` / `build_lstm_dataset` / etc. | Yes — raw canonical input |
| `data_fp`, `code_fp`, `fk` | computed in `run_once` | fingerprints / keys | `run_once` (`ml_scheduler.py:1369-1378`) | passed to both `_train_parallel` and `_train_cascade` (`ml_scheduler.py:1595`, `1640`) | Yes — same keys both arches |
| LSTM tensor cache | `models/cache/features/{fk}/` | `lstm_tensors.npz` + meta + identity | first trainer to save | either arch on cache hit | **Yes** |
| Parallel transformer tensor cache | same `fdir` | `transformer_parallel_tensors.npz` | parallel path (`ml_scheduler.py:648-663`) | parallel only | No for cascade training |
| Cascade transformer tensor cache | same `fdir` | `cascade_transformer_xgb_lstm.npz` etc. | cascade path (`ml_scheduler.py:1171-1174`) | cascade only | No for parallel training |
| Candidate manifests | `models/{parallel\|cascade}/<ticker>/scheduler_run_manifest.json` | skip lineage + eval summaries | `save_run_manifest` (`ml_scheduler.py:2044+`) | `load_run_manifest` per dir | No — one file per arch dir |
| `preload_historical_db_for_eval` | memory only | snapshot rows subset | eval / meta loops | `_predict_*` consumers | N/A |

---

## Q4 — Documented intent

### `ml_scheduler.py` module docstring (`ml_scheduler.py:1-16`)

States an ordered nightly flow **A** train parallel, **B** train cascade, **C** compare, and documents cache dirs including `models/cache/features/{feature_cache_key}/: LSTM npz + parallel Transformer npz` (`ml_scheduler.py:14-16`).

**Discrepancy:** Step **D** says "Promote winner to models/active" (`ml_scheduler.py:8-9`), while later governance work uses `arch_competition` manual promotion; treat the docstring as **historical / high-level** rather than exact runtime promotion path.

### `train_compare.py` header (`train_compare.py:3-8`)

Explicitly: training uses `_train_parallel` / `_train_cascade` "identical to nightly `run_once`" and evaluation uses the same eval helpers — intent is **comparable entry points**, not cascade consuming parallel model files.

### `docs/architecture_parallel_vs_cascade_competition_spec.md`

- **Parallel independence** at inference: base models do not depend on one another's outputs (`docs/architecture_parallel_vs_cascade_competition_spec.md:11-16`).
- **Cascade coupling:** downstream may consume upstream compact outputs (`docs/architecture_parallel_vs_cascade_competition_spec.md:18-22`, `57-63`).
- **Shared canonical cached tensors** are **allowed** for fair comparison (`docs/architecture_parallel_vs_cascade_competition_spec.md:24-29`, `44-48`, `65-68`).

**Code vs spec:** The spec's "Shared canonical cached tensors" aligns with **LSTM NPZ reuse** via `models/cache/features/...`. The spec does **not** say cascade should read parallel **trained weights** from `models/parallel/`.

### `lstm_model.py` header (`lstm_model.py:1-5`)

Comment: supports parallel (raw confluence) and cascade (confluence + XGB preds) — describes **intra-cascade** staged inputs, not reading parallel directory.

### `git log` (limited signal in this clone)

Commands:

- `git log --all --oneline --grep="cascade" | Select-Object -First 30`
- same for `"cache"`, `"parallel"`

Output only showed recent governance-related commits (e.g. `63d9e0b`, `2524770`, `430e020`), not historical training-design commits. **No reliable commit-message evidence** for original cascade/parallel dependency design beyond current file contents.

---

## Q5 — Pattern classification

- **Pattern A (cascade depends on parallel model artifacts in the same cycle):** **Not supported.** `train_cascade_candidate` does not read `models/parallel/<ticker>/` weights or manifests (`Q1`).
- **Pattern B (fully independent aside from raw DB):** **Not fully accurate** because of **shared on-disk LSTM tensor cache** keyed only by `(ticker, data_fp, feature_cache_key)` (`training_cache.py:349-363`, `366-451`; `ml_scheduler.py:1378`, `1595`, `1640`).
- **Pattern C (hybrid):** **Best fit.** Parallel and cascade are **independent for trained model binaries** under their candidate dirs, but **deliberately share** (a) raw DB inputs, (b) fingerprint keys, and (c) **LSTM feature tensor cache files** under `models/cache/features/{fk}/`. Cascade also uses cascade-only transformer tensor artifacts in the same cache root (`training_cache.py:37-39`).

---

## Implications for G2

**Pattern C confirmed** with **no** parallel **model-dir** dependency.

- **`governance/G2_PLAN.md` cascade meta block** remains structurally valid: set `mp.MODEL_DIR` to the **cascade** candidate leaf and use `_strict_off_for_candidate_inference` as parallel meta does (`ml_scheduler.py:725-727`).
- **One addition (architectural invariant) for G2 prompts:** explicitly state that cascade meta assembly **must not** read paths under `models/parallel/<ticker>/`; any reuse is limited to **shared caches** (`models/cache/features/...`) and the **DB**, both already keyed for lineage elsewhere.
- **No revision** to G2 meta logic is required **solely** because of parallel **weight** reuse — there is none.

---

## Open questions for runtime tracing

1. **`_model_dir_for_ticker` when `MODEL_DIR` is a leaf directory:** Confirm at runtime that with `mp.MODEL_DIR = models/cascade/<T>/` (absolute) and strict-off, `_predict_*` resolve to that leaf (expected via `ml_predict.py:302-307`). If not, capture `MODEL_DIR`, `_INFER_ARCHITECTURE.get()`, and returned `base` once per stage.
2. **Need for `_cascade_challenger_inference_scope` during cascade meta:** Static reading suggests flat fallback may suffice (`ml_predict.py:302-307`); if any `_load_lstm` / `_load_transformer` branch assumes cascade context differently, a one-ticker train with logging at `ml_predict.py:620` and `820` would disambiguate.
3. **LSTM cache parity:** If parallel wrote `lstm_tensors.npz` first, does cascade `train_lstm` always consume tensors consistent with cascade `xgb_probs` feeding? Static reading shows cascade still uses cached `ds` then may pass `xgb_probs` separately (`ml_scheduler.py:1026-1037`). **Runtime-only** confirmation: compare `ds.n_samples` vs `len(xgb_probs_list)` warning frequency (`ml_scheduler.py:1010-1013`).
