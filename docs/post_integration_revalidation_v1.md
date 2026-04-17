# Post-Integration Revalidation v1 (signal_layer_v1)

**Scope:** Revalidate the **updated** production stack after `signal_layer_v1` integration. No edge discovery or calibration tuning.

**Date:** 2026-04-09  
**Evidence DB:** `data/calibration_accumulation_validation.db` (fresh run this session)  
**Evidence report:** `data/calibration_accumulation_validation_report.json`  
**Phase1 audit artifact:** `models/calibration_runs/phase1_audit_1775942000.json`

---

## 1. Executive result

The integrated path was exercised end-to-end via a **fresh** deterministic accumulation (`python -m calibration.run_production_accumulation_validation`), then validated with **outcome join**, **anchor audit**, and **audit_phase1** on that same database. Automated gates **passed**. Leakage was reviewed in code at the bar-load boundary and fusion consumption path, with **`tests/test_signal_layer_v1.py` passing (4/4)**.

**FINAL RESULT: PASS**

---

## 2. Exact files / functions audited

| Area | Files | Functions / entry points |
|------|--------|---------------------------|
| Signal layer bar contract | `features/signal_layer_v1.py` | `load_bars_before_decision`, `compute_signal_layer_v1`, `compute_signal_layer_v1_for_calibration`, `signal_layer_v1_to_direction_probs` |
| Production stack order | `signals.py` | `compute_signals` → `_compute_signals_impl`, `build_inference_snapshot_v1_from_signal_input`, `compute_signal_layer_v1_for_calibration`, `bayesian_fusion.fuse`, `canonical_forecast_from_fusion`, `build_multi_horizon_bundle`, `_maybe_append_calibration_log` |
| Fusion blend | `bayesian_fusion.py` | `fuse`, `_fuse_impl` (signal_layer_v1 directional blend block) |
| Multi-horizon | `multi_horizon_decision.py` | `build_multi_horizon_bundle` and canonical blend (referenced from `signals.py`) |
| Calibration write | `calibration/writer.py` | `append_calibration_decision_log` (raw_bundle `signal_layer_v1`) |
| Accumulation harness | `calibration/run_production_accumulation_validation.py` | full pipeline + validators |
| Outcome join | `calibration/validate_outcome_join.py` | `analyze` |
| Anchors | `calibration/anchor_audit.py` | `run_anchor_audit` |
| Phase1 + stats gates | `calibration/audit_phase1.py`, `calibration/statistical_integrity.py` | `verify_audit_phase1_no_numeric_leak`, `verify_anchor_audit_no_numeric_leak` |
| Unit tests | `tests/test_signal_layer_v1.py` | leakage bounds + synthetic sanity |

---

## 3. Updated production-path inventory

| Stage | File | Function | Changed / affected by integration |
|-------|------|----------|-----------------------------------|
| Signal input | Caller / `build_market_state` (upstream) | `SignalInput` | Unchanged contract; still feeds snapshot |
| Inference snapshot | `features/inference_snapshot.py` | `build_inference_snapshot_v1_from_signal_input` | **Downstream:** snapshot extended with optional `signal_layer_v1` after layer compute |
| **signal_layer_v1 injection** | `signals.py` | `_compute_signals_impl` | **Changed:** after snapshot, `compute_signal_layer_v1_for_calibration(db, ticker, as_of_ts, inp)` |
| Fusion | `bayesian_fusion.py` | `fuse` / `_fuse_impl` | **Changed:** optional blend from `signal_layer_v1` → directional probs |
| Canonical forecast | `signals.py` | `canonical_forecast_from_fusion` | **Downstream:** receives fusion that may include layer blend |
| Multi-horizon | `multi_horizon_decision.py` | `build_multi_horizon_bundle` | **Downstream:** consumes canonical (already fusion-informed) |
| Final call / logging | `signals.py` | `compute_call`, `_log_decision_bundle`, MH promotion block | **Downstream:** MH promotion when fusion tradeable + `wait` call |
| **calibration_decision_log** | `calibration/writer.py` | `append_calibration_decision_log` | **Changed:** `raw_bundle_json.signal_layer_v1` populated |
| Outcome join | `calibration/backfill_outcomes.py` | `backfill`, `resolve_snapshot_for_backfill` | Unchanged join contract (exact ts) |
| Trusted / legacy | `calibration/trust.py` + writer | trust columns | Unchanged predicates; harness asserts `legacy_rows == 0` |

