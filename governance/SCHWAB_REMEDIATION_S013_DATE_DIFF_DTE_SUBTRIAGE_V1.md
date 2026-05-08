# Schwab Remediation S013 — `DATE_DIFF_DTE` Sub-Triage V1

**Status:** SUBTRIAGE_COMPLETE (method + buckets; no new slice contracts in this artifact)  
**Date:** 2026-05-08  
**Parent slice:** S013 `DATE_DIFF_DTE` (Medium aggregate)  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv` — primitive `chains.*.daysToExpiration`

---

## 1. Count reconciliation (why “213” ≠ “562 rows”)

| Source | What it counts | Approx. |
|--------|----------------|--------:|
| Slice plan S013 | Clustered **mechanical-scan instances** (pre-classifier / separate pass) | 213 |
| `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_CLASSIFIED.csv` | **CSV rows** tagged `DATE_DIFF_DTE`, excluding `.claude/worktrees/*` | 562 |
| Same CSV, `server.py` only | Rows (not unique lines; duplicates across extracted “names”) | 151 |
| Same, `server.py` unique line numbers | Distinct `line` values | 128 |

**Conclusion:** Treat **crosswalk row counts as an upper bound on “lines touched by the tagger,”** not as “213 distinct DTE bugs.” The slice-plan instance count and the crosswalk row count measure different layers.

---

## 2. Key finding — tagger false-positive dominance

Spot checks of `CLASSIFIED.csv` show `DATE_DIFF_DTE` attached to lines whose **code** is only:

- Function parameters or variables named **`expiry`**, or  
- Comments / UI strings containing **“0DTE”** or **“DTE”** in prose, or  
- **Unrelated** identifiers that substring-match heuristics (e.g. lines that mention expiry scope but perform **no** calendar subtraction).

**Example:** `server.py:2405` is tagged `DATE_DIFF_DTE` with code snippet `def _resolve_l2_cache_entry_for_l1(ticker: str, expiry: Optional[str])` — **naming only**, not DTE derivation.

**Implication:** Sub-triage priority is **not** “edit 100+ server lines”; it is **(A)** confirm no remaining **true** calendar-DTE substitutions on hot paths, **(B)** tighten the **working-crosswalk generator** so `DATE_DIFF_DTE` fires only on real date arithmetic (future tooling batch).

---

## 3. Bucket definitions

### Bucket A — **CLOSED / superseded by S001 (runtime Schwab DTE)**

**Intent:** Any **market-data** “days to expiration” exposed to trading/analytics should use Schwab **`daysToExpiration`** (and related chain fields), not `(expiry_date - today).days`.

**Evidence on `main` (representative):**

- `server.py::_selected_schwab_days_to_expiration` — reads `ct.get("daysToExpiration")` (`2029-2068`).
- `market_state.py::_schwab_days_to_expiration_for_contract` — same primitive (`820-840`).
- `v2_decision/a2_option_expression.py` — `_spread_from_bid_ask` / scoring paths use `_num(chain_row.get("daysToExpiration"))` (`532`, `546`).
- Snapshot persistence path documents Schwab-native DTE (`server.py` ~3839-3846 region, `_selected_schwab_days_to_expiration`).

**Disposition:** **S013-A → follow S001 + committed helpers;** no second parallel “S013 code sweep” unless a **new** `(date − date).days` DTE appears in review.

### Bucket B — **NOT_APPLICABLE — offline audit / QA**

**Files:** `audit_expiry_data.py`, parts of `live_vs_replay_validation.py`, similar.

**Why:** These compare **stored** snapshot columns (`expiry`, `dte`, timestamps) for data-quality reports. They do not substitute Schwab chain primitives in the live quote/chain ingest path.

**Disposition:** Exclude from `REPLACE_WITH_SCHWAB` remediation; optional **governance note only** if a row still appears in residuals.

### Bucket C — **NOT_APPLICABLE / CANONICAL — tests**

**Files:** `tests/test_v2_a2_option_expression.py`, `tests/test_schwab_days_to_expiration_contract.py`, etc.

**Why:** Assert Schwab field usage or negative cases (missing `daysToExpiration`).

**Disposition:** No production change; classifier should eventually **exclude** or **down-rank** `tests/` for S013 mechanical noise (policy already prefers tests as non-runtime in other tracks).

### Bucket D — **CANONICAL — BS/charm time scaling (not “replace DTE integer”)**

**Site:** `math_exposure_core.py::compute_net_charm` — `_resolve_T(dte_raw)` uses Schwab `daysToExpiration`; for `dte_raw <= 0` uses **remaining session hours** heuristic for `T` (`350-360`), not a second integer DTE derived from calendar subtraction.

**Disposition:** **Out of S013 REPLACE scope**; charm/theta/BSP math is **S008 / S016** territory. Do not “fix” here as date-diff DTE.

### Bucket E — **TOOLING / hygiene — tighten `DATE_DIFF_DTE` tagging**

**Action:** Update the script that emits `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv` (or post-filter in classifier) so `DATE_DIFF_DTE` requires evidence such as:

- `.days` on a `timedelta` built from expiry-related dates, or  
- Explicit `(date_a - date_b).days` where operands tie to **expirationDate** / snapshot expiry, or  
- Deprecated patterns documented in S001 closure notes.

**Outcome:** Manual residual count and operator review time drop without changing runtime behavior.

---

## 4. Recommended commit / batch sequence (after this doc)

1. **Batch / tooling:** Implement Bucket **E** (tagger tighten) + re-run classifier; expect large **drop in S013-tagged rows** with little or no code churn.  
2. **Residual batch 4:** Target any **remaining** true positives (if any) after re-tag.  
3. **Optional:** Per-file grep for `.days` + `expir` on `main` after tagger update — should be near-zero outside audits and non-DTE date math (`ingest` windowing, etc.).

---

## 5. CSV-first declaration (sub-triage scope)

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.daysToExpiration; chains.putExpDateMap.*.daysToExpiration
Derived-field disposition for true positives: REPLACE_WITH_SCHWAB (already driven by S001 on hot paths)
All consumers checked: no — mechanical list was inflated; consumer list reset after Bucket E retag
```

---

**SYSTEM STATUS:** Unchanged (FAIL). This document defines **how** S013 collapses; it does not claim slice closure.
