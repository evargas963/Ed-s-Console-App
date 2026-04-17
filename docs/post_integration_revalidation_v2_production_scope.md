# Post-Integration Revalidation v2 — Production Scope

**Date:** 2026-04-11  
**Scope:** Validators only on the authoritative production database (no harness accumulation, no dataset rebuild).

---

## 1. Executive result

Validators **run successfully** against `data/ed_console.db`. **`calibration.validate_outcome_join`** reports `binary_pass: true` but the **trusted** population has **no rows with `outcome_5c` attached** (`rows_with_outcomes: 0`, `rows_pending_outcomes: 1`, reason **`snapshot_outcomes_not_filled`**). Join verification against snapshots is therefore **vacuous** (nothing to verify), and **`binary_pass_strict_production`** is **false** when that gate is evaluated.

**FINAL RESULT: FAIL** — post-integration outcome join is **not proven** on the real production calibration slice.

---

## 2. Authoritative production DB scope

| Role | Path | Reason |
|------|------|--------|
| **Authoritative production** | `data/ed_console.db` | `calibration.paths.DEFAULT_DB` — live app / writer default. |
| **Not authoritative for this proof** | `data/calibration_accumulation_validation.db` | Isolated harness DB (out of scope per request). |

**Relevant tables:** `calibration_decision_log`, `snapshots`, `price_bars_1m` (validators).

---

## 3. Exact DB path used

`c:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db`

---

## 4. Commands / validators run

```text
python -m calibration.validate_outcome_join --db data/ed_console.db
python -m calibration.anchor_audit --db data/ed_console.db --sample 5000
python -m calibration.audit_phase1 --db data/ed_console.db
```

**Artifact:** `models/calibration_runs/phase1_audit_1775958132.json`

**Validator changes:** None — all three accepted `--db data/ed_console.db` as-is.

---

## 5. Production row counts and coverage summary

| Metric | Value |
|--------|--------|
| `calibration_decision_log` rows | 43 |
| Trusted | 1 |
| Legacy | 42 |
| Distinct tickers (calibration) | SPY only |
| `decision_ts_utc` min | 1775874066.762656 |
| `decision_ts_utc` max | 1775926978.9349923 |

---

## 6. Leakage audit result (production scope)

Not re-executed in this pass (per instructions: validators only). No code-path proof delta from this run.

---

## 7. Join result (`validate_outcome_join`)

| Field | Value |
|--------|--------|
| `ambiguous_exact_ts_duplicate_snapshots` | 0 |
| `verification_pass` / `verification_fail` | 0 / 0 |
| `rows_with_outcomes` (trusted) | **0** |
| `rows_pending_outcomes` (trusted) | **1** |
| `pending_reasons_exact_tol0` | `snapshot_outcomes_not_filled`: 1 |
| `binary_pass` | **true** (structural checks only; no outcome rows to verify) |
| `binary_pass_strict_production` | **false** |

---

## 8. Anchor result (`anchor_audit --sample 5000`)

| Field | Value |
|--------|--------|
| `binary_pass` | **true** |
| `statistical_integrity.binary_pass` | **true** |
| Snapshot sample | 5000 random 1m rows |
| `calibration_trusted_anchor_audit` | 1 trusted row, 1 with anchor, 0 without |

---

## 9. Statistical integrity (`audit_phase1`)

| Field | Value |
|--------|--------|
| `statistical_integrity.binary_pass` | **true** |
| `timeframe_enforcement.violations_count` | 103109 non-canonical `5m` snapshot rows (reported; canonical enforcement for calibration remains 1m-only elsewhere) |

---

## 10. Exact files changed

**None** (this pass was validation-only).

---

## 11. Exact failures found

1. **Trusted outcome join incomplete:** one trusted `calibration_decision_log` row remains pending because the matched snapshot does not have `outcome_5c` filled (`snapshot_outcomes_not_filled`), so backfill cannot attach outcomes and there is **no** row on which to run snapshot-vs-calibration verification.

2. **Strict production gate:** `binary_pass_strict_production` is **false** (`rows_pending_outcomes` ≠ 0).

---

## 12. Exact fixes applied

**None** in this session (data/bar grid issue is not safely “fixed” by code-only changes without new bars or a contract change).

---

## 13. Remaining issues

1. **Blocker:** Complete bar-anchor outcome labeling for the trusted snapshot (or otherwise resolve `outcome_5c` NULL on the join target) so trusted rows can receive outcomes and join verification is non-vacuous.

2. **Low N:** One trusted row cannot support population-level empirical gates (e.g. anchor fraction gates with `min_required: 30` remain `insufficient_sample` by design).

---

## 14. FINAL RESULT: **FAIL**

Production DB validators ran, but **outcome join integrity for the trusted calibration path is not proven** because the sole trusted row is still pending with `snapshot_outcomes_not_filled`.
