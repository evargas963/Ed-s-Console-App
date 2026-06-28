> **Classification:** Inventory / Read-only audit artifact | **Scope:** D17 Schwab V4 register slice state @ pinned register SHA
>
> **Status:** Inventory only — **does not** close D17, Schwab V4 Register Closure, card fidelity, or real-money readiness.
>
> **Aligned SHA:** `62797052d2d460348c363ca0074ab9f67b5f56d2`
> **Generated:** 2026-06-27 (read-only analysis; no register/slice edits)
> **Amended:** 2026-06-27 — post-inventory `D17_MECHANICAL_NO_OPERATOR_JUDGMENT_SLICE_1` merge-slices proof (docs correction only)
> **Regen command:** Re-run read-only analysis at tip (same SHA) with:
> `python -m tools.schwab_coverage_v4_metrics --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv --operator-register governance/OPERATOR_DECISION_REGISTER.md`
> plus register/slice CSV analysis scripts — **do not** run scanner regen or `--merge-slices` for inventory regen.
>
> **Authority:** Program law remains `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (Deliverable 17). This document is a **planning inventory** only.
>
> **Consumer:** Operator + future D17 mechanical/operator-decision lanes.

# D17 Register Slice Inventory Summary

## Executive summary

| Fact | Value |
|------|------:|
| Pinned register rows | 83,587 |
| Local `unreviewed_count` | 52,237 |
| CI fresh-scan reference `unreviewed_count` | 53,215 (@ `ed555f7` Schwab V4 Register Closure run 28301615190) |
| `bare_governed_exception_count` | 0 |
| `closure_admissible` | **false** (blocked by UNREVIEWED only) |
| Register pin SHA256 | `2017b18f24870bdf8fa1c9153c4aca4b3e137ebd1167a9b260ed766fd455303e` |
| Pin alignment (register = meta = scoreboard) | **PASS** |
| O-XX validation | **PASS** |
| Slice files | 85 |
| Slice rows (total) | 66,692 |
| Slice UNREVIEWED rows | **0** |
| **Path/line overlap** (UNREVIEWED register + slice disposition at same `(path, line)`) | **6,286** |
| **Tool merge-eligible** (`register_id` / `site_key` resolver match on UNREVIEWED rows) | **0** |
| **No-slice gap** (UNREVIEWED + no `(path, line)` in slices; path/line accounting only) | **45,951** |

**Primary D17 blocker:** `unreviewed_count > 0`. No bare GOVERNED_EXCEPTION, no pin/scoreboard/O-XX defects on pinned register. **No D17 metric movement has been achieved** (post-merge proof: still 52,237 UNREVIEWED).

**Key finding (original inventory):** 6,286 rows show path/line overlap between UNREVIEWED register rows and non-UNREVIEWED slice dispositions.

**Key finding (post-merge proof):** Those overlaps are **not** currently mergeable by `stream_revert_v4_register_and_sync_perf.py --merge-slices` because the resolver matches **`register_id` / `site_key` only** — not ranked `(path, line)` fallback. Reclassify as **`path_line_overlap_requires_identity_reconciliation`**. **Identity reconciliation audit required before any merge/repin lane.**

---

## 1. Register baseline

### 1.1 Metrics (local pinned register)

| Metric | Value |
|--------|------:|
| Total rows | 83,587 |
| UNREVIEWED | 52,237 |
| NOT_MARKET_DATA | 31,285 |
| REPLACED | 50 |
| KEEP_DERIVED | 13 |
| GOVERNED_EXCEPTION (O-49) | 2 |
| bare_governed_exception_count | 0 |
| governed_exception_with_oxx_count | 2 |
| closure_admissible | false |
| v4_a_violations | [] |

Command: `python -m tools.schwab_coverage_v4_metrics ...` → exit **1** (EXPECTED_OPEN_D17).

### 1.2 Pin alignment

| Artifact | `register_content_sha256` |
|----------|---------------------------|
| Local register CSV | `2017b18f24870bdf8fa1c9153c4aca4b3e137ebd1167a9b260ed766fd455303e` |
| `schwab_v4_register_build_meta.json` | `2017b18f24870bdf8fa1c9153c4aca4b3e137ebd1167a9b260ed766fd455303e` |
| `schwab_v4_scoreboard.json` → `register_build` | `2017b18f24870bdf8fa1c9153c4aca4b3e137ebd1167a9b260ed766fd455303e` |

**Status:** PASS — all three match.

### 1.3 Canonical truth model

| Layer | Path | Tracked? | Role |
|-------|------|----------|------|
| Pin + build recipe | `governance/artifacts/schwab_v4_register_build_meta.json` | yes | SHA256 authority; `partial_scan: false` |
| Reconciled register | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` | **gitignored** | Row-level dispositions; must match pin |
| Human overlays | `governance/register_slices/*.csv` | yes | Dispositions authored per slice; **merge tool** applies via `register_id` / `site_key` (see §3.7) |
| D17 summary | `governance/artifacts/schwab_v4_scoreboard.json` | yes | Metrics snapshot; regen after reconciliation |
| Scanner output | `tools/schwab_universal_coverage_scanner_v3/` | yes | Regenerates register rows (forbidden in inventory lane) |

