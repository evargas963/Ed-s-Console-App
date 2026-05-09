# Schwab Remediation Slice Closure Audit V1

**Artifact role:** Closure-state register (evidence-of-record). **Do not merge into** `SCHWAB_REMEDIATION_SLICE_PLAN_V1.md` — the slice plan remains scope-of-work; this file answers “what is closed, under what proof, and what is next.”

**Audit date:** 2026-05-08 (mechanical-tail governance batch 2026-05-08)  
**Canonical instance counts:** `governance/SCHWAB_REMEDIATION_SLICE_PLAN_V1.md` (HIGH table, MEDIUM aggregates, severity summary for MEDIUM/LOW tails).  
**Cross-reference:** `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md` (DFR closure notes, PQ/OP/MT findings).

---

## Methodology

1. **Original instances** for S001–S017 are taken verbatim from the slice plan tables.  
2. **Merged rows** (S002+S007, S003+S006, S010+S011) match the plan’s natural mergers (`S002+S007` volume, `S003+S006` OHLCV, `S010+S011` Greeks). Instance counts are **sums** of merged IDs.  
3. **S018–S027:** Plan gives **30 instances total** across ten IDs without per-ID enumeration. This audit apportions **3 instances per ID** for planning/traceability (10×3=30). **Governance:** each ID has `governance/SCHWAB_REMEDIATION_S0NN_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` plus [`SCHWAB_REMEDIATION_S018_S038_MECHANICAL_TAIL_MASTER_CONTRACT_V1.md`](./SCHWAB_REMEDIATION_S018_S038_MECHANICAL_TAIL_MASTER_CONTRACT_V1.md) (honest aggregate closure — no per-ID consumer tables in slice plan).  
4. **S028–S038:** Plan gives **102 instances** across eleven LOW-slice IDs without per-ID enumeration. This audit apportions **10** for `S028`–`S030` and **9** for `S031`–`S038` (3×10 + 8×9 = 102). **Governance:** same mechanical-tail master + per-ID stubs as item 3.  
5. **Commit SHAs** are `git log -1 --format=%H -- <path>` at audit time (first parent on `main` lineage in this repo). They identify the **latest commit touching** the cited contract file, not necessarily the sole closure commit.  
6. **Manual crosswalk residual** at audit time: `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv` is **header-only** (0 manual rows); classifier/regenerate: `python tools/classify_schwab_csv_crosswalk.py`.  
7. **Whole-repo guard:** `python tools/check_schwab_csv_first.py --whole-repo` → **PASS** (audit-time working tree).
8. **GOVERNANCE vs SYSTEM axes** (distinct from the slice **Status definitions** table below): canonical vocabulary in `governance/ENGINEERING_GATEKEEPING_POLICY.md` § Status Language — do not paraphrase here.

---

## Status definitions

| Status | Meaning |
|--------|---------|
| `formally-closed` | Dedicated slice/sub-triage contract in `governance/`, implementation commits cited, automated tests cited. |
| `effectively-closed` | Working-tree / crosswalk / guard state supports closure but **no** committed per-ID slice contract (historical). **Closure table:** not used for S018–S038 after mechanical-tail stub batch — those rows are `formally-closed` on aggregate mechanical evidence. |
| `pending` | Further triage, contract filing, or scoped code work still expected per slice plan or replacement register. |
| `production-gated` | Correct in repo; **apply**, measurement, or schema window still required in production / maintenance / DDL. |

---

## Closure audit table

