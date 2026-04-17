# Calibration statistical integrity — full-path proof (v2)

**Scope:** Every analysis / empirical / calibration output path that can emit metrics, thresholds, rankings, baselines, recommendations, or comparative statistics from calibration data.

**Floor:** `math_probabilities.MIN_SAMPLES_STATISTICAL` (30), surfaced via `calibration.statistical_integrity` (`bucket_gate`, `gated_mean`, `gated_ratio`).

**Date:** 2026-04-11

---

## A. Exact files changed (this closure)

| File | Change |
|------|--------|
| `calibration/audit_phase1.py` | Aligned Phase 1 JSON with `verify_audit_phase1_no_numeric_leak`: gated gap distributions (`distribution_sample_gate`), snapshot↔bar alignment fraction (`fraction_missing_anchor_gate`), outcome null rates (`null_rates_sample_gate`), structural null rates (`structural_null_rates_sample_gate`); appended `statistical_integrity` block. |
| `docs/calibration_statistical_integrity_v2.md` | This document. |

**Supporting modules (verified; no edits required for this closure):** `calibration/statistical_integrity.py`, `calibration/analyze_phase3.py`, `calibration/analyze_phase4.py`, `calibration/payload_audit.py`, `calibration/anchor_audit.py`.

---

## B. Full analysis-path inventory

| # | Path | Module / entry | Primary outputs | Role |
|---|------|----------------|-----------------|------|
| 1 | Phase 3 study | `python -m calibration.analyze_phase3` | Reliability, regime buckets, threshold grid, Brier, snapshot fallback buckets, etc. | Empirical calibration analysis |
| 2 | Phase 4 study | `python -m calibration.analyze_phase4` | Decision performance, MHAP alignment, snapshot baselines, log vs baseline comparison | Empirical calibration analysis |
| 3 | Payload / snapshot join audit | `python -m calibration.payload_audit` | Duplicate stats, fusion key checks, `snapshot_exact_ts_match_rate`, nearest-Δ distribution | Data-quality reporting over trusted rows |
| 4 | Anchor feasibility (BAR_ANCHOR_V1) | `python -m calibration.anchor_audit` | Miss rates, buckets, calibration trusted fraction without anchor | Empirical audit (trusted scope) |
| 5 | Phase 1 data integrity | `python -m calibration.audit_phase1` | Gap continuity, alignment sample fraction, label null rates, structural null rates | Infrastructure / integrity reporting |
| 6 | Legacy vs trusted inventory | `python -m calibration.legacy_report` | Row counts by trust / subcategory | **Non-empirical** enumeration (counts only; no inferential rates) |
| 7 | Outcome join verification | `python -m calibration.validate_outcome_join` | Per-row verify tallies, ambiguity counts, pending reason histograms | **Integrity reconciliation** (deterministic checks; not pooled estimators) |
| 8 | Schema / logging smoke | `python -m calibration.validate_logging` | Row counts, trust split | Non-empirical |
| 9 | E2E logging smoke | `python -m calibration.validate_logging_e2e` | Row count after controlled insert | Non-empirical |
| 10 | Proof dataset builder | `python -m calibration.build_trusted_anchor_proof_dataset` | Invokes phase 3/4 + anchor audit | Wrapper; inherits downstream gates |
| 11 | Backfill / writer / schema | `calibration/backfill_outcomes.py`, `calibration/writer.py`, `calibration/schema.py` | DB mutations or DDL | **Not** metric emitters for study conclusions |
| 12 | Canonical enforcement | `calibration/canonical_enforcement.py` | Fail-closed structural rules | Preconditions; not empirical metrics |

---

## C. Gate status per path