**Never hand-edit:** gitignored register CSV, meta/scoreboard without full regen pipeline.

---

## 2. Slice inventory (85 files)

### 2.1 Totals

| Measure | Value |
|---------|------:|
| Slice file count | 85 |
| Total slice rows | 66,692 |
| Unique `(path, line)` keys | 38,193 |
| Keys appearing in >1 slice file | 16,281 |
| Keys with **conflicting** dispositions across slices | 363 |
| UNREVIEWED rows in any slice | **0** |
| Invalid/unknown dispositions | **0** |

### 2.2 Disposition totals (all slices)

- `NOT_MARKET_DATA` — 64,878
- `KEEP_DERIVED` — 602
- `PASS_THROUGH` — 485
- `GOVERNED_EXCEPTION (O-49)` — 426
- `REPLACED` — 223
- `GOVERNED_EXCEPTION (O-51)` — 40
- `NO_SCHWAB_EQUIVALENT` — 15
- `GOVERNED_EXCEPTION (O-50)` — 7
- `GOVERNED_EXCEPTION (O-47)` — 4
- `GOVERNED_EXCEPTION (O-53)` — 4
- `GOVERNED_EXCEPTION (O-41)` — 2
- `GOVERNED_EXCEPTION (O-42)` — 1
- `GOVERNED_EXCEPTION (O-43)` — 1
- `GOVERNED_EXCEPTION (O-44)` — 1
- `GOVERNED_EXCEPTION (O-45)` — 1
- `GOVERNED_EXCEPTION (O-46)` — 1
- `GOVERNED_EXCEPTION (O-48)` — 1

### 2.3 Naming / phase clusters (row counts)

- `module_slice` — 22,192
- `phase2_tests` — 14,772
- `scanner_baseline_variant` — 12,508
- `server_py` — 4,265
- `phase2_governance` — 4,170
- `phase2_docs` — 4,040
- `phase2_mega` — 3,038
- `phase3` — 621
- `static_index_html` — 579
- `phase4` — 424
- `phase` — 46
- `phase5b` — 34
- `phase5a` — 3

### 2.4 Top 20 largest slice files

- `phase2_tests_non_contract_not_market_data.csv` — 14,772
- `phase2_governance_md_not_market_data.csv` — 4,170
- `phase2_docs_md_not_market_data.csv` — 4,040
- `phase2_mega_inventories_not_market_data.csv` — 3,038
- `call_engine_py_1_1768.csv` — 2,370
- `liquidity_value_engine_py_1_1520.csv` — 1,969
- `ml_predict_py_1_1631.csv` — 1,902
- `order_flow_engine_py_1_1161.csv` — 1,607
- `prediction_engine_py_1_1249.csv` — 1,458
- `signals_py_1_1422.csv` — 1,422
- `call_engine_py_1_1768_scanner_baseline.csv` — 1,248
- `training_cache_py_1_1208.csv` — 1,208
- `market_state_py_1_1500.csv` — 1,127
- `training_cache_py_1_1118.csv` — 1,118
- `market_state_py_1_1500_scanner_baseline.csv` — 1,097
- `multi_horizon_decision_py_1_854.csv` — 1,053
- `bayesian_fusion_py_1_859.csv` — 1,037
- `server_py_4501_6000.csv` — 1,007
- `market_context_py_1_961.csv` — 961
- `order_flow_engine_py_1_1161_scanner_baseline.csv` — 958

### 2.5 Duplicate-key note

`16,281` keys appear in more than one slice file (often `*_scanner_baseline.csv` paired with module slices). Merge uses disposition **rank** in `tools/stream_revert_v4_register_and_sync_perf.py` (`UNREVIEWED`=0 lowest). **`363` keys** have conflicting dispositions across slices — mechanical merge must use rank resolution; operator should spot-check conflicts before merge-lag lane.

---

## 3. Path/line overlap inventory (formerly “merge-lag”)

**Definition (inventory accounting):** Pinned register row has `disposition=UNREVIEWED`, but a slice row exists for the same `(path, line)` with a non-UNREVIEWED disposition.

**Tool eligibility (corrected post-proof):** This count is **path/line overlap only**. It is **not** the count of rows the current `--merge-slices` resolver will update on UNREVIEWED register rows (**tool merge-eligible = 0**; see §3.7).

### 3.1 Totals

| Measure | Value |
|---------|------:|
| **Path/line overlap row count** | **6,286** |
| **Tool merge-eligible (UNREVIEWED + resolver match)** | **0** |
| Includes money-path files (AGENTS roster) | 2,755 |

### 3.2 By slice disposition (what merge would apply)

- `NOT_MARKET_DATA` — 5,941
- `KEEP_DERIVED` — 170
- `PASS_THROUGH` — 129
- `REPLACED` — 37
- `GOVERNED_EXCEPTION (O-49)` — 7
- `GOVERNED_EXCEPTION (O-47)` — 2

### 3.3 Top paths (merge-lag)

