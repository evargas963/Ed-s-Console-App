> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/repo_wide_canonical_enforcement_v1.md`.

# Repo-wide canonical snapshot timeframe enforcement (v1)

Hard gate: **no silent unscoped reads** of the multi-timeframe `snapshots` table for analytical or production metrics. Canonical live and calibration paths use **`timeframe_config.CANONICAL_TIMEFRAME`** (`'1m'`).

## A. Exact files changed

| File | Change |
|------|--------|
| `snapshot_access.py` | **New.** `require_snapshot_timeframe`, `SnapshotTimeframeRequiredError`, constants `SNAPSHOTS_TABLE` / `NORMALIZED_1M_TABLE`, docs on `snapshots_1m_normalized` contract. |
| `db.py` | `get_recent_snapshots`, `get_similar_setups`, `count_snapshots`, `compute_accuracy`: call `require_snapshot_timeframe`. `get_avg_move`: same + empty return if non-canonical (Issue 19 parity). `get_db_stats`: primary metrics **scoped to `timeframe='1m'`**; explicit audit keys for all-timeframe totals + `GROUP BY timeframe`. |
| `similarity_feature_search.py` | `diagnose_overlay_match_counts`: first stage fixed to ticker+timeframe+outcome (no unscoped count); `require_snapshot_timeframe` on diagnosis/overlay helpers; `analyze_baseline_feature_outcome_divergence` requires timeframe. |
| `audit_gate_labels.py` | All snapshot queries: `AND timeframe = ?` (`CANONICAL_TIMEFRAME`). |
| `audit_training_data.py` | All snapshot queries: canonical timeframe filter. |
| `backfill_snapshot_derived.py` | `WHERE timeframe IN ('1m','5m')` + `ORDER BY ticker, timeframe, ts_utc`. |
| `verify_snapshot_pipeline.py` | Latest-snapshot checks: `AND timeframe=?`. |
| `snapshot_normalizer.py` | `_print_ingestion_context`: total = **sum of `GROUP BY timeframe`** (no unscoped `COUNT(*)`). |
| `tools/_audit_distance_signs_db.py` | All `snapshots` metrics: `WHERE timeframe=?` (canonical). |
| `tools/_diag_pin_neutral_outcomes.py` | Rewritten: `timeframe IN (1m,5m)` for pin_neutral scope; canonical for pin_bull sample. |
| `tools/repair_validation_counts_v1.py` | Pin-neutral diagnostics: explicit `timeframe IN (?, ?)`; per-ticker labeled count includes `timeframe=?`. |
| `tools/phase2_forward_write_verify.py` | Post-cutoff / negative-distance stats: `timeframe='1m'`. |
| `tests/test_distance_option_a_backfill_v1.py` | SQL: add `timeframe` filter. |
| `tests/test_horizon_bar_outcomes.py` | SQL: add `timeframe` filter. |
| `tests/test_issue16_normalized_training_sync.py` | SQL: add `timeframe='1m'`. |
| `tests/test_similarity_feature_survivorship.py` | Stage index after diagnosis pipeline trim. |
| `docs/repo_wide_canonical_enforcement_v1.md` | This document. |

## B. Full list of snapshot access paths (inventory)

**Production / library**

| Location | Mechanism | Timeframe |
|----------|-----------|-----------|
| `db.EdDB.get_recent_snapshots` | SQL `WHERE ticker=? AND timeframe=?` | Enforced via `require_snapshot_timeframe` |
| `db.EdDB.get_similar_setups` | Tiers 1–5: `timeframe=?` | Required + canonical-only policy |
| `db.EdDB.get_avg_move` | SQL `timeframe=?` | Required + canonical-only empty return |
| `db.EdDB.count_snapshots` | SQL | Required |
| `db.EdDB.compute_accuracy` | SQL | Required |
| `db.EdDB.fill_outcomes` / pin_neutral backfill | SQL | `timeframe` bound |
| `db.EdDB.get_db_stats` | Primary counts | **`WHERE timeframe='1m'`**; audit: `total_snapshots_all_timeframes_audit`, `snapshots_by_timeframe_audit` |
| `db._already_filled` / outcome updates | `snapshot_id` PK | Single-row; no mixed TF |
| `prediction_engine` / `signals` | Via `get_similar_setups` / `count_snapshots` | Callers pass `inp.timeframe` |
| `ml_data_common.py` | SQL | `ticker` + `timeframe` |
| `snapshot_normalizer.py` | Fetch raw | `WHERE ticker=? AND timeframe=?` or `IN (1m,5m)` for ticker list |
| `normalized_training_sync.py` | Fingerprint | `WHERE timeframe IN (?, ?)` |
| `training_cache.py` / `ml_train.py` | `snapshots_1m_normalized` | `where` built with ticker (+ implied 1m table) |
| `server.py` debug zone counts | SQL | `ticker` + `CANONICAL_TIMEFRAME` (already present) |
| `calibration/*` | Phase 3/4, audits, `payload_audit`, `validate_outcome_join`, `backfill_outcomes` | `'1m'` or `?` bound |
| `verification/similar_set_trace.py` | Tier SQL | `timeframe=?` throughout |

**Training table `snapshots_1m_normalized`**

- By design **1m-only** (see `timeframe_config.SNAPSHOT_TABLE_1M`). Reads do not mix 5m legacy rows; materialization selects source `snapshots` rows by explicit timeframe.

**Audits intentionally multi-timeframe**

- Queries that **`GROUP BY timeframe`** (e.g. `audit_snapshot_data` summary, `pin_neutral_any_schema`, `get_db_stats` audit map) are **labeled** as distribution audits, not a single mixed aggregate without breakdown.

**Diagnostics / CLI**

- `tools/pin_neutral_1m_5m_divergence_audit_v1.py`: `bar_anchor_scope_sql()` includes **`timeframe = ?`** per inventory call.
- `issue19_rehydration_range_v1.py`, `bar_history_recovery_audit_v1.py`: `timeframe IN (1m,5m)` where applicable.

## C. Classification

| Category | Meaning |
|----------|---------|
| **SAFE** | `WHERE timeframe = ?` (bound), or `snapshot_id` PK, or `snapshots_1m_normalized` (1m table contract), or explicit `GROUP BY timeframe` audit. |
| **UNSAFE** | `FROM snapshots` with no timeframe and no PK — **removed or rewritten** in this pass. |
| **UNKNOWN** | None remaining for production paths after re-audit. |

## D. Exact fixes applied

1. **`snapshot_access.require_snapshot_timeframe`** — raises if `timeframe` is missing/blank for API paths that build SQL.
2. **`db.get_db_stats`** — replaced unscoped `COUNT(*)` / `MIN(ts_et)` / `DISTINCT ticker` with **canonical-scoped** queries; added **`total_snapshots_all_timeframes_audit`** and **`snapshots_by_timeframe_audit`** for operators.
3. **`get_avg_move`** — non-canonical timeframe returns empty stats with `reject_reason` (aligned with Issue 19 similarity).
4. **Audit scripts** (`audit_gate_labels`, `audit_training_data`, `_diag_pin_neutral_outcomes`, `_audit_distance_signs_db`, `repair_validation_counts_v1`, `backfill_snapshot_derived`, `verify_snapshot_pipeline`, `phase2_forward_write_verify`) — explicit timeframe filters.
5. **`similarity_feature_search.diagnose_overlay_match_counts`** — removed unscoped “ticker-only” pool count; stages renamed; `require_snapshot_timeframe` on entry.
6. **`snapshot_normalizer._print_ingestion_context`** — total row count derived from **`GROUP BY timeframe`** sum, not `SELECT COUNT(*) FROM snapshots` alone.
7. **Tests** — SQL updated to include `timeframe` where assertions touch `snapshots`.

## E. Enforcement mechanism added

- **Module:** `snapshot_access.py`
  - `require_snapshot_timeframe(timeframe, caller=...)` → non-empty string or **`SnapshotTimeframeRequiredError`**
  - Documents **`NORMALIZED_1M_TABLE`** vs raw **`snapshots`**
- **DB layer:** `EdDB` methods that accept `timeframe: str` validate before opening connections where applicable.
- **Canonical constant:** `timeframe_config.CANONICAL_TIMEFRAME` (single source; also referenced in `snapshot_access` docs).

## F. Remaining exceptions (justified)

| Item | Justification |
|------|----------------|
| `SELECT COUNT(*) FROM snapshots` inside `get_db_stats` | **Audit only:** `total_snapshots_all_timeframes_audit` — explicit key name; not used as canonical metric. |
| `GROUP BY timeframe` distribution queries | **Audit:** shows composition; does not present a single misleading “total” without breakdown. |
| `MAX(snapshot_id) FROM snapshots` in tests/tools | Global ID sequence; not used for mixed-timeframe analytics. |
| PK lookups `WHERE snapshot_id = ?` | Single row; timeframe is a column on that row. |

## G. FINAL: PASS or FAIL (binary)

**PASS** — Unscoped analytical reads on `snapshots` have been eliminated or replaced with explicit timeframe filters, canonical-scoped aggregates, or documented audit-only totals. Enforcement is centralized in `snapshot_access` and `EdDB` for parameterized APIs.