| Path | Min *n* / rule | Insufficient buckets fail-closed | No numeric leak when *n* low | Labeled *n* / exclusions |
|------|----------------|-----------------------------------|------------------------------|---------------------------|
| Phase 3 | `MIN_SAMPLES_STATISTICAL` per bucket (see `thresholds_dict()`) | Yes — means/rates `None` + `sample_gate` | `verify_phase3_no_numeric_leak` | `sample_gate.n`, trusted-only notes in analyzer |
| Phase 4 | Same floor for signals, MHAP, baselines, comparison | Yes | `verify_phase4_no_numeric_leak`; baseline `delta` only if `status=="ok"` | Gates on each series |
| Payload audit | `n_trusted` for match **rate**; `n_compared` for Δ distribution | Yes — rates/summaries `None` | `verify_payload_audit_no_numeric_leak` | `trusted_rows`, `legacy_rows_quarantined`, `sample_size` (JSON row sample) |
| Anchor audit | `MIN_SAMPLES_STATISTICAL` for all `*_rate` / fraction fields | Yes | `verify_anchor_audit_no_numeric_leak` | Trusted vs legacy counts; sampling metadata in output |
| Phase 1 audit | Gaps: per-ticker `len(gaps)`; alignment: random sample `checked`; labels/structure: snapshot row `n` | Yes — gated fields `None` | `verify_audit_phase1_no_numeric_leak` | `row_count_1m`, `random_sample_size`, RTH notes |
| Legacy report | N/A (integer counts) | N/A | No pooled proportions emitted | Explicit trust criteria in JSON |
| Outcome join | N/A for pooled rates | N/A | No calibration estimators; integer tallies | `study_trusted_only` flag |
| validate_logging / e2e | N/A | N/A | Counts only | N/A |
| Proof dataset builder | Delegates to gated tools | Inherits | Inherits | Inherits |

---

## D. Fixes applied (gap closure)

1. **Phase 1 (`audit_phase1.py`)** previously emitted **ungated** gap medians/p95/max, alignment **fraction**, outcome **null rates**, and structural **null rates** while `verify_audit_phase1_no_numeric_leak` already defined the safe contract. The implementation now **withholds** those numeric fields unless the paired `bucket_gate` reports `sufficient_sample`, and attaches `statistical_integrity.binary_pass` from the verifier.

2. **Phase 3 / 4 / payload / anchor** — already implemented gated means/rates, defensive verifiers, and `statistical_integrity` metadata; **baseline comparison delta** in phase 4 is guarded by `verify_phase4_no_numeric_leak` (no `delta` unless `status == "ok"`).

---

## E. Path counts

| Category | Count |
|----------|-------|
| Gated empirical / reporting with verifiers | **5** (phase 3, phase 4, payload audit, anchor audit, phase 1) |
| Explicitly non-empirical (counts / integrity only) | **4** (legacy report, outcome join, validate_logging, validate_logging_e2e) |
| Non-metric infrastructure / wrappers | **3** (proof builder, backfill/writer/schema, canonical enforcement) |
| **Ungated empirical paths** | **0** |
| **Quarantined (blocked) empirical paths** | **0** (all empirical paths either gated or not applicable) |

---

## F. FINAL: **PASS**

**Criteria:**

- All relevant analysis paths are either **properly gated** (phase 1–4, payload, anchor) or **explicitly non-empirical / reporting-only** (legacy, join verify, logging smoke).
- **Ungated empirical paths = 0**
- **Numeric leakage on insufficient sample = 0** (enforced by construction + defensive `verify_*_no_numeric_leak` functions on gated emitters)

---

## Validation commands used

```text
python -m pytest tests -q -k "calibration or statistical" --ignore=tests/test_playwright_must_run.py
```

Result: **28 passed** (2026-04-11).

```text
python -c "from calibration.audit_phase1 import run_audit; from pathlib import Path; from calibration.paths import DEFAULT_DB; from calibration.statistical_integrity import verify_audit_phase1_no_numeric_leak; p=Path(DEFAULT_DB); d=run_audit(p); assert d['statistical_integrity']['binary_pass'] and verify_audit_phase1_no_numeric_leak(d)"
```

Result: **exit 0** (real DB smoke; ~108s on representative workspace).

Full suite: `python -m pytest tests -q` — **713 passed**, **1 failed** (`tests/test_playwright_must_run.py::test_playwright_marker_newer_than_e2e_sources` — Playwright marker staleness; **unrelated** to calibration statistics).

---

## Remaining issues

**NONE** (for statistical integrity scope as defined above).