- `call_engine.py` — 772
- `server.py` — 752
- `liquidity_value_engine.py` — 615
- `market_context.py` — 574
- `training_cache.py` — 541
- `ml_predict.py` — 488
- `signals.py` — 448
- `prediction_engine.py` — 355
- `multi_horizon_decision.py` — 344
- `market_state.py` — 303
- `features/canonical_contract.py` — 223
- `order_flow_engine.py` — 113
- `features/mvp_source_coercion.py` — 98
- `features/lstm_sequence_input.py` — 97
- `features/shared_sequence_context.py` — 92
- `rules_engine.py` — 85
- `features/fusion_policy_contract.py` — 81
- `features/xgb_model_input.py` — 51
- `volatility_regime.py` — 44
- `bayesian_fusion.py` — 42

### 3.4 Top pattern_kind (merge-lag)

- `TEXT_LINE_MARKET_TOKEN` — 2,480
- `pattern_kind_miss` — 2,316
- `PYTHON_GETATTR_SETATTR` — 390
- `DICT_GET_MARKET_NULLABLE` — 260
- `DICT_LITERAL_MARKET_KEY` — 229
- `BINOP_MARKET_IDENT` — 119
- `SUBSCRIPT_MARKET_KEY` — 103
- `GETATTR_MARKET_LITERAL` — 102
- `ATTRIBUTE_MARKET` — 90
- `REGISTRY_DISPATCH` — 56
- `IFEXP_ZERO_DEFAULT` — 33
- `DICT_GET_MARKET_DEFAULT` — 25
- `DECORATOR_SITE` — 23
- `MAGIC_NUMERIC_DEFAULT` — 19
- `TIME_TIME` — 12
- `COERCE_OR_ZERO` — 9
- `CALL_NAMED_DERIVATION` — 8
- `TIME_MONOTONIC` — 8
- `DATETIME_NOW` — 4

### 3.5 Top contributing slice files (merge-lag rows)

- `call_engine_py_1_1768.csv` — 811
- `liquidity_value_engine_py_1_1520.csv` — 690
- `market_context_py_1_961.csv` — 574
- `training_cache_py_1_1208.csv` — 541
- `training_cache_py_1_1118.csv` — 497
- `ml_predict_py_1_1631.csv` — 491
- `signals_py_1_1422.csv` — 448
- `market_context_py_1_961_scanner_baseline.csv` — 424
- `canonical_contract_py_1_346_scanner_baseline.csv` — 421
- `multi_horizon_decision_py_1_854.csv` — 372
- `prediction_engine_py_1_1249.csv` — 367
- `server_py_3001_4500.csv` — 365
- `server_py_4501_6000.csv` — 359
- `market_state_py_1_1500.csv` — 305
- `server_py_4501_6000_scanner_baseline.csv` — 288
- `market_state_py_1_1500_scanner_baseline.csv` — 287
- `server_py_6001_7323.csv` — 265
- `signals_py_1_1422_scanner_baseline.csv` — 261
- `server_py_3001_4500_scanner_baseline.csv` — 254
- `server_py_6001_7323_scanner_baseline.csv` — 253

### 3.6 Mechanical lane safety (superseded by §3.7)

| Question | Answer (pre-proof estimate — **superseded**) |
|----------|--------|
| Safe for mechanical merge without new operator judgment? | **Was estimated YES** — dispositions already in slices |
| Post-proof status | **`D17_MECHANICAL_NO_OPERATOR_JUDGMENT_SLICE_1` = NOT_PROVEN / NOT_READY_FOR_COMMIT** |

### 3.7 Post-inventory merge-slices proof result

Local execution **after** this inventory doc (@ `62797052d2d460348c363ca0074ab9f67b5f56d2`):

1. **`D17_MECHANICAL_NO_OPERATOR_JUDGMENT_SLICE_1`** was attempted locally after the inventory doc landed.
2. Command: `python tools/stream_revert_v4_register_and_sync_perf.py --merge-slices` — **completed cleanly** (exit 0).
3. **`unreviewed_count` remained 52,237** (no change).
4. **Actual metric delta = 0**, not the expected ~6,286.
5. **`register_content_sha256` unchanged** (`2017b18f…55303e`). Tool reported `rows_updated: 31,069` on non-UNREVIEWED `register_id` matches (metadata-only / no disposition change).
6. Timestamp-only **`schwab_v4_register_build_meta.json` drift** (`generated_at_utc`) was **reverted**; working tree returned clean except pre-existing untracked `reports/`.
7. The inventory **6,286** figure is **path/line overlap**, not current merge-tool eligibility.
8. The existing merge-slices resolver matches by **`register_id`**, then **`site_key` (path, line, col, pattern_kind, language)** — see `load_slice_disposition_maps` / `_resolve_slice_row` in `tools/stream_revert_v4_register_and_sync_perf.py`.
9. **`by_path_line` resolver coverage = 0 keys** — all slice rows carry `register_id`, so path/line maps are not populated for merge.
10. On UNREVIEWED pinned-register rows, **`_resolve_slice_row` matched 0** rows; **6,282** path/line overlaps have **different `register_id` values** than slice rows at the same site (scanner identity drift).
11. Therefore the mechanical merge-lag lane is **`NOT_PROVEN`** and **`NOT_READY_FOR_COMMIT`**.
12. Reclassification: **6,286** rows → **`path_line_overlap_requires_identity_reconciliation`** (not “mechanically mergeable”).
13. **D17 remains NOT_CLOSED.**
14. **Schwab V4 Register Closure remains NOT_CLOSED.**
15. **No pinned-register metric movement; 155 tracked slice identity rekeys landed** (Path-A waves @ `77675a6` — pinned register unchanged; temp-merge proof only).

