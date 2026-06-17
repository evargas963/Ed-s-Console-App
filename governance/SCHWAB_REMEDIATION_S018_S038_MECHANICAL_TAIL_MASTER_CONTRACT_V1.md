> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S018_S038_MECHANICAL_TAIL_MASTER_CONTRACT_V1.md`.

# Schwab Remediation S018–S038 Mechanical Tail Master Contract V1

**Status:** FORMALLY_CLOSED_RECORDED  
**Date:** 2026-05-08  
**Authority:** `governance/SCHWAB_REMEDIATION_SLICE_PLAN_V1.md` (MEDIUM tail § + LOW tail §)  
**Closure audit:** `governance/SCHWAB_REMEDIATION_SLICE_CLOSURE_AUDIT_V1.md`

---

## Purpose

Slice plan **reserved** slice IDs **S018–S027** (~30 instances, MEDIUM tail) and **S028–S038** (11 IDs, ~102 instances, LOW tail) but **did not publish** per-ID risk patterns, canonical CSV rows, or line-level consumer tables for those IDs. Those IDs exist for **planning and traceability** only.

This master contract records **formal closure on mechanical, aggregate grounds** without inventing per-ID consumer evidence that the slice plan never supplied.

---

## CSV-first declaration

```text
Schwab CSV authority checked: yes (repo-wide CSV-first discipline; `tools/check_schwab_csv_first.py`)
CSV row(s): NOT_ENUMERATED_PER_SLICE_PLAN for S018–S038 individually — see SCHWAB_REMEDIATION_SLICE_PLAN_V1.md (MEDIUM tail line re S018–S027; LOW Priority Tail for S028–S038). Instance counts per ID follow closure-audit apportionment for traceability only.
Derived-field disposition: MECHANICAL_TAIL_CLOSED — manual crosswalk residual rows = 0; whole-repo guard PASS; classifier + prior remediation waves absorb tagged mechanical rows. No additional runtime code change is asserted for this bucket beyond what is already merged and guarded.
All consumers checked: not applicable at per-ID granularity — the slice plan never required per-ID consumer tables for S018–S038. Aggregate closure evidence substitutes as defined in §Evidence below.
```

---

## Evidence (aggregate)

| Artifact | Requirement | State |
|----------|----------------|-------|
| `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv` | Header-only / zero manual residual at closure | **0** manual rows (audit-time) |
| `python tools/check_schwab_csv_first.py --whole-repo` | Exit 0 | **PASS** |
| Classifier / crosswalk regeneration | Consistent with guarded tree | `python tools/classify_schwab_csv_crosswalk.py` |
| Prior HIGH/MEDIUM contracts | Absorb hot-path risk | Cited in `SCHWAB_REMEDIATION_SLICE_CLOSURE_AUDIT_V1.md` for S001–S017 |

---

## All-consumers disposition (single row)

| Consumer | Status | Evidence | Note |
|----------|--------|----------|------|
| Per-ID sites for S018–S038 | `not-applicable-at-this-granularity` | Slice plan contains no per-ID file/line registry for these IDs. | Closure is **governance-recorded mechanical tail**, not a line-by-line remediation pass. If the plan is later amended with real per-ID mappings, replace this contract with field-scoped contracts. |

---

## Slice registry (apportionment = closure-audit columns)

| ID | Tier | Original instances (apportioned) | Per-ID stub file |
|----|------|-----------------------------------:|------------------|
| S018 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S018_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S019 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S019_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S020 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S020_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S021 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S021_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S022 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S022_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S023 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S023_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S024 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S024_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S025 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S025_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S026 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S026_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S027 | MEDIUM | 3 | `SCHWAB_REMEDIATION_S027_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S028 | LOW | 10 | `SCHWAB_REMEDIATION_S028_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S029 | LOW | 10 | `SCHWAB_REMEDIATION_S029_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S030 | LOW | 10 | `SCHWAB_REMEDIATION_S030_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S031 | LOW | 9 | `SCHWAB_REMEDIATION_S031_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S032 | LOW | 9 | `SCHWAB_REMEDIATION_S032_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S033 | LOW | 9 | `SCHWAB_REMEDIATION_S033_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S034 | LOW | 9 | `SCHWAB_REMEDIATION_S034_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S035 | LOW | 9 | `SCHWAB_REMEDIATION_S035_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S036 | LOW | 9 | `SCHWAB_REMEDIATION_S036_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S037 | LOW | 9 | `SCHWAB_REMEDIATION_S037_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |
| S038 | LOW | 9 | `SCHWAB_REMEDIATION_S038_MECHANICAL_TAIL_SLICE_CONTRACT_V1.md` |

---

## Verification

```text
python -m pytest tests/test_check_schwab_csv_first.py tests/test_classify_schwab_csv_crosswalk.py
python tools/check_schwab_csv_first.py --whole-repo
```

Expected: pytest pass; guard exit code 0.

---

## Non-misrepresentation statement

```text
mechanical_tail_s018_s038 = FORMALLY_CLOSED_RECORDED
per_id_consumer_line_tables = NOT_PUBLISHED_BY_SLICE_PLAN
honest_upgrade_path = amend slice plan with real mappings OR absorb into future field-scoped contracts
```
