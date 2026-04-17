# Calibration legacy quarantine — complete proof package (v2)

Independent audit checklist: criteria, counts, every reader, no-mixing proof, validation commands.

---

## A. Exact files changed (implementation + this proof)

| File | Role |
|------|------|
| `calibration/trust.py` | `CALIBRATION_TRUST_LEGACY`, `CALIBRATION_TRUST_TRUSTED`, `TRUSTED_PREDICATE_SQL` |
| `calibration/schema.py` | Column `calibration_trust`, migrations, partial index `idx_calib_outcome_pending` (trusted pending only) |
| `calibration/writer.py` | Production `INSERT` sets `calibration_trust = 'trusted'` |
| `calibration/backfill_outcomes.py` | Pending attach + resync: `calibration_trust = 'trusted'` only |
| `calibration/validate_outcome_join.py` | Default `trusted_only=True`; CLI `--include-legacy` |
| `calibration/analyze_phase3.py` | Study rows: `TRUSTED_PREDICATE_SQL`; provenance `legacy_rows_excluded_from_study_dataset` |
| `calibration/analyze_phase4.py` | Same as phase 3 |
| `calibration/anchor_audit.py` | Anchor gate: trusted rows only; legacy counts separate |
| `calibration/payload_audit.py` | Study metrics (dups, sample, snapshot match): trusted only; totals split |
| `calibration/validate_logging.py` | Prints total + trusted + legacy counts |
| `calibration/legacy_report.py` | CLI: full trust + legacy subcategory counts |
| `snapshot_sql/registry_full_a.json` | `validate_outcome_join.py:89` trusted keys; `89_include_legacy`; `payload_audit.py:101` trusted filter |
| `tests/test_calibration_legacy_quarantine.py` | Quarantine behavior proofs |
| `tests/test_calibration_outcome_join_scale.py` | Inserts `calibration_trust='trusted'` |
| `tests/test_calibration_logging_production_path.py` | Asserts `calibration_trust == 'trusted'` on writer path |
| `docs/calibration_legacy_quarantine_v2.md` | This document |

---

## B. Exact legacy vs trusted criteria

### B.1 Authoritative stored flag

| Value | Meaning |
|-------|---------|
| `calibration_trust = 'trusted'` | Row inserted by **`calibration.writer.append_calibration_decision`** with explicit `calibration_trust = 'trusted'`. This is the **only** supported production insert path for new study-eligible rows. |
| `calibration_trust = 'legacy'` | **Default** for: (1) any row present before the `calibration_trust` column was added (`ALTER TABLE ... DEFAULT 'legacy'`), (2) any manual/test `INSERT` that omits `calibration_trust` (defaults to legacy in DDL), (3) any insert not going through the writer. **Excluded from empirical study datasets by default.** |

### B.2 Mapping to historical milestones (trust boundary, not per-row inference)

The system does **not** recompute “was this row pre-timestamp-fix?” from data alone. Instead, the **trust column** defines the boundary:

| Milestone | How it is covered |
|-----------|-------------------|
| **Pre-authoritative `decision_ts_utc` / refresh alignment** | Rows from before the logging fix that are still in the DB received `calibration_trust = 'legacy'` at migration unless later replaced by a trusted insert (same key → idempotent skip). |
| **Pre-uniqueness / pre-idempotency** | Legacy duplicates were deduped in schema migration; surviving rows are still **`legacy`** unless rewritten by a trusted insert. Unique index is on `(ticker, decision_ts_utc)`; trust is independent. |
| **Pre-corrected join / resync regime** | Old partial attaches or drift are not trusted for studies; such rows remain **`legacy`** until superseded. **Backfill and resync only run on `trusted` rows**, so legacy rows are not “healed” into the study path silently. |
| **Other row-level correctness** | Anything not inserted via the current writer is **`legacy`** by definition. |

### B.3 Legacy subcategories (informational only; all quarantined)

Computed in `calibration/legacy_report.py` for **legacy** rows only:

- `legacy_pending_outcomes` — `outcome_5c IS NULL`
- `legacy_labeled_join_metadata_complete` — `outcome_5c` set and `matched_snapshot_ts_utc` and `outcome_join_method` both non-NULL
- `legacy_labeled_join_metadata_incomplete` — `outcome_5c` set but incomplete join metadata