| Proof metric | Value |
|--------------|------:|
| Post-merge `unreviewed_count` | 52,237 |
| `unreviewed_count` delta | 0 |
| `bare_governed_exception_count` | 0 (unchanged) |
| `closure_admissible` | false (unchanged) |
| Tool merge-eligible UNREVIEWED rows | **0** |

---

## 4. No-slice gap inventory

**Definition:** Register `UNREVIEWED` with **no** matching `(path, line)` in any slice file. **Path/line accounting only** — not the same as tool-admissible residual after identity reconciliation.

### 4.1 Totals

| Measure | Value |
|---------|------:|
| **No-slice gap count** | **45,951** |
| Money-path cluster (AGENTS roster paths) | 5,172 |
| Docs/governance/tests/OPEN_ITEMS paths | 7,812 |
| `pattern_kind_miss` only | 15,590 |

### 4.2 Top 30 paths (no-slice gap)

- `server.py` — 3,440
- `db.py` — 2,331
- `arch_competition/stack_bundle_eval_v1.py` — 1,175
- `micro_structure.py` — 1,093
- `ml_scheduler.py` — 922
- `math_probabilities.py` — 901
- `math_exposure_core.py` — 794
- `math_levels.py` — 652
- `realized_contract_eval.py` — 586
- `math_volatility.py` — 584
- `governance/SCHWAB_V4_FILE_INVENTORY.csv` — 560
- `v2_decision/a2_option_expression.py` — 552
- `lstm_data.py` — 545
- `OPEN_ITEMS.md` — 521
- `features/signal_layer_v1.py` — 495
- `verification/ui_realtime_transport_audit.py` — 495
- `ml_train.py` — 488
- `tests/test_schwab_universal_coverage_scanner_v3.py` — 427
- `signal_types.py` — 420
- `AGENTS.md` — 411
- `design_mockups/ui_card_provenance_mockup.html` — 387
- `ml_data_common.py` — 345
- `lstm_model.py` — 333
- `arch_competition/ablation_bundle_inference.py` — 332
- `arch_competition/metrics.py` — 332
- `governed_stack_contract.py` — 326
- `snapshot_normalizer.py` — 315
- `levels.py` — 308
- `v2_decision/a2_lifecycle_sidecar.py` — 301
- `schwab_full_field_inventory.py` — 297

### 4.3 Top 30 pattern_kind (no-slice gap)

- `TEXT_LINE_MARKET_TOKEN` — 22,121
- `pattern_kind_miss` — 15,590
- `DICT_LITERAL_MARKET_KEY` — 2,323
- `BINOP_MARKET_IDENT` — 995
- `SUBSCRIPT_MARKET_KEY` — 792
- `ATTRIBUTE_MARKET` — 781
- `DICT_GET_MARKET_NULLABLE` — 710
- `PYTHON_GETATTR_SETATTR` — 519
- `REGISTRY_DISPATCH` — 465
- `JSON_STRING_MARKET_TOKEN` — 232
- `DECORATOR_SITE` — 190
- `GETATTR_MARKET_LITERAL` — 146
- `JSON_KEY_MARKET_TOKEN` — 145
- `MAGIC_NUMERIC_DEFAULT` — 144
- `IFEXP_ZERO_DEFAULT` — 135
- `HTML_ATTR_MARKET_TOKEN` — 118
- `YAML_KEY_MARKET_TOKEN` — 96
- `COERCE_OR_ZERO` — 96
- `DICT_GET_MARKET_DEFAULT` — 87
- `TIME_TIME` — 83
- `CALL_NAMED_DERIVATION` — 54
- `YAML_STRING_MARKET_TOKEN` — 43
- `DATETIME_NOW` — 41
- `TIME_MONOTONIC` — 34
- `COMPUTED_PROPERTY` — 6
- `BOOL_OR_DEFAULT_ZERO` — 2
- `TOML_KEY_MARKET_TOKEN` — 2
- `DYNAMIC_DISPATCH` — 1

### 4.4 Cluster classification (no-slice gap)

| Cluster | Approx rows | Bucket | Next lane |
|---------|------------:|--------|-----------|
| `pattern_kind_miss` | 15,590 | E — scanner/tooling | D17_SCANNER_FALSE_POSITIVE_TRIAGE |
| `TEXT_LINE_MARKET_TOKEN` in docs/tests/governance | subset of 7,812 docs cluster | A — mechanical NOT_MARKET_DATA | Export new phase slices from register baseline |
| `server.py`, `db.py`, ML/arch_competition | top paths table | D — source alignment | D17_SOURCE_CODE_ALIGNMENT_QUEUE |
| `REGISTRY_DISPATCH` | 465+ in no-slice gap | C — operator decision | V3-D resolution + O-NN if needed |
| Money-path (`signals`, `call_engine`, `market_state`, …) | 5,172 | C/D — operator + code | Per-file Read + Class A wire fixes |

---

## 5. Recommended priority queue (updated post-merge proof)

### Lane sequence (safest order)

