# Schwab Remediation S017 Inference Snapshot Time Contract

**Status:** IMPLEMENTED  
**Slice:** S017 `TIME_NOW_FALLBACK` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): pricehistory.candles.*.datetime; streaming.content.*.QUOTE_TIME_MILLIS; streaming.content.*.TRADE_TIME_MILLIS; snapshots.ts_utc is internal canonical decision timestamp derived once per refresh
Derived-field disposition: SPLIT_DECISION_TIME_FROM_WALL_CLOCK_AND_GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

`InferenceSnapshotV1.as_of_ts` is an evaluation/decision timestamp. It must come from the caller's explicit `as_of_ts` or `SignalInput.refresh_ts_utc`, which is aligned to the refresh/snapshot decision instant. It must not silently fall back to `time.time()`.

If no authoritative decision timestamp is available, `as_of_ts` remains `None`. Downstream consumers that require time-bounded data must handle `None` explicitly instead of receiving a fabricated current wall-clock value.

L1 payloads may carry `_server_build_ts` for other diagnostics, but **`InferenceSnapshotV1.as_of_ts` must not be derived from it** — that field is ingestion wall clock, not Schwab market-data time and not an asserted decision instant.

## Implementation lineage

The initial S017 bundle commit set included governance and server/live-plane work but did not include `features/inference_snapshot.py`. Slice closure requires the disposition rows above to match **committed** code: `build_inference_snapshot_v1_from_signal_input` is amended in the same commit series that updates this section (no `time.time()` fallback; invalid/missing timestamps stay `None`).

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `features.inference_snapshot.build_inference_snapshot_v1_from_signal_input` | fixed-in-this-slice | `features/inference_snapshot.py::build_inference_snapshot_v1_from_signal_input` | Uses explicit `as_of_ts` or `SignalInput.refresh_ts_utc`; no `time.time()` fallback. |
| `features.inference_snapshot.build_inference_snapshot_v1` | fixed-in-this-slice | `features/inference_snapshot.py::build_inference_snapshot_v1` | `as_of_ts` from caller argument or optional `l1_payload["as_of_ts"]` only; **no** `l1_payload["_server_build_ts"]` wall-clock fill (D-S017-03). |
| `signals.compute_signals` | covered-by-contract | `signals.py::compute_signals` | Builds the shared inference snapshot once; existing calibration tests assert `decision_ts_utc == refresh_ts_utc`. |
| `signals.compute_signals_parallel` | covered-by-contract | `signals.py::compute_signals_parallel` | Same shared builder path. |
| `prediction_engine._as_of_ts_utc_for_similarity` | covered-by-contract | `prediction_engine.py::_as_of_ts_utc_for_similarity` | Treats missing inference/signal time as `None`, avoiding future-row cutoff fabrication. |
| `ml_predict._require_as_of_ts_utc_for_sequence_db` | fixed-in-this-slice | `ml_predict.py:137-151` | Fail-closed: missing `as_of_ts` raises `LstmSequenceInputError` before any `float(None)`. |
| `features.shared_sequence_context.build_shared_sequence_context` | canonical | `features/shared_sequence_context.py:77-81`, `119-127` | Calls `_require_as_of_ts_utc_for_sequence_db` first; on failure returns `(None, err)` and **never** constructs `SharedSequenceContext`. On success `_asof` is a finite `float`, so `SharedSequenceContext.as_of_ts=float(_asof)` is safe. A `None` upstream snapshot therefore cannot reach the dataclass without changing this contract. |
| `features.xgb_model_input.inference_snapshot_v1_to_engineering_snapshot` | canonical | `features/xgb_model_input.py:102-115` | After `validate_inference_snapshot_v1_for_xgb`, reads `as_of_ts`; if `None`, omits `ts_utc` / ET clock fields (no silent wall-clock fill). |
| `arch_competition.stack_bundle_eval_v1` (eval replay) | not-applicable | `arch_competition/stack_bundle_eval_v1.py:406-422` | Offline path: skips rows with missing `ts_utc`; only then `as_of_ts=float(ts_utc)` and `build_inference_snapshot_v1_from_db_row(...)`. Not on the live `as_of_ts is None` inference path. |

No `pending-follow-up` rows remain for this inference snapshot S017 sub-slice.

## Verification

```text
python -m pytest tests/test_xgb_inference_snapshot_v1_input.py tests/test_feature_leakage_similarity_as_of.py tests/test_calibration_logging_production_path.py::test_decision_ts_utc_matches_refresh_ts_utc
```

Expected: inference snapshots preserve missing `as_of_ts` as `None`, explicit `refresh_ts_utc` remains authoritative, and no wall-clock fallback remains in `features/inference_snapshot.py`.