---

## 4. Leakage audit results

**Reviewed mechanisms**

1. **Bars:** `load_bars_before_decision` selects `price_bars_1m` with `bar_end_ts_utc <= decision_ts_utc` (`features/signal_layer_v1.py`). Completed bars only.
2. **Decision clock:** Layer uses `inference_snapshot_v1["as_of_ts"]` passed as `decision_ts_utc` (`signals.py` → `compute_signal_layer_v1_for_calibration`).
3. **Fusion:** `_fuse_impl` blends model evidence with `signal_layer_v1_to_direction_probs(signal_layer_v1)` only; **no** outcome columns, **no** post-decision fields in the fusion input path reviewed.
4. **Logging:** `raw_bundle` stores the same dict passed at decision time; outcomes are joined later on `calibration_decision_log` / `snapshots`, not fed back into `compute_signals`.

**Automated tests:** `pytest tests/test_signal_layer_v1.py` — **4 passed** (leakage bounds + synthetic checks).

**FINAL: Leakage PASS** — No code path was found that pulls future bars into the layer query; fusion uses only the precomputed layer dict and standard model outputs.

---

## 5. Fresh accumulation validation

| Item | Evidence |
|------|----------|
| **Run method** | `python -m calibration.run_production_accumulation_validation` |
| **Output DB** | `data/calibration_accumulation_validation.db` |
| **Report** | `data/calibration_accumulation_validation_report.json` |
| **Rows written** | `calibration_decision_log_total` = **120** (trusted **120**, legacy **0**) |
| **Duplicates** | `duplicate_key_groups` = **0** |
| **Timestamps** | Deterministic plan: `base_ts_utc` 1712200000, `ts_step_sec` 100, 120 events |
| **Schema / bundle** | SQL spot check: **120/120** rows have non-empty `signal_layer_v1` object in `raw_bundle_json` |
| **Trusted** | `total_rows_eq_trusted_no_legacy` gate **true**; legacy quarantine **0** |
| **Anomalies** | `warnings` array **empty**; `binary_pass` **true** |

---

## 6. Outcome join / trust / anchor validation

| Check | Result |
|-------|--------|
| `validate_outcome_join` | `binary_pass` **true**; ambiguous duplicate snapshots **0**; verification **120** pass / **0** fail; all manual samples `join_method: "exact"` |
| Anchor (`anchor_audit`) | `binary_pass` **true**; trusted without anchor **0** / **120**; `statistical_integrity.binary_pass` **true** |
| Harness gates | `unsafe_non_exact_join_rows_trusted` **0**; `anchor_all_trusted_anchored` **true** |
| Legacy | `legacy_rows` **0**; no silent legacy contamination in this trusted-only empirical slice |

---

## 7. Statistical integrity validation

| Source | Result |
|--------|--------|
| `calibration/anchor_audit.py` | `verify_anchor_audit_no_numeric_leak` — **pass** (`statistical_integrity.binary_pass: true`) |
| `calibration/audit_phase1.py` | `verify_audit_phase1_no_numeric_leak` — **pass** (`statistical_integrity.binary_pass: true`) |
| Gap stats | Per-ticker gap `n=29` → distribution medians **withheld** (`insufficient_sample`) — fail-closed, not fake precision |
| Reference floor | `MIN_SAMPLES_STATISTICAL` (30) via `calibration.statistical_integrity` |

---

## 8. Dataset readiness (Phase 5 / Phase 6)

**SAFE** for proceeding **on this validated artifact**, with explicit scope:

- **Phase 5 (discrimination audit):** Population **120** trusted rows exceeds the **30** statistical floor; join and anchor proofs apply to this DB. Use this file or a production DB that passes the same validators.
- **Phase 6 (edge discovery retest):** Same — structure is proven for the integrated path; edge discovery remains a separate empirical exercise on sufficient N.

**Caveat:** Generalization to a larger production database requires re-running the same validators on that DB (this report proves the **code path + harness dataset**, not an unbounded production history unless revalidated).

---

## 9. Remaining issues

**NONE** (PASS criteria met for this revalidation scope).

---

## 10. FINAL RESULT: PASS

**Binary:** The updated production accumulation path, with `signal_layer_v1` on fusion / canonical / multi-horizon / calibration logging, is **structurally valid** per executable validators and documented code review **for the evidence run above**.