| Order | Lane | Scope | Notes |
|------:|------|-------|-------|
| **1** | **D17_SLICE_IDENTITY_RECONCILIATION_AUDIT** | **READ_ONLY** | **Required before any merge/repin lane** — see below |
| 2 | D17_MECHANICAL_NO_OPERATOR_JUDGMENT_SLICE_1 | REGISTER_SLICE_ONLY | **Demoted** — blocked until identity reconciliation resolves path/line vs register_id mismatch |
| 3 | D17_SCANNER_FALSE_POSITIVE_TRIAGE | Tooling / read-only triage | `pattern_kind_miss` clusters |
| 4 | D17_REGISTER_SLICE_EXPORT_PHASE3 | Slice export | New phase slices from register baseline |
| 5 | D17_SOURCE_CODE_ALIGNMENT_QUEUE | Source + test | Money-path wire fixes |
| 6 | D17_OPERATOR_DECISION_REGISTER_RECONCILIATION | Operator narrative | O-NN for retained derivations |

### Lane 1 detail — D17_SLICE_IDENTITY_RECONCILIATION_AUDIT (recommended next)

| Field | Value |
|-------|-------|
| **Scope** | **READ_ONLY** |
| **Purpose** | Determine the safe path before any merge/repin execution |
| **Inspect (read-only)** | `governance/register_slices/**`, gitignored `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`, `tools/stream_revert_v4_register_and_sync_perf.py`, `governance/artifacts/schwab_v4_register_build_meta.json`, `governance/artifacts/schwab_v4_scoreboard.json` |
| **Decision options** | **A.** Re-export slices keyed to current register IDs · **B.** Extend merge-slices with ranked `(path, line)` fallback under strict conflict controls (separate tooling lane) · **C.** CI-style scanner regen + merge pipeline and repin · **D.** Stop for operator decision · **E.** Not proven |
| **Proof commands** | Read-only resolver analysis; `python -m tools.schwab_coverage_v4_metrics` (exit 1 EXPECTED_OPEN_D17); no `--merge-slices` unless separately approved |
| **Forbidden until audit completes** | `--merge-slices`, scanner regen, scoreboard regen, slice CSV edits, D17 closure claims — **SUPERSEDED_BY_PATH_A_WAVES** for slice CSV identity edits: Path-A waves 1–6 @ `77675a6` landed 155 identity-only rekeys under strict non-money LINE_SCOPE NMD policy; production `--merge-slices` and register repin remain **NOT_APPROVED** |

### Lane 2 detail — D17_MECHANICAL_NO_OPERATOR_JUDGMENT_SLICE_1 (demoted)

| Field | Value |
|-------|-------|
| **Status** | **NOT_PROVEN / NOT_READY_FOR_COMMIT** (Slice 1 local proof @ `6279705`) — **SUPERSEDED_BY_PATH_A_WAVES** for merge-slices Δ=0 gate: Path-A identity rekeys @ `77675a6` proved temp-merge only; pinned register metrics unchanged |
| **Prior expectation** | −6,286 UNREVIEWED → ~45,951 |
| **Actual result** | Δ = **0** (historical @ `6279705`; pinned register `unreviewed_count` still 52,237 @ `77675a6`) |
| **Blocked until** | `D17_SLICE_IDENTITY_RECONCILIATION_AUDIT` selects path A, B, or C — Path A waves 1–6 **COMPLETE_WITH_EVIDENCE**; production semantic-key merge and register repin remain **NOT_APPROVED** |

### Lane 3 detail — D17_SCANNER_FALSE_POSITIVE_TRIAGE

Focus: 15,590 no-slice + 2,316 path/line-overlap `pattern_kind_miss` rows. Top paths: `server.py`, `db.py`, `arch_competition/stack_bundle_eval_v1.py`. Proof: scanner test suite + regen diff shows miss count drop without disposition theater.

---

## Path-A wave train summary (COMPLETE_WITH_EVIDENCE @ `77675a6`)

**Scope:** D17 strict non-money LINE_SCOPE NMD tracked slice identity rewrite (Policy A). Identity-only rekeys in tracked slice CSVs; no pinned register repin; no production `--merge-slices`.

| Wave | Commit SHA | Files | Row changes | Status |
|------|------------|------:|------------:|--------|
| Pilot | `2e29f12` | 3 | 6 | **CLOSED_WITH_EVIDENCE** |
| Wave 2 | `bccc18e` | 3 | 26 | **CLOSED_WITH_EVIDENCE** |
| Wave 3 | `b03f042` | 2 | 43 | **CLOSED_WITH_EVIDENCE** |
| Wave 4 | `03a3eaa` | 1 | 51 | **CLOSED_WITH_EVIDENCE** |
| Wave 5 | `9cb0f65` | 2 | 18 (9 unique targets) | **CLOSED_WITH_EVIDENCE** |
| Wave 6 | `77675a6` | 4 | 11 (8 unique targets) | **CLOSED_WITH_EVIDENCE** |

| Path-A total | Value |
|--------------|------:|
| Tracked slice files | 15 |
| `register_id` row changes | 155 |
| Forbidden-field drift | 0 |
| Money-path rows | 0 |
| Pinned register changed | **no** |
| Temp-merge proof only | **yes** |
| Temp-merge deduped unreviewed drop (unique targets) | 143 |
| Production `--merge-slices` | **no** |
| Register repin | **NOT_APPROVED** |

