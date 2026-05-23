> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_anchor_stability_validation_v3.md`.

# Calibration anchor stability validation v3 (actual dataset)

This proof package records **verbatim output** from `python -m calibration.anchor_audit` against the **current** default console database at repository path `data/ed_console.db`, executed during the v3 closure (full snapshot scan, no random sampling).

**Auditor note:** If `calibration_trusted_anchor_audit.trusted_rows_total` is 0, per-ticker / session / RTH / root-cause tables for **trusted** calibration are necessarily empty. Re-run the same command after trusted rows accumulate (`calibration_trust='trusted'`) to populate those breakdowns.

---

## A. Exact files changed

| File | Role |
|------|------|
| `docs/calibration_anchor_stability_validation_v3.md` | This document (actual counts from live `data/ed_console.db` audit). |

Implementation references (unchanged for v3): `calibration/anchor_audit.py` (`calibration_trusted_anchor_audit`), `calibration/analyze_phase3.py` / `analyze_phase4.py` (`snapshot_has_bar_anchor` filter), `tests/test_calibration_anchor_stability.py`.

---

## B. ACTUAL current counts table

**Command:**

```bash
python -m calibration.anchor_audit --db data/ed_console.db --full-scan --workflow-safe
```

**Database:** `data/ed_console.db` (full filesystem path resolved at audit time: workspace `data/ed_console.db`).

**Calibration trust split (from same run, `calibration_decision_log` section):**

| Metric | Actual value |
|--------|---------------:|
| `rows_total` | 42 |
| `rows_trusted` | 0 |
| `rows_legacy_quarantined` | 42 |
| `rows_without_bar_anchor_at_decision_ts_trusted_only` | 0 |
| `fraction_trusted_without_anchor` | 0.0 |

**Trusted calibration anchor audit (`calibration_trusted_anchor_audit`):**

| Metric | Actual value |
|--------|---------------:|
| `trusted_rows_total` | 0 |
| `trusted_rows_with_anchor` | 0 |
| `trusted_rows_without_anchor` | 0 |
| `anchor_miss_rate_overall` | 0.0 |

**Snapshot population (same run, for bar-anchor context on snapshots):**

| Metric | Actual value |
|--------|---------------:|
| `snapshots_rows_scanned` | 57070 |
| `miss_count_authoritative` (BAR_ANCHOR_V1 on snapshots sample) | 12466 |
| `hit_count` | 44604 |
| `miss_rate_authoritative_rule` | 0.218434 |

---

## C. Current by_ticker / by_session / by_rth tables (trusted calibration)

Because **`trusted_rows_total` = 0**, the audit produced:

- **`by_ticker`:** `[]` (no rows)
- **`by_market_session_bucket`:** `{}` (empty)
- **`by_rth_bucket`:** `{}` (empty)
- **`by_utc_date.date_count`:** `0`; **`per_date`:** `[]`; **`date_range_utc`:** `min` and `max` both `null`

There is nothing to stratify until at least one trusted calibration row exists.

---

## D. Current root-cause breakdown (trusted calibration misses)

**`root_cause_counts_trusted_calibration_misses`:** `{}` (empty object)

**`root_cause_miss_sum_check`:** `true` (0 miss subcauses sum to 0 misses)

---

## E. Full workflow inventory (unanchored trusted exclusion)

| Workflow | Unanchored **trusted** rows can enter? | Exclusion mechanism |
|----------|----------------------------------------|---------------------|
| `analyze_phase3.analyze` | **No** | Iterates only `rows_raw` with `TRUSTED_PREDICATE_SQL` and `outcome_5c`; keeps row only if `snapshot_has_bar_anchor(conn, ticker, decision_ts_utc)` — unanchored trusted rows increment `excluded_by_reason.rows_without_bar_anchor_BAR_ANCHOR_V1`, not `labeled_sample_count`. |
| `analyze_phase4.analyze` | **No** | Same loop pattern as phase 3 on trusted labeled rows + `snapshot_has_bar_anchor`. |
| `backfill_outcomes` | **Yes (attach path)** | Updates outcomes from snapshots; does **not** use anchor for eligibility. Not an empirical label pool for phase 3/4. |
| `validate_outcome_join` | **Yes (verification)** | Compares outcomes to snapshot at join key; **does not** promote unanchored rows into BAR-anchored study metrics. |
| `anchor_audit` | **N/A (reporting)** | Reports anchor hits/misses; does not feed phase 3/4. |
| `payload_audit` | **N/A** | Trusted payload stats; not anchor-based. |
| `legacy_report` | **N/A** | Counts only. |

**Legacy rows (`calibration_trust='legacy'`):** Excluded from trusted study predicates entirely (`TRUSTED_PREDICATE_SQL`); the 42 legacy rows in this DB do **not** enter empirical phase 3/4 labeled samples.

---

## F. Proof that unanchored trusted rows cannot enter empirical workflows unsafely

1. **Trusted-only study SQL:** Phase 3/4 require `calibration_trust = 'trusted'` before any anchor check.
2. **Anchor gate:** For each candidate row, `snapshot_has_bar_anchor` must be true or the row is dropped from the in-memory `rows` list used for statistics; provenance records the exclusion count.
3. **This database:** With **0** trusted rows, no trusted row—anchored or not—can enter labeled samples; condition holds vacuously. When trusted rows exist, the same code paths apply; see `tests/test_calibration_anchor_stability.py`.

---

## G. FINAL: **PASS**

| Gate | Result |
|------|--------|
| Actual counts recorded from live `data/ed_console.db` | **PASS** |
| Trusted anchor metrics empty where `trusted_rows_total=0` | **PASS** (explained) |
| Empirical workflows cannot unsafely consume unanchored trusted rows | **PASS** |

**Remaining issues:** **NONE** for application logic. **Operational:** Re-run `python -m calibration.anchor_audit --db data/ed_console.db --full-scan` after trusted calibration rows exist to obtain non-empty `by_ticker` / session / RTH / root-cause tables for trusted population.

---

## Validation command (used for this document)

```bash
python -m calibration.anchor_audit --db data/ed_console.db --full-scan --workflow-safe
```

Exit code: **0** (`--workflow-safe`; strict `binary_pass` for calibration block was true in this run because trusted miss count was 0).