Sum of the three equals `legacy_rows` when `legacy_subcategory_sum_equals_legacy_rows` is true.

---

## C. Exact counts table

### C.1 Definitions (any database)

| Metric | Definition |
|--------|------------|
| Total rows | `COUNT(*)` from `calibration_decision_log` |
| Trusted rows | `WHERE calibration_trust = 'trusted'` |
| Legacy rows | `WHERE calibration_trust = 'legacy'` |
| Legacy subcategories | As in §B.3 (`python -m calibration.legacy_report`) |
| Trusted rows **included in phase 3/4 study dataset** | `provenance.labeled_sample_count` — trusted rows with `outcome_5c`, canonical `1m`, **and** BAR_ANCHOR_V1 at `decision_ts_utc` |
| Legacy rows **excluded from study dataset** | `provenance.excluded_by_reason.legacy_rows_excluded_from_study_dataset` (phase 3/4); equals count of legacy rows with `canonical_timeframe = '1m'` |

### C.2 Reference fixture (deterministic composition, captured 2026-04-09)

A temporary SQLite DB was built with **6** rows: **3 legacy**, **3 trusted** (mixed pending / outcomes / join metadata). Commands: `calibration.legacy_report.analyze(db_path)` and `calibration.analyze_phase3.analyze(db_path)`.

| Metric | Value |
|--------|------:|
| total_rows | 6 |
| trusted_rows | 3 |
| legacy_rows | 3 |
| trusted_pending_outcomes | 2 |
| trusted_with_outcomes | 1 |
| legacy_pending_outcomes | 1 |
| legacy_labeled_join_metadata_complete | 1 |
| legacy_labeled_join_metadata_incomplete | 1 |
| legacy_subcategory_sum_equals_legacy_rows | true |
| phase3 labeled_sample_count (trusted, after anchor filter) | 0 |
| phase3 legacy_rows_excluded_from_study_dataset | 3 |
| phase3 rows_without_outcome_5c (trusted pending) | 2 |
| phase3 rows_without_bar_anchor_BAR_ANCHOR_V1 (trusted with outcome, no bars) | 1 |

**Production:** run `python -m calibration.legacy_report --db <your.db>` for live counts; run `python -m calibration.analyze_phase3` (or import `analyze`) for study `labeled_sample_count` and exclusions.

---

## D. Full workflow inventory (every `calibration_decision_log` reader)

| # | File | Function / entry | Reads table? | Trusted-only for study / attach? | Exact predicate / notes |
|---|------|------------------|--------------|-----------------------------------|---------------------------|
| 1 | `calibration/writer.py` | `append_calibration_decision` | INSERT | N/A (writes **`trusted`**) | `calibration_trust` column in INSERT = `'trusted'` |
| 2 | `calibration/backfill_outcomes.py` | `backfill` | SELECT pending | **Yes** | `WHERE outcome_5c IS NULL AND calibration_trust = 'trusted'` |
| 3 | `calibration/backfill_outcomes.py` | `_resync_existing_outcomes_from_snapshots` | SELECT | **Yes** | `WHERE outcome_5c IS NOT NULL AND calibration_trust = 'trusted'` |
| 4 | `calibration/validate_outcome_join.py` | `analyze(..., trusted_only=True)` | SELECT/COUNT | **Default yes** | `tc` / `cc`: `calibration_trust = 'trusted'`; totals also use `calibration_trust IN ('trusted','legacy')` for breakdown |
| 5 | `calibration/validate_outcome_join.py` | `main` / `--include-legacy` | same | **Opt-in no** | `trusted_only=not args.include_legacy` |
| 6 | `calibration/analyze_phase3.py` | `analyze` | SELECT | **Yes** for study rows | `TRUSTED_PREDICATE_SQL` on rows with outcomes; `n_legacy` = `NOT (TRUSTED_PREDICATE_SQL)` |
| 7 | `calibration/analyze_phase3.py` | `_snapshot_fallback` | snapshots only | N/A | Does not read `calibration_decision_log` |
| 8 | `calibration/analyze_phase4.py` | `analyze` | SELECT | **Yes** | Same pattern as phase 3 |
| 9 | `calibration/payload_audit.py` | `main` | SELECT | **Yes** for study metrics | `TRUSTED_PREDICATE_SQL` on dups, sample, delta loop; `total_rows` / `legacy_rows_quarantined` report full split |
| 10 | `calibration/anchor_audit.py` | `run_anchor_audit` (calibration block) | SELECT | **Yes** for gate | Trusted: `calibration_trust = 'trusted'`; legacy counted separately |
| 11 | `calibration/validate_logging.py` | `main` | COUNT | **Reporting** | Three counts: all / trusted / legacy (not a combined study metric) |
| 12 | `calibration/legacy_report.py` | `analyze` | COUNT/SELECT | **Reporting** | Full enumeration by design (audit tool) |
| 13 | `calibration/canonical_enforcement.py` | `enforce_calibration_decision_log_only_1m` | COUNT | **No** (safety gate) | All rows: NULL or `!= '1m'` → fail; not a study aggregation |
| 14 | `calibration/canonical_enforcement.py` | `run_binary_gate` / provenance | calls enforce | **No** | Gate on canonical timeframe only |
| 15 | `calibration/schema.py` | `_migrate_calibration_unique_ticker_decision_ts` | DELETE/SELECT | **No** | Maintenance migration |
| 16 | `calibration/audit_phase1.py` | (table presence) | **No row reads** | N/A | `calibration_decision_log` existence only |
| 17 | `calibration/validate_logging_e2e.py` | `main` | COUNT | **No** | Before/after total row count for E2E parity |
| 18 | `tests/test_calibration_*.py` | various | SELECT/INSERT | Mixed | Test-only |
| 19 | `signals.py` | (calibration hook) | via writer | N/A | Only `append_calibration_decision` |