**Pinned register truth @ `77675a6` (unchanged by waves):** rows = 83,587; `unreviewed_count` = 52,237; `closure_admissible` = false; `bare_governed_exception_count` = 0; `replaced_count` = 50; content SHA = `2017b18f24870bdf8fa1c9153c4aca4b3e137ebd1167a9b260ed766fd455303e`.

**Preserved:** D17 full closure = **NOT_CLOSED**; Schwab V4 Register Closure = **NOT_CLOSED**; register repin = **NOT_APPROVED**; production semantic-key merge = **NOT_APPROVED**.

---

## 6. D17 closure gates (unchanged)

All must hold before any D17 / Schwab V4 Register Closure claim:

1. `unreviewed_count == 0` and `bare_governed_exception_count == 0` (local + CI)
2. `register_build.partial_scan == false` (already true)
3. Register SHA256 = meta = scoreboard
4. `schwab_oxx_validator` PASS
5. Remote Schwab V4 Register Closure workflow green
6. Branch protection: Objective Audit, Pytest Full Suite, Hardening Gates, Schwab CSV First Guard
7. Diff-emission gate on new market-fact sites (`check_schwab_csv_first`)
8. Deliverable 16 closure audit + operator O-XX narrative

---

## 7. Safety constraints (binding on all future D17 lanes)

- **No mass disposition** without per-row evidence in slice or code fix
- **No hand-editing** generated register CSV
- **No D17 closure claim** while `unreviewed_count > 0`
- **No Schwab V4 Register Closure claim** as program complete
- **No real-money readiness claim** from register walk-down
- **No card-fidelity claim** — orthogonal program
- **Operator approval** before any merge/repin mechanical lane — **blocked until identity reconciliation audit**
- **Does not affect** closed card/harness lanes (trust-aware harness, workflow trigger narrowing @ `ed555f7`; inventory doc @ `6279705`)

---

## 8. Relationship to card fidelity / RTH

| Program | Interaction |
|---------|-------------|
| Closed card/harness lanes | **No retroactive effect** |
| RTH universal runtime proof | **Separate** — session gate blocked |
| Real-money readiness | **Not proven** by D17 inventory |
| D17 | Schwab/data-governance register walk-down only |

---

## Appendix A — Full slice file inventory (85 files)