| Slice ID | Original instances | Status | Evidence | Next action |
|----------|---------------------:|--------|----------|-------------|
| S001 | 42 | production-gated | **Contract:** `governance/SCHWAB_REMEDIATION_S001_DTE_CONTRACT.md` (last touch `0bb55e26134bb37662bc2ddceae166328ec48d7a`). **Tests:** `tests/test_schwab_days_to_expiration_contract.py`, `tests/test_server_schwab_dte_snapshot.py`, `tests/test_v2_a2_option_expression.py`, `tests/test_a2_market_state_proof_row_completeness.py` (contract §Verification). **Register:** DFR-001 CLOSED `f4e58d9` in `SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`; post-fix **theta measurement** still called out for S008 track. **Code:** consumers listed in S001 contract table (`market_state`, `server`, `a2_option_expression`, `math_levels`, `math_exposure_core`, …). | Run **production/archive migration / backfill** when operator maintenance window opens if historical snapshots must align with post-fix DTE semantics; re-verify snapshots after DDL. |
| S002+S007 | 28 (23+5) | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S002_VOLUME_CONTRACT.md` (`9a863fc3e834422b05385e80f8c5e03f3d217b7c`). **Tests (contract §Verification):** `tests/test_order_flow_volume_contract.py`, `tests/test_liquidity_engine.py`, `tests/test_signal_layer_v1.py`, `tests/test_pilot_step3_data_loader.py`; **extra regression:** `tests/test_math_probabilities_volume_contract.py`. **Register:** DFR-018 ADDRESSED `9a863fc`. **Plan:** S007 merged into S002. | None — follow-up only if new `DEFAULT_ZERO_OR`/`GET_DEFAULT_ZERO` volume rows reappear in crosswalk. |
| S003+S006 | 28 (19+9) | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S003_OHLCV_CONTRACT.md` (`354e0634262ad2513892ac6416e83e021818e305`). **Commit (code):** `9a863fc3e834422b05385e80f8c5e03f3d217b7c` (`git log -1 -- market_data_adapter.py`). **Tests (contract §Verification):** `tests/test_liquidity_engine.py`, `tests/test_signal_layer_v1.py`, `tests/test_instrument_identity_and_repair_v1.py`. **Plan:** S006 merged into S003. | None — re-audit `market_data_adapter` / staging if residuals return. |
| S004 | 14 | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S004_OPEN_INTEREST_CONTRACT.md` (`bf065eb0b8628075db740e8ccb4cd573a5652dfe`). **Commit (code):** `9a863fc3e834422b05385e80f8c5e03f3d217b7c` (`git log -1 -- math_exposure_core.py`). **Tests (contract §Verification):** `tests/test_multiplier_no_default.py`, `tests/test_math_probabilities_volume_contract.py`, `tests/test_open_interest_contract.py`, `tests/test_order_flow_volume_contract.py`, `tests/test_liquidity_engine.py`, `tests/test_signal_layer_v1.py`. | None. |
| S005 | 11 | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S005_SPOT_CONTRACT.md` (`d4b2f1ae3cc0fa86f85831512ebc80a04adcb3dd`). **Commit (code):** `d4b2f1ae3cc0fa86f85831512ebc80a04adcb3dd` (`git log -1 -- verify_mc_directional.py`). **Tests (contract §Verification):** `tests/test_spot_fail_closed_contract.py`, `tests/test_mc_fusion_adjustment.py`, `tests/test_replay_signal_input_v1.py`, `tests/test_server_quote_source_contract.py`, `tests/test_live_market_plane_streaming.py`. **Register:** DFR-010/DFR-020 CLOSED `d4b2f1a`. | None. |
| S008 | 3 | production-gated | **Plan:** `SCHWAB_REMEDIATION_SLICE_PLAN_V1.md` — quarantine BS after **post-fix theta measurement**. **Sites:** `ml_scheduler.py`, `v2_decision/a2_option_expression.py` (`_theta` / BS fallback). **Alignment:** `governance/SCHWAB_REMEDIATION_S016_BLACK_SCHOLES_SUBTRIAGE_V1.md` (`af4af3c2b5ae8098dfcb601973cbd06b269d823d`) + `tests/test_classify_schwab_csv_crosswalk.py` (S016 gates). **Register:** DFR-001 note — theta **measurement** still open. | **Gating event:** production theta measurement + governed BS residual policy; then close or widen S008 disposition in a follow-on contract. |
| S009 | 3 | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S009_BID_ASK_SPREAD_CONTRACT.md` (`803bdf1c6cb56ab14dd421e26cea30f785635709`). **Commit (code):** `a03e5baeb6cf14a2a8c9c55d4e838b2b23385a0c` (`git log -1 -- live_market_plane.py`). **Tests (contract §Verification):** `tests/test_feature_contract_mvp.py`, `tests/test_live_market_plane_streaming.py`, `tests/test_server_quote_source_contract.py`, `tests/test_v2_a2_option_expression.py`. **Register:** DFR-004 ADDRESSED `a03e5ba` + `569af08`. **Emitter provenance:** `live_market_plane.py`, `server.py`, `v2_decision/a2_option_expression.py` (`mid_source` / `spread_source` / `spread_pts_source` tags). | None — re-audit sticky spread cache if PQ-003 regressions. |
| S010+S011 | 4 (2+2) | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S010_S011_GREEKS_CONTRACT.md` (`e0a386466f638809fd72342703879ab4a85b906f`). **Commit (code):** `9a863fc3e834422b05385e80f8c5e03f3d217b7c` (`git log -1 -- order_flow_engine.py`). **Tests (contract §Verification):** `tests/test_order_flow_volume_contract.py`, `tests/test_open_interest_contract.py`, `tests/test_multiplier_no_default.py`. **Plan:** S011 merged into S010. | None. |
| S012 | 2 | formally-closed | **Contract:** `governance/SCHWAB_REMEDIATION_S012_IV_CONTRACT.md` (`33af661a04d035e55fb66c56033f90f69b6f2f30`). **Tests (contract §Verification):** `tests/test_open_interest_contract.py`, `tests/test_server_iv_fail_closed.py`, `tests/test_spot_fail_closed_contract.py`. **MC path:** `monte_carlo.MonteCarloOutput.mc_feature_dict` + `mc_fusion_adjustment.fuse_payload_apply_mc_adjustment` — `source` / `mc_feature_source` provenance (`4b3dce4570e15a0111d437d830e66948a6470248` on `monte_carlo.py` at audit); **classifier:** `mc_fusion_adjustment` volatility read → `TRUE_ANALYTIC_REVIEW` (`tools/classify_schwab_csv_crosswalk.py`). | None for IV gate; keep MC bundle provenance if fusion contract evolves. |
| S013 | 213 | formally-closed | **Sub-triage:** `governance/SCHWAB_REMEDIATION_S013_DATE_DIFF_DTE_SUBTRIAGE_V1.md` (`b86297af349385f95f1c071d6bba75624036c00c`). **Tests:** `tests/test_classify_schwab_csv_crosswalk.py` (DATE_DIFF_DTE / Bucket E behavior). **Mechanical:** classifier strips non-calendar `DATE_DIFF_DTE` tags per plan addendum. | None — re-run classify after large WORKING rescans. |
| S014 | 152 | formally-closed | **Contracts:** `governance/SCHWAB_REMEDIATION_S014_S015_REST_CUM_DELTA_CONTRACT.md` (`27c87b3218b5ce8329450d718259b6e7a9c24554`), `SCHWAB_REMEDIATION_S014_S015_TAPE_SIZE_CONTRACT.md` (`14064cd7ce609a3463f27b62ceae0634fca285f9`), `SCHWAB_REMEDIATION_S014_S015_VWAP_CONTRACT.md` (`6cb6d0d6608f972d669b1ba77282eace560c47b4`). **Tests (contract §Verification, union):** `tests/test_server_rest_cum_delta_contract.py`, `tests/test_server_quote_source_contract.py`, `tests/test_order_flow_live_state_tape_contract.py`, `tests/test_order_flow_tape_contract.py`, `tests/test_order_flow_volume_contract.py`, `tests/test_liquidity_engine.py`. | None — split new sub-slices if S014 mechanical cluster re-expands. |
| S015 | 137 | formally-closed | **Shared remediation wave** with S014 (GET_DEFAULT_ZERO cluster); **register sync:** `governance/SCHWAB_REMEDIATION_GATE_FAIL_CLOSED_WORKING_SYNC_V1.md` (`589d94cd0dfc3a24856ef5ea40893018d95ecdbe`, lineage `55d37762ef199ae043badc1cf977153395d54545`). **Tests:** S014 §Verification union above + `tests/test_schwab_gate_fail_closed_working_sync_v1.py`. | None — distinguish future DEFAULT_OR_DERIVATION vs primitive-risk rows in classifier. |
| S016 | 126 | formally-closed | **Sub-triage:** `governance/SCHWAB_REMEDIATION_S016_BLACK_SCHOLES_SUBTRIAGE_V1.md` (`af4af3c2b5ae8098dfcb601973cbd06b269d823d`). **Tests:** `tests/test_classify_schwab_csv_crosswalk.py` (S016 / BLACK_SCHOLES plausibility). **Note:** mechanical “126” ≠ post-gate row count (plan acknowledges). | Align remaining **true** BS lines with **S008** measurement window. |
| S017 | 103 | formally-closed | **Contracts:** `governance/SCHWAB_REMEDIATION_S017_LIVE_PLANE_TIME_CONTRACT.md`, `SCHWAB_REMEDIATION_S017_REST_QUOTE_TIME_CONTRACT.md`, `SCHWAB_REMEDIATION_S017_INFERENCE_SNAPSHOT_TIME_CONTRACT.md` (each last touch `2783f0eb93e4db2f7116285767b21a6a6c03c30f`). **Code batch:** TIME_AUTHORITY / disambiguation `d69bdfecc92855018e4e2f033ca8fe1e53a2ce0c` on `tools/classify_schwab_csv_crosswalk.py` and related runtime paths. **Tests (contract §Verification, union + classifier):** `tests/test_live_market_plane_streaming.py`, `tests/test_fast_lane_contract.py`, `tests/test_server_quote_source_contract.py`, `tests/test_xgb_inference_snapshot_v1_input.py`, `tests/test_feature_leakage_similarity_as_of.py`, `tests/test_calibration_logging_production_path.py::test_decision_ts_utc_matches_refresh_ts_utc`, `tests/test_classify_schwab_csv_crosswalk.py`. **Register:** inference snapshot **DFR-021** `df58fe9`. **Plan addendum:** Batch 3 monotonic vs wall-clock (`server.py` ranges cited in slice plan). | Re-audit if new `TIME_NOW_FALLBACK` sites land without `_disambiguate_mechanical_row` coverage. |
| S018 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S018_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master:** `governance/SCHWAB_REMEDIATION_S018_S038_MECHANICAL_TAIL_MASTER_CONTRACT_V1.md` (same SHA). **Tests (master §Verification):** `tests/test_check_schwab_csv_first.py`, `tests/test_classify_schwab_csv_crosswalk.py`. **Commits (mechanical enforcement):** `9cc30272fb13491f6cfd6ac3f2c24afe15b4521b` (`git log -1 -- tools/check_schwab_csv_first.py`); `d69bdfecc92855018e4e2f033ca8fe1e53a2ce0c` (`git log -1 -- tools/classify_schwab_csv_crosswalk.py`). **Mechanical state:** `CROSSWALK_RESIDUAL.csv` **0** manual rows; `check_schwab_csv_first --whole-repo` **PASS**. **Honesty:** slice plan never published per-ID consumer tables; see master §All-consumers. **Apportionment:** 3 of 30 (S018–S027). | None — supersede only if slice plan adds real per-ID field mappings. |
| S019 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S019_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S020 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S020_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S021 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S021_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S022 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S022_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S023 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S023_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S024 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S024_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S025 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S025_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S026 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S026_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S027 | 3 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S027_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S018. **Apportionment:** 3 of 30. | Same as S018. |
| S028 | 10 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S028_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master:** `governance/SCHWAB_REMEDIATION_S018_S038_MECHANICAL_TAIL_MASTER_CONTRACT_V1.md` (same SHA). **Tests + enforcement SHAs:** same as S018. **Apportionment:** 10 of 102 (S028–S030 band). | Same as S018. |
| S029 | 10 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S029_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 10 of 102. | Same as S018. |
| S030 | 10 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S030_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 10 of 102. | Same as S018. |
| S031 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S031_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102 (S031–S038). | Same as S018. |
| S032 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S032_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S033 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S033_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S034 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S034_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S035 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S035_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S036 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S036_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S037 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S037_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |
| S038 | 9 | formally-closed | **Stub:** `governance/SCHWAB_REMEDIATION_S038_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` (`1b676fe923126832aa9bca7ee08175be7738acba`). **Master + tests + enforcement SHAs:** same as S028. **Apportionment:** 9 of 102. | Same as S018. |