**Registry SQL** (see `snapshot_sql/registry_full_a.json`):

- `calibration/validate_outcome_join.py:89` — DISTINCT `(ticker, decision_ts_utc)` from **`calibration_decision_log WHERE calibration_trust = 'trusted'`** (ambiguity check for trusted keys).
- `calibration/validate_outcome_join.py:89_include_legacy` — full table (use only with `--include-legacy`).
- `calibration/payload_audit.py:101` — `c.calibration_trust = 'trusted'` in EXISTS subquery.

---

## E. No-mixing proof

1. **Default trusted-only:** Phase 3, phase 4, default `validate_outcome_join.analyze()`, payload audit study metrics, anchor calibration gate, and backfill/resync all restrict to **`calibration_trust = 'trusted'`** (see §D).

2. **Legacy cannot silently enter study datasets:** Phase 3/4 build labeled samples only from `rows_raw` filtered by `TRUSTED_PREDICATE_SQL`. Legacy rows contribute only to **`legacy_rows_excluded_from_study_dataset`** in provenance.

3. **Explicit opt-in for legacy in join audit:** CLI `python -m calibration.validate_outcome_join --include-legacy` or `analyze(..., trusted_only=False)` — documented and intentional.

4. **No unintentional mix:** No single query aggregates “trusted + legacy” for phase 3/4 labeled statistics. Tools that show **totals** (`legacy_report`, `validate_logging`, `validate_outcome_join` total row counts) separate **breakdown** columns; they do not feed legacy rows into `labeled_sample_count`.

5. **Canonical enforcement** scans all rows for **1m violations only** — it does not add legacy rows into empirical buckets; it fails closed on bad timeframe.

---

## F. Validation commands / results

Commands executed for this proof package:

```bash
python -m pytest tests/test_calibration_legacy_quarantine.py tests/test_calibration_outcome_join_scale.py tests/test_calibration_logging_production_path.py -q
```

Result:

```text
11 passed
```

Additional verification (any DB path):

```bash
python -m calibration.legacy_report --db <path>
python -m calibration.validate_outcome_join --db <path>
python -m calibration.validate_logging --db <path>
```

---

## G. FINAL: **PASS**

| Gate | Status |
|------|--------|
| Criteria explicit | **PASS** (§B) |
| Counts explicit | **PASS** (§C; production via CLI) |
| Workflow inventory complete | **PASS** (§D) |
| No mixing by default | **PASS** (§E) |

**Remaining issues:** **NONE**