| Slice file | Rows | Primary disposition(s) |
|---|---:|---|
| `bayesian_fusion_py_1_859.csv` | 1037 | NOT_MARKET_DATA 989, KEEP_DERIVED 32, PASS_THROUGH 16 |
| `bayesian_fusion_py_1_859_scanner_baseline.csv` | 361 | NOT_MARKET_DATA 361 |
| `call_engine_py_1_1768.csv` | 2370 | NOT_MARKET_DATA 2316, KEEP_DERIVED 39, PASS_THROUGH 15 |
| `call_engine_py_1_1768_scanner_baseline.csv` | 1248 | NOT_MARKET_DATA 1248 |
| `canonical_contract_py_1_346.csv` | 346 | NOT_MARKET_DATA 341, KEEP_DERIVED 5 |
| `canonical_contract_py_1_346_scanner_baseline.csv` | 223 | NOT_MARKET_DATA 217, KEEP_DERIVED 6 |
| `cascade_stack_contract_py_1_133.csv` | 133 | NOT_MARKET_DATA 128, KEEP_DERIVED 4, PASS_THROUGH 1 |
| `cascade_stack_schema_py_1_42.csv` | 42 | NOT_MARKET_DATA 40, PASS_THROUGH 1, KEEP_DERIVED 1 |
| `db_feature_adapter_py_1_50.csv` | 50 | NOT_MARKET_DATA 39, PASS_THROUGH 10, KEEP_DERIVED 1 |
| `db_feature_adapter_py_1_50_scanner_baseline.csv` | 14 | NOT_MARKET_DATA 9, PASS_THROUGH 5 |
| `features_fusion_policy_contract_py_1_106.csv` | 106 | NOT_MARKET_DATA 95, KEEP_DERIVED 6, PASS_THROUGH 5 |
| `features_fusion_policy_contract_py_1_106_scanner_baseline.csv` | 68 | NOT_MARKET_DATA 64, PASS_THROUGH 4 |
| `fusion_model_input_py_1_87.csv` | 87 | NOT_MARKET_DATA 82, KEEP_DERIVED 5 |
| `fusion_policy_contract_py_1_106.csv` | 106 | NOT_MARKET_DATA 95, KEEP_DERIVED 6, PASS_THROUGH 5 |
| `fusion_policy_contract_py_1_130.csv` | 130 | NOT_MARKET_DATA 119, KEEP_DERIVED 6, PASS_THROUGH 5 |
| `liquidity_value_engine_py_1_1520.csv` | 1969 | NOT_MARKET_DATA 1939, KEEP_DERIVED 26, PASS_THROUGH 4 |
| `liquidity_value_engine_py_1_1520_scanner_baseline.csv` | 867 | NOT_MARKET_DATA 867 |
| `lstm_sequence_input_py_1_238.csv` | 238 | NOT_MARKET_DATA 225, KEEP_DERIVED 9, PASS_THROUGH 4 |
| `lstm_sequence_input_py_1_238_scanner_baseline.csv` | 121 | NOT_MARKET_DATA 117, KEEP_DERIVED 4 |
| `market_context_py_1_961.csv` | 961 | NOT_MARKET_DATA 905, REPLACED 28, KEEP_DERIVED 23 |
| `market_context_py_1_961_scanner_baseline.csv` | 629 | NOT_MARKET_DATA 591, KEEP_DERIVED 16, REPLACED 16 |
| `market_state_py_1501_1722.csv` | 156 | NOT_MARKET_DATA 134, KEEP_DERIVED 14, PASS_THROUGH 8 |
| `market_state_py_1501_1722_scanner_baseline.csv` | 140 | NOT_MARKET_DATA 140 |
| `market_state_py_1_1500.csv` | 1127 | NOT_MARKET_DATA 1100, REPLACED 14, KEEP_DERIVED 9 |
| `market_state_py_1_1500_scanner_baseline.csv` | 1097 | NOT_MARKET_DATA 1097 |
| `mc_fusion_adjustment_py_1_583.csv` | 671 | NOT_MARKET_DATA 656, KEEP_DERIVED 10, PASS_THROUGH 5 |
| `mc_fusion_adjustment_py_1_583_scanner_baseline.csv` | 177 | NOT_MARKET_DATA 177 |
| `ml_predict_py_1_1631.csv` | 1902 | NOT_MARKET_DATA 1877, KEEP_DERIVED 19, PASS_THROUGH 6 |
| `ml_predict_py_1_1631_scanner_baseline.csv` | 543 | NOT_MARKET_DATA 543 |
| `monte_carlo_py_1_425.csv` | 581 | NOT_MARKET_DATA 563, KEEP_DERIVED 13, PASS_THROUGH 5 |
| `monte_carlo_py_1_425_scanner_baseline.csv` | 289 | NOT_MARKET_DATA 289 |
| `multi_horizon_decision_py_1_854.csv` | 1053 | NOT_MARKET_DATA 1017, KEEP_DERIVED 22, PASS_THROUGH 14 |
| `multi_horizon_decision_py_1_854_scanner_baseline.csv` | 419 | NOT_MARKET_DATA 419 |
| `mvp_source_coercion_py_1_139.csv` | 139 | NOT_MARKET_DATA 132, KEEP_DERIVED 7 |
| `order_flow_engine_py_1_1161.csv` | 1607 | NOT_MARKET_DATA 1588, KEEP_DERIVED 14, PASS_THROUGH 5 |
| `order_flow_engine_py_1_1161_scanner_baseline.csv` | 958 | NOT_MARKET_DATA 958 |
| `parallel_stack_schema_py_1_92.csv` | 92 | NOT_MARKET_DATA 89, KEEP_DERIVED 3 |
| `parallel_stack_schema_py_1_92_scanner_baseline.csv` | 40 | NOT_MARKET_DATA 38, KEEP_DERIVED 2 |
| `phase2_docs_md_not_market_data.csv` | 4040 | NOT_MARKET_DATA 4040 |
| `phase2_governance_md_not_market_data.csv` | 4170 | NOT_MARKET_DATA 4170 |
| `phase2_mega_inventories_not_market_data.csv` | 3038 | NOT_MARKET_DATA 3038 |
| `phase2_tests_non_contract_not_market_data.csv` | 14772 | NOT_MARKET_DATA 14772 |
| `phase3_adapter_lexical_not_market_data.csv` | 548 | NOT_MARKET_DATA 548 |
| `phase3_adapter_wire_disposition.csv` | 73 | REPLACED 47, KEEP_DERIVED 13, NOT_MARKET_DATA 13 |
| `phase4_market_state_lexical_not_market_data.csv` | 424 | NOT_MARKET_DATA 424 |
| `phase5a_market_state_structural_not_market_data.csv` | 3 | NOT_MARKET_DATA 3 |
| `phase5b_market_state_mixed_line_lexical_not_market_data.csv` | 34 | NOT_MARKET_DATA 34 |
| `phase_oxx_perf_proof_lexical_not_market_data.csv` | 46 | NOT_MARKET_DATA 46 |
| `prediction_engine_py_1_1249.csv` | 1458 | NOT_MARKET_DATA 1426, KEEP_DERIVED 21, PASS_THROUGH 11 |
| `prediction_engine_py_1_1249_scanner_baseline.csv` | 433 | NOT_MARKET_DATA 433 |
| `regime_engine_py_1_563.csv` | 688 | NOT_MARKET_DATA 657, KEEP_DERIVED 16, PASS_THROUGH 15 |
| `regime_engine_py_1_563_scanner_baseline.csv` | 233 | NOT_MARKET_DATA 233 |
| `regime_mvp_context_py_1_62.csv` | 62 | NOT_MARKET_DATA 56, KEEP_DERIVED 6 |
| `regime_mvp_context_py_1_62_scanner_baseline.csv` | 36 | NOT_MARKET_DATA 36 |
| `rules_engine_py_1_252.csv` | 318 | NOT_MARKET_DATA 297, PASS_THROUGH 12, KEEP_DERIVED 9 |
| `rules_engine_py_1_252_scanner_baseline.csv` | 124 | NOT_MARKET_DATA 124 |
| `server_py_1501_3000.csv` | 876 | NOT_MARKET_DATA 793, GOVERNED_EXCEPTION 57, REPLACED 26 |
| `server_py_1501_3000_scanner_baseline.csv` | 857 | NOT_MARKET_DATA 812, GOVERNED_EXCEPTION 45 |
| `server_py_1_1500.csv` | 837 | NOT_MARKET_DATA 827, GOVERNED_EXCEPTION 8, REPLACED 2 |
| `server_py_1_1500_scanner_baseline.csv` | 837 | NOT_MARKET_DATA 837 |
| `server_py_3001_4500.csv` | 891 | NOT_MARKET_DATA 683, PASS_THROUGH 110, KEEP_DERIVED 47 |
| `server_py_3001_4500_scanner_baseline.csv` | 682 | NOT_MARKET_DATA 682 |
| `server_py_4501_6000.csv` | 1007 | NOT_MARKET_DATA 831, PASS_THROUGH 110, KEEP_DERIVED 58 |
| `server_py_4501_6000_scanner_baseline.csv` | 853 | NOT_MARKET_DATA 844, NO_SCHWAB_EQUIVALENT 8, KEEP_DERIVED 1 |
| `server_py_6001_7323.csv` | 654 | NOT_MARKET_DATA 624, KEEP_DERIVED 14, REPLACED 9 |
| `server_py_6001_7323_scanner_baseline.csv` | 614 | NOT_MARKET_DATA 614 |
| `shared_sequence_context_py_1_208.csv` | 208 | NOT_MARKET_DATA 202, KEEP_DERIVED 4, PASS_THROUGH 2 |
| `shared_sequence_context_py_1_219.csv` | 219 | NOT_MARKET_DATA 213, KEEP_DERIVED 4, PASS_THROUGH 2 |
| `signals_py_1_1422.csv` | 1422 | NOT_MARKET_DATA 1379, KEEP_DERIVED 22, PASS_THROUGH 21 |
| `signals_py_1_1422_scanner_baseline.csv` | 467 | NOT_MARKET_DATA 461, KEEP_DERIVED 4, PASS_THROUGH 2 |
| `stack_integrity_v1_py_1_83.csv` | 83 | NOT_MARKET_DATA 80, KEEP_DERIVED 3 |
| `static_index_html_1501_3000.csv` | 75 | GOVERNED_EXCEPTION 57, REPLACED 16, NOT_MARKET_DATA 2 |
| `static_index_html_3001_4100.csv` | 67 | GOVERNED_EXCEPTION 58, REPLACED 7, NOT_MARKET_DATA 2 |
| `static_index_html_3001_4500.csv` | 88 | GOVERNED_EXCEPTION 67, NOT_MARKET_DATA 14, REPLACED 7 |
| `static_index_html_4501_6000.csv` | 110 | GOVERNED_EXCEPTION 85, PASS_THROUGH 13, NOT_MARKET_DATA 12 |
| `static_index_html_6001_7500.csv` | 128 | GOVERNED_EXCEPTION 96, NOT_MARKET_DATA 18, PASS_THROUGH 14 |
| `static_index_html_7501_9000.csv` | 79 | NOT_MARKET_DATA 52, GOVERNED_EXCEPTION 15, PASS_THROUGH 12 |
| `static_index_html_9001_9349.csv` | 26 | NOT_MARKET_DATA 26 |
| `static_index_html_9350_9456.csv` | 6 | NOT_MARKET_DATA 6 |
| `training_cache_py_1_1118.csv` | 1118 | NOT_MARKET_DATA 1092, KEEP_DERIVED 26 |
| `training_cache_py_1_1208.csv` | 1208 | NOT_MARKET_DATA 1182, KEEP_DERIVED 26 |
| `volatility_regime_py_1_291.csv` | 354 | NOT_MARKET_DATA 333, KEEP_DERIVED 13, PASS_THROUGH 8 |
| `volatility_regime_py_1_291_scanner_baseline.csv` | 129 | NOT_MARKET_DATA 129 |
| `xgb_model_input_py_1_151.csv` | 151 | NOT_MARKET_DATA 134, PASS_THROUGH 10, KEEP_DERIVED 7 |
| `xgb_model_input_py_1_151_scanner_baseline.csv` | 49 | NOT_MARKET_DATA 40, KEEP_DERIVED 6, PASS_THROUGH 3 |

---

## Appendix B — Analysis provenance

- Read-only Python analysis @ `62797052d2d460348c363ca0074ab9f67b5f56d2`
- Inventory merge key (accounting): `(path, line)` normalized
- Tool merge key (actual): `register_id` → `site_key`; `by_path_line` inactive when slice rows carry `register_id`
- Slice 1 local proof: `--merge-slices` @ `6279705`; `unreviewed_count` delta **0**
- Metrics: `python -m tools.schwab_coverage_v4_metrics` (exit 1 EXPECTED_OPEN_D17)
- Governance: `check_agent_preload_contract` PASS; `--objective-audit` PASS; O-XX validator PASS
- **Amendment only** — this document (pending operator commit review). D17 / Schwab V4 Register Closure **NOT_CLOSED**.
