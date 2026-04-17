# Calibration legacy quarantine v1

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/trust.py` | **New:** `CALIBRATION_TRUST_LEGACY` / `CALIBRATION_TRUST_TRUSTED`, `TRUSTED_PREDICATE_SQL`. |
| `calibration/schema.py` | Column `calibration_trust TEXT NOT NULL DEFAULT 'legacy'`; migration `ALTER TABLE ... ADD COLUMN`; partial index `idx_calib_outcome_pending` on `(ticker) WHERE outcome_5c IS NULL AND calibration_trust = 'trusted'`. |
| `calibration/writer.py` | Production inserts set `calibration_trust = 'trusted'`. |
| `calibration/backfill_outcomes.py` | Pending attach + resync only `calibration_trust = 'trusted'`. |
| `calibration/validate_outcome_join.py` | Default study scope: trusted-only counts/verification/pending; `--include-legacy` for full-table audit; registry key for trusted ambiguity query. |
| `calibration/analyze_phase3.py` | Empirical dataset: `calibration_trust = 'trusted'`; provenance `legacy_rows_excluded_from_study_dataset`. |
| `calibration/analyze_phase4.py` | Same as phase 3. |
| `calibration/anchor_audit.py` | Anchor miss rate and `binary_pass` use **trusted rows only**; totals split `rows_trusted` / `rows_legacy_quarantined`. |
| `calibration/payload_audit.py` | Dup check, random sample, snapshot delta loop, exact-match count: **trusted only**; report `trusted_rows` / `legacy_rows_quarantined`. |
| `calibration/validate_logging.py` | Prints `trusted=` and `legacy=` counts. |
| `calibration/legacy_report.py` | **New:** CLI `python -m calibration.legacy_report` — counts by trust + legacy subcategories. |
| `snapshot_sql/registry_full_a.json` | `validate_outcome_join` ambiguity subquery restricted to trusted keys; `payload_audit.py:101` filters trusted; `89_include_legacy` for optional audit. |
| `tests/test_calibration_legacy_quarantine.py` | **New:** migration, phase3 exclusion, join analyzer scope. |
| `tests/test_calibration_outcome_join_scale.py` | Inserts use `calibration_trust='trusted'`. |
| `tests/test_calibration_logging_production_path.py` | Asserts production row `calibration_trust == 'trusted'`. |

## B. Exact legacy criteria

1. **Column (authoritative):** `calibration_trust`
   - **`trusted`** — Rows inserted via `calibration.writer.append_calibration_decision` after this quarantine (production path sets `calibration_trust = 'trusted'`).
   - **`legacy`** — Default for all rows created before the column existed, any manual SQL insert omitting trust, or any non-writer path. Treated as **not trustworthy for empirical calibration studies** regardless of apparent completeness.

2. **Informational subcategories (legacy rows only; all remain quarantined):**
   - **`legacy_pending_outcomes`** — `outcome_5c IS NULL`
   - **`legacy_labeled_join_metadata_complete`** — `outcome_5c` set and both `matched_snapshot_ts_utc` and `outcome_join_method` set (may still be legacy if inserted before writer trust)
   - **`legacy_labeled_join_metadata_incomplete`** — `outcome_5c` set but incomplete join metadata (typical of older partial attaches)

Row-level milestones (authoritative timestamp, uniqueness, outcome join/resync) are **not** re-inferred per row in SQL; **trust is explicit** so studies cannot silently depend on heuristics.

## C. Counts by category

Counts are **per-database**. After migration, a typical production DB has:

- **`legacy_rows`** = all pre-migration rows (until promoted — no auto-promotion in v1).
- **`trusted_rows`** = rows from production writer since quarantine.

Run:

```bash
python -m calibration.legacy_report --db <path>
```

Example categories in JSON: `trusted_rows`, `legacy_rows`, `legacy_pending_outcomes`, `legacy_labeled_join_metadata_complete`, `legacy_labeled_join_metadata_incomplete`, `legacy_subcategory_sum_equals_legacy_rows`.

## D. Quarantine mechanism

- **Hard column + default:** New rows from the **only** supported writer path are **`trusted`**. Everything else is **`legacy`** unless explicitly updated (operational promotion is out of scope for v1; use controlled `UPDATE` if ever needed).
- **Studies and tooling default to `calibration_trust = 'trusted'`** so legacy rows are not read for empirical metrics unless a tool explicitly opts into `--include-legacy` (validate_outcome_join only).

## E. Workflows updated

| Workflow | Behavior |
|----------|----------|
| `calibration.writer` | Sets `trusted` on insert. |
| `calibration.backfill_outcomes` | Pending + resync **trusted only**. |
| `calibration.validate_outcome_join` | Trusted-only by default; `--include-legacy` for full audit. |
| `calibration.analyze_phase3` / `analyze_phase4` | Labeled sample = trusted only; provenance lists legacy excluded count. |
| `calibration.anchor_audit` | Anchor gate on **trusted** rows; legacy reported separately. |
| `calibration.payload_audit` | Study metrics (dups, sample, snapshot match stats) = **trusted only**. |
| `calibration.validate_logging` | Prints trusted vs legacy row counts. |
| `calibration.legacy_report` | Full trust + legacy category breakdown. |

## F. Proof that no mixing remains

1. **Counted:** `legacy_report.analyze()` returns `trusted_rows`, `legacy_rows`, and legacy subcategories with `legacy_subcategory_sum_equals_legacy_rows == true` when categories partition legacy rows.

2. **Trusted-only study paths:** Phase 3/4 use `TRUSTED_PREDICATE_SQL` on all `calibration_decision_log` reads that feed labeled samples; provenance includes `legacy_rows_excluded_from_study_dataset`.

3. **No silent mixing:** There is no code path that aggregates legacy + trusted for phase 3/4, payload audit (study sections), anchor `binary_pass`, or default `validate_outcome_join`. Mixing requires explicitly passing `trusted_only=False` to `analyze()` or `--include-legacy` on the CLI (audit-only).

4. **Production inserts are trusted:** `tests/test_calibration_logging_production_path.py::test_decision_ts_utc_matches_refresh_ts_utc` asserts `calibration_trust == 'trusted'`.

5. **Tests:** `tests/test_calibration_legacy_quarantine.py` proves legacy-only labeled data does not enter phase 3 sample; join analyzer trusted vs full counts differ as expected.

## G. FINAL: **PASS**

| Gate | Result |
|------|--------|
| Legacy criteria explicit | **PASS** (`calibration_trust` + documented subcategories) |
| Legacy rows quarantined / excluded from studies | **PASS** (default trusted-only reads) |
| Mixed trusted/untrusted study reads impossible without explicit audit flag | **PASS** |

**Verification command (executed):**

```text
python -m pytest tests/test_calibration_legacy_quarantine.py tests/test_calibration_outcome_join_scale.py tests/test_calibration_logging_production_path.py -q
```

```text
11 passed
```
