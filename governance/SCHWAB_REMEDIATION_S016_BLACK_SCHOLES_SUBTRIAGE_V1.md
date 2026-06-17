> **Classification:** Policy Specification | **Scope:** Governance documentation `SCHWAB_REMEDIATION_S016_BLACK_SCHOLES_SUBTRIAGE_V1.md`.

# Schwab Remediation S016 — `BLACK_SCHOLES` Sub-Triage V1

**Status:** SUBTRIAGE_COMPLETE; **classifier tag-plausibility gate IMPLEMENTED** (2026-05-08)  
**Date:** 2026-05-08  
**Parent slice:** S016 `BLACK_SCHOLES` (Medium aggregate)  
**Related:** S008 `BLACK_SCHOLES` × `greeks` (HIGH — governed theta / BS fallback)

---

## 1. Count reconciliation (slice plan vs crosswalk)

| Source | What it counts | Approx. |
|--------|----------------|--------:|
| Slice plan S016 | Clustered **mechanical-scan instances** (pre-classifier) | 126 |
| `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_CLASSIFIED.csv` | **CSV rows** tagged `BLACK_SCHOLES`, excluding `.claude/worktrees/*` (before gate) | 249 |
| Same (after `_normalize_black_scholes_tag`) | Rows retaining `BLACK_SCHOLES` after classify | **20** |

**Conclusion:** Like S013, treat crosswalk row volume as **tagger-inflated**. The slice-plan instance count and per-row tags measure different layers.

---

## 2. Key finding — regex false-positive dominance

Spot checks show `BLACK_SCHOLES` attached to lines with **no** Black-Scholes naming or BS theta fallback, including:

- Unrelated identifiers (`d1` as a local variable in probability tuples, `delta` as a count delta, `abs_core` / `vol_n` arithmetic),
- ML / threshold code with no BS formula,
- Generic statistics (`norm.cdf` on z-scores).

**Implication:** Sub-triage priority is **not** a repo-wide “remove BS” sweep; it is **(A)** keep **S008** focus on the governed BS theta path (`v2_decision/a2_option_expression.py`), **(B)** strip mechanical noise via classifier **before** residual batches.

---

## 3. Classifier gate (shipped)

**Implementation:** `tools/classify_schwab_csv_crosswalk.py` — `_black_scholes_tag_plausible` / `_normalize_black_scholes_tag`, invoked from `classify()` after the S013 `DATE_DIFF_DTE` normalization.

**Keep `BLACK_SCHOLES` when the code line shows** (summary):

- `Black-Scholes` / `black_scholes` (hyphen/underscore-insensitive via alphanumeric blob), or `bs_approximation`, or `_bs_` in identifiers (e.g. `theta_bs_fallback`), or  
- `bs_theta` as a word, `_norm_cdf` (project BS helper), or  
- `norm.cdf` / `norm.pdf` **and** option-pricing-like context (`spot`+`strike`, or `d1`+`d2`, or black-scholes text).

**Strip** generic `norm.cdf(abs(z))` and all d1/delta noise rows.

`SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv` is unchanged.

---

## 4. Evidence (classifier re-run)

| Metric | Before S016 gate | After S016 gate |
|--------|------------------|-----------------|
| Manual residual rows (`CROSSWALK_RESIDUAL.csv`) | 171 | **167** |
| Residual rows tagged `BLACK_SCHOLES` | (mixed) | **1** (`a2_option_expression.py` gate string + `theta` primitive) |
| Classified rows (excl. `.claude/`) retaining `BLACK_SCHOLES` | 249 | **20** |

The remaining production-facing BS cluster aligns with **S008** (Schwab `theta` vs BS approximation), not broad ML files.

---

## 5. CSV-first declaration (sub-triage scope)

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.theta; chains.putExpDateMap.*.theta; chains.*.volatility (as BS inputs where applicable)
Derived-field disposition for true positives: REPLACE_WITH_SCHWAB_OR_GATE / S008 measurement discipline
All consumers checked: no — mechanical BLACK_SCHOLES list was inflated; classifier gate resets crosswalk signal
```

---

**SYSTEM STATUS:** Unchanged (FAIL). This document defines how S016 **collapses in the crosswalk**; it does not claim S008 closure.
