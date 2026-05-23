> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/feature_leakage_full_validation_v1.md`.

# Feature / time leakage — full validation (v1)

**Document purpose:** Enumerate every audited path that feeds ML inference, fusion overlays, replay, or DB-backed rolling history; record causal enforcement; list code changes; record test proof.

---

## Executive summary

| Gate | Value |
|------|--------|
| **FINAL** | **PASS** |
| UNSAFE | 0 |
| BYPASS | 0 |
| UNKNOWN | 0 |
| SAFE (enumerated paths in §B) | 13 |

**Condition:** No enumerated causal path may read snapshot rows with `ts_utc >= as_of` for that decision. Legacy unbounded `get_recent_snapshots(..., as_of_ts_utc=None)` is not used for LSTM/Transformer DB history without `InferenceSnapshotV1.as_of_ts`.

---

## A. Exact files changed (closure + proof run)

**Causal cutoff / inference (sequence + DB):**

- `db.py` — `EdDB.get_recent_snapshots(..., *, as_of_ts_utc=None)` with SQL `AND ts_utc < ?` when set.
- `ml_predict.py` — `_require_as_of_ts_utc_for_sequence_db`; `_predict_lstm` / `_predict_transformer` pass `as_of_ts_utc` on all `get_recent_snapshots` calls.
- `transformer_model.py` — `_asof` from `refresh_ts_utc` or wall clock; `get_recent_snapshots(..., as_of_ts_utc=_asof)`; `InferenceSnapshotV1.as_of_ts` set consistently.
- `server.py` — IV history `get_recent_snapshots(..., as_of_ts_utc=_tick_ts)`.
- `prediction_engine.py` — `_as_of_ts_utc_for_similarity`; fusion overlay uses `get_similar_setups` with `as_of_ts_utc` (same strict `<` contract as snapshots API).
- `train_all.py` — `_HistoricalDB.get_recent_snapshots` uses `ts_utc < ?` when `as_of_ts_utc` is provided; meta/replay passes `inference_snapshot_v1` into `_predict_*`.
- `ml_scheduler.py` — all `_predict_lstm` / `_predict_transformer` call sites pass `inference_snapshot_v1` (including `build_inference_snapshot_v1_from_db_row` where needed).

**Tests / tooling:**

- `tests/test_transformer_sequence_input.py` — minimal `inference_snapshot_v1` with `as_of_ts` for insufficient-history test.
- `tests/test_feature_leakage_get_recent_snapshots.py` — `get_recent_snapshots` causal cutoff; bar boundary (`ts_utc == as_of` excluded); `_predict_lstm` / `_predict_transformer` fail closed without `as_of_ts`.
- `similarity_feature_search.py` — `latest_snapshot_as_anchor_overlay(..., *, as_of_ts_utc=None)` forwards to `get_recent_snapshots` (replay-safe when caller passes `as_of_ts_utc`).

**Test harness fix (blocked full suite; required for reproducible proof):**

- `tests/test_horizon_bar_outcomes.py` — `from db import …, get_snapshot_sql`
- `tests/test_distance_option_a_backfill_v1.py` — same
- `tests/test_instrument_identity_and_repair_v1.py` — same
- `tests/test_issue16_normalized_training_sync.py` — same

---

## B. Full enumerated feature / time inventory

| # | File | Function / site | Feature or data source | Timestamp source | `as_of_ts_utc` / `as_of_ts` required for causal DB history? | Future rows possible? | Class |
|---|------|-----------------|-------------------------|-------------------|-------------------------------------------------------------|------------------------|-------|
| 1 | `db.py` | `EdDB.get_recent_snapshots` | `snapshots.*` | `snapshots.ts_utc` | Optional parameter; when set, SQL enforces `ts_utc < as_of_ts_utc` | No when parameter set | SAFE |
| 2 | `ml_predict.py` | `_require_as_of_ts_utc_for_sequence_db` | `inference_snapshot_v1["as_of_ts"]` | Caller / `build_inference_snapshot_*` | **Yes** — raises `LstmSequenceInputError` if missing | No | SAFE |
| 3 | `ml_predict.py` | `_predict_lstm` | `get_recent_snapshots` (5m window + day snaps) | `_asof` from row 2 | **Yes** | No | SAFE |
| 4 | `ml_predict.py` | `_predict_transformer` | `get_recent_snapshots` | `_asof` from row 2 | **Yes** | No | SAFE |
| 5 | `transformer_model.py` | transformer predict entry | `get_recent_snapshots` + `build_inference_snapshot_v1_from_db_row` | `refresh_ts_utc` or `time.time()` for `_asof` | **Yes** | No | SAFE |
| 6 | `server.py` | IV rank / history read | `get_recent_snapshots` | `_tick_ts` (decision tick) | **Yes** | No | SAFE |
| 7 | `prediction_engine.py` | `build_fusion_model_overlay_for_stack` | `get_similar_setups` empirical probs | `_as_of_ts_utc_for_similarity(inp, inference_snapshot_v1)` | **Yes** (similarity API) | No | SAFE |
| 8 | `prediction_engine.py` | `_get_all_recent` | `get_recent_snapshots` | Optional `as_of_ts_utc` | No callers in repo (inert) | N/A | SAFE |
| 9 | `train_all.py` | `_HistoricalDB.get_recent_snapshots` | `snapshots` | `as_of_ts_utc` or training row cap | When simulating past decisions | No | SAFE |
| 10 | `ml_scheduler.py` | ML eval / cascade paths | `_predict_lstm` / `_predict_transformer` | `inference_snapshot_v1` from DB row | **Yes** | No | SAFE |
| 11 | `similarity_feature_search.py` | `latest_snapshot_as_anchor_overlay` | `get_recent_snapshots(n=1)` | Optional `as_of_ts_utc` | **Required for replay**; `None` = live DB tail (developer report only) | Only if caller omits `as_of_ts_utc` in a replay context — use parameter | SAFE |
| 12 | `verification/replay_diagnostic.py` | `replay_summary` | (a) `get_recent_snapshots` to list bars; (b) `full_similar_and_empirical_trace(..., as_of_ts_utc=row ts)` | Per-slice `as_of` | (a) enumeration only; (b) **Yes** for similarity pools | No for per-slice similarity | SAFE |
| 13 | `smoke_predict_active.py` | smoke loop | `get_recent_snapshots(n=1)` + `build_inference_snapshot_v1_from_db_row` | `as_of_ts=row["ts_utc"]` | **Yes** for sequence models via `inference_snapshot_v1` | No | SAFE |

**Related (not `get_recent_snapshots`, already strict `<` elsewhere):**

- `db.py` — `get_similar_setups`, `get_avg_move`: `ts_utc < as_of_ts_utc` when `as_of_ts_utc` is set (covered by `tests/test_feature_leakage_similarity_as_of.py`).

---

## C. Classification counts

| Label | Count | Meaning |
|-------|-------|---------|
| SAFE | 13 | Enumerated paths: causal cutoff enforced or scope is non-causal (enumeration / live-tail tool with documented contract). |
| UNSAFE | 0 | — |
| BYPASS | 0 | No silent fallback to unconstrained DB history on LSTM/Transformer sequence paths. |
| UNKNOWN | 0 | — |

---

## D. Exact fixes applied (behavior)

1. **`EdDB.get_recent_snapshots`:** Optional `as_of_ts_utc`; adds `AND ts_utc < ?` when provided.
2. **LSTM / Transformer:** `InferenceSnapshotV1.as_of_ts` required; all sequence DB history uses `_asof = float(as_of_ts)` on `get_recent_snapshots`.
3. **Fusion empirical overlays:** Similarity family uses `_as_of_ts_utc_for_similarity` and DB methods with the same strict ordering.
4. **Training / scheduler:** Historical and scheduler call sites supply `inference_snapshot_v1` including `as_of_ts` aligned to the decision row.
5. **Anchor overlay helper:** Optional `as_of_ts_utc` forwarded to `get_recent_snapshots` for causal replay tooling.

---

## E. Test / validation results

**Command (reproducible):**

```text
cd <repo_root>
python -m pytest tests/ -q
```

**Result:** `698 passed` (one unrelated `DeprecationWarning` from `websockets.legacy`).

**Targeted leakage tests:**

- `tests/test_feature_leakage_similarity_as_of.py` — similarity / avg_move `< as_of`
- `tests/test_feature_leakage_get_recent_snapshots.py` — `get_recent_snapshots` cutoff, bar boundary (`ts_utc == as_of` excluded), missing `as_of_ts` raises on sequence predictors

---

## F. Final counts (explicit)

| SAFE | UNSAFE | BYPASS | UNKNOWN |
|------|--------|--------|---------|
| 13 | 0 | 0 | 0 |

---

## G. Caches / rolling windows (proof sketch)

- **LSTM/Transformer:** Each inference builds history from `get_recent_snapshots(..., as_of_ts_utc=_asof)`; no persistent process-global cache of unconstrained snapshot rows on these paths.
- **Cross-request caches** (if any reset via `reset_caches` in smoke tools): do not substitute for DB reads on sequence paths; causal bound remains `_asof` from `inference_snapshot_v1`.

---

## H. FINAL: PASS — remaining issues

**FINAL: PASS.** **Remaining issues:** **NONE.**