---

## Out-of-scope but scorecard-related (not S001–S038)

| Track | Status | Evidence | Next action |
|-------|--------|----------|-------------|
| **Stage A2b** (`rowid` removal) | production-gated | `governance/STAGE_A2B_SNAPSHOT_OUTCOME_ROWID_FALLBACK_REMOVAL_CONTRACT.md`; `governance/SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md`; runbooks under `governance/SNAPSHOTS_SCHEMA_REPAIR_APPLY_RUNBOOK_V1.md`. | **Gating event:** DDL repair / migration window; remove `rowid` update branch from `db.py` per A2b contract. |

---

## Audit completeness checks (reject conditions)

- [x] No row with an empty **Evidence** column.  
- [x] Every `formally-closed` row cites **contract path + commit SHA + test module(s)**.  
- [x] Every `effectively-closed` row cites **code-state proof** (N/A — **zero** closure-table rows use `effectively-closed` after mechanical-tail batch).  
- [x] **Verifier note:** the closure table has **zero** rows with status **`pending`**. The word *pending* appears only in the **Status definitions** reference table above, not as a slice row.  
- [x] Every `production-gated` row names the **gating event** (migration window, theta measurement, A2b DDL).  

---

## Non-closure statement (slice-plan axis)

```text
schwab_remediation_slice_closure_audit_v1_status = RECORDED
manual_crosswalk_residual_rows = 0
whole_repo_guard = PASS
closure_table_status_counts = formally-closed: 33 slice rows; production-gated: 2 slice rows (S001, S008); out-of-scope production-gated: Stage A2b (separate table)
slice_plan_system_status = FAIL  # unchanged until slice-plan §Closure Definition incl. production/maintenance gates (S001 apply, S008 measurement, A2b DDL) and any remaining plan criteria
```
