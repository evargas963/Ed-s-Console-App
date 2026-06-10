> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_feature_leakage_validation_v1.md`.

# Calibration / decision feature leakage validation (v1)

This document traces the **live** feature path for `compute_signals` → decision/calibration logging, proves **no lookahead** in the **empirical similarity** and **inference snapshot** cutoffs, and records **residual** risks outside that fix.

Checklist: **A** files · **B** path · **C** safe · **D** suspect · **E** fixes · **F** risks · **G** PASS/FAIL.

---

## B. Full feature path audited (live stack)

| Stage | Source | Timestamp semantics |
|-------|--------|----------------------|
| **Market state** | `build_market_state` → `SignalInput` | `refresh_ts_utc` set at refresh boundary when provided (`market_state.py`). |
| **InferenceSnapshotV1** | `build_inference_snapshot_v1_from_signal_input` | **`as_of_ts`**: explicit `as_of_ts` → **`refresh_ts_utc`** → **`time.time()`** (`features/inference_snapshot.py`). |
| **MVP features** | `build_live_mvp_feature_row` from L1-equivalent dict | Only fields derived from **current** `SignalInput` / L1 payload for this tick — no DB outcome reads. |
| **Vol / regime / rules** | `classify_volatility_regime`, `classify_regime`, `compute_rules` | **`mvp_features`** from InferenceSnapshotV1 only for canonical fields (`features/regime_mvp_context.py` contract). |
| **Fusion overlay (empirical preds)** | `build_fusion_model_overlay_for_stack` | `get_similar_setups(..., as_of_ts_utc=…)` — **only historical snapshots strictly before decision instant**. |
| **ML stack** | `run_unified_stack_ml_once` / `ml_predict` | Uses overlay + `inference_snapshot_v1`; sequence loaders use **`get_recent_snapshots`** (see **F**). |
| **Monte Carlo** | `resolve_monte_carlo_stack_inputs(inp, inference_snapshot_v1)` | Canonical spot/levels from MVP row. |
| **Bayesian fusion** | `bayesian_fuse` | Model outputs + rules — no DB similarity. |
| **`compute_prediction`** | `get_similar_setups` + `get_avg_move` | **`as_of_ts_utc`** from `_as_of_ts_utc_for_similarity` (`prediction_engine.py`). |
| **Call / MHAP** | `compute_call`, `build_multi_horizon_bundle` | Prior stack outputs only. |
| **Calibration log** | `append_calibration_decision` | Serializes stack outputs; **no** outcome columns from future bars (outcomes attached later via `backfill_outcomes`). |

**Authoritative refresh instant for DB history:**  
`InferenceSnapshotV1["as_of_ts"]` when present, else `SignalInput.refresh_ts_utc`, else legacy **`None`** (no SQL cutoff — tests / old callers).

---

## C. Proven safe features (post-fix)

| Area | Why safe |
|------|----------|
| **Canonical MVP row** | Built from **this tick’s** L1 / `SignalInput` only; validated by `validate_feature_contract_row`. |
| **Similar-setup empirical histograms** | `snapshots.ts_utc < as_of_ts_utc` in **`get_similar_setups`** (existing SQL); production now passes **`as_of_ts_utc`** from decision time (`db.py`, `prediction_engine.py`). |
| **avg_move (What the Data Says)** | **`get_avg_move`** now supports the same **`as_of_ts_utc`** cutoff so averages cannot include post-decision rows. |
| **Outcome labels on historical similar rows** | Labels attach to **past** snapshot rows; using them at decision time **T** only for rows with **`ts_utc < T`** is the correct empirical construction (not future information at **T**). |

---

## D. Suspect / unsafe features (before fix)

| Issue | Risk |
|-------|------|
| **`get_similar_setups` / `get_avg_move` without `as_of_ts_utc`** | **Lookahead** in **replay** or any evaluation at time **T**: pools could include snapshots with **`ts_utc ≥ T`**, leaking “future” cohort rows into empirical probabilities. |
| **`InferenceSnapshotV1.as_of_ts` = `time.time()` when `refresh_ts_utc` unset** | Misalignment between **bar** time and **wall clock** in edge tooling; mitigated by preferring **`refresh_ts_utc`** when set. |

---

## E. Exact fixes applied

| File | Change |
|------|--------|
| `features/inference_snapshot.py` | **`build_inference_snapshot_v1_from_signal_input`**: `as_of_ts` order = argument → **`refresh_ts_utc`** → **`time.time()`**. |
| `prediction_engine.py` | **`_as_of_ts_utc_for_similarity`**: resolves cutoff from **`inference_snapshot_v1.as_of_ts`** then **`refresh_ts_utc`**. **`build_fusion_model_overlay_for_stack`** and **`compute_prediction`** pass **`as_of_ts_utc`** into **`get_similar_setups`** and **`get_avg_move`**. |
| `db.py` | **`get_avg_move(..., *, as_of_ts_utc=None)`**: adds **`AND ts_utc < ?`** when set (matches **`get_similar_setups`**). |
| `tests/test_feature_leakage_similarity_as_of.py` | Regression tests for cutoff + helper behavior. |

---

## F. Remaining risks

1. **`ml_predict.get_recent_snapshots`** (LSTM / sequence paths) does **not** take **`as_of_ts_utc`**. **Live** operation is OK (only past rows exist relative to “now”). **Historical replay** at time **T** could still load rows with **`ts_utc > T`** if the DB contains them. Mitigation: replay harness should use a DB snapshot cut at **T** or extend **`get_recent_snapshots`** with an optional cutoff (not required for **live** calibration logging).
2. **Outcome / label columns** on the **current** snapshot row in the UI are filled **later** by **`fill_outcomes`** — they are **not** inputs to **`compute_signals`** for that same row’s decision (calibration attaches outcomes in **`calibration_decision_log`** via **`backfill_outcomes`**, not from live feature path).
3. **Cross-asset fields** on `SignalInput` (e.g. QQQ/SPY changes) inherit **whatever timestamping the data vendor** uses in `build_market_state`; not re-derived here.

---

## A. Exact files changed

- `features/inference_snapshot.py`
- `prediction_engine.py`
- `db.py`
- `tests/test_feature_leakage_similarity_as_of.py`
- `docs/calibration_feature_leakage_validation_v1.md`

---

## G. PASS / FAIL (binary)

**PASS** — Empirical similarity and **`get_avg_move`** now enforce **`ts_utc < as_of_ts_utc`** using the same decision instant as **`InferenceSnapshotV1.as_of_ts`** / **`refresh_ts_utc`**, closing replay lookahead for those paths. MVP features remain single-tick; residual replay risk is documented for **`get_recent_snapshots`** in **§F**.
