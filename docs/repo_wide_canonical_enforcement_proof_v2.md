> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/repo_wide_canonical_enforcement_proof_v2.md`.

# Repo-wide canonical enforcement — verification proof (v2)

**Date:** 2026-04-09  
**Source of truth for fixes:** violations listed in `repo_wide_canonical_enforcement_proof_v1.md` §D.

## Search re-run (post-fix)

```text
rg "FROM snapshots" --glob "*.py"
rg "FROM snapshots_1m_normalized" --glob "*.py"
rg "JOIN snapshots" --glob "*.py"
```

- **`FROM snapshots`:** **270** substring matches in **56** Python files (down from 271 / 57: one unscoped `COUNT(*)` removed from `db.py` by deriving the all-timeframe total from `GROUP BY timeframe`).
- **`JOIN snapshots`:** none in `*.py`.
- **`FROM snapshots_1m_normalized`:** unchanged inventory; training paths use `timeframe` in dynamic `WHERE` where applicable.

---

## A. Exact files changed

| File | Change |
|------|--------|
| `tests/test_issue16_normalized_outcome_materialize.py` | `SELECT` from `snapshots` adds `AND timeframe=?` / `CF`. |
| `tools/ontology_mismatch_evidence.py` | All `snapshots` queries scoped to `CANONICAL_TIMEFRAME`; section note for ontology audit. |
| `db_health_audit.py` | `snapshots_total` = sum of per-TF counts; chain/flow stats + flow audit + duplicate-ID check: explicit `timeframe` / `IN (1m,5m)`. |
| `db.py` | `get_db_stats`: `total_all_timeframes_audit` = **sum** of `by_tf_rows`, not unscoped `COUNT(*)`. |
| `audit_expiry_data.py` | All snapshot queries: `timeframe IN (1m, 5m)` bound. |
| `clean_db.py` | Delete / verify / total: `timeframe IN (1m, 5m)` bound. |
| `similarity_feature_survivorship.py` | `discover_tickers_for_survivorship`: `WHERE timeframe=?` (canonical). |
| `debug_flow_snapshot.py` | `--latest` path: `AND timeframe=?` (canonical). |
| `tools/issue19_option_a_post_validate.py` | `snapshots_context_distribution`: `WHERE timeframe=?` + documented `base_filter`. |
| `backfill_flow_imbalance.py` | Backfill scan: `timeframe IN (1m, 5m)`. |
| `tools/pin_neutral_anchor_feasibility_sample_v1.py` | Sample row: `timeframe IN (1m, 5m)` (repair scope parity). |

---

## B. Every violation fixed (from proof v1 §D)

| # | v1 violation | Resolution |
|---|----------------|------------|
| 1 | `test_issue16_normalized_outcome_materialize.py` unscoped `SELECT` | Added `AND timeframe=?` with `CF`. |
| 2 | `ontology_mismatch_evidence.py` | All queries `WHERE timeframe = ?` (canonical). |
| 3 | `db_health_audit.py` inventory + flow audit | Totals from `GROUP BY timeframe`; metrics + flow audit `WHERE timeframe=?` or `IN (?,?)`; duplicate IDs scoped to `IN (1m,5m)`. |
| 4 | `db.py` `get_db_stats` unscoped `COUNT(*)` | Replaced with sum of per-timeframe counts. |
| 5 | `audit_expiry_data.py` | All queries `timeframe IN (?, ?)`. |
| 6 | `clean_db.py` | Delete / verify / total: `timeframe IN (?, ?)`. |
| 7 | `similarity_feature_survivorship.py` | `discover_tickers_*`: `timeframe = CANONICAL_TIMEFRAME`. |
| 8 | `debug_flow_snapshot.py` `--latest` | `timeframe = CANONICAL_TIMEFRAME`. |
| 9 | `issue19_option_a_post_validate.py` `snapshots_context_distribution` | `WHERE timeframe = ?` (canonical). |
| 10 | `backfill_flow_imbalance.py` | `WHERE timeframe IN (?, ?)`. |
| 11 | `pin_neutral_anchor_feasibility_sample_v1.py` | `WHERE timeframe IN (?, ?)`. |

---

## C. Intentionally multi-timeframe paths (SAFE NON-CANONICAL)

| Path | Why safe |
|------|----------|
| `WHERE timeframe IN (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)` | Explicit list; both TF buckets known; used for expiry cleanup, flow backfill, pin_neutral sampling, duplicate-ID scan within known TF set. |
| `GROUP BY timeframe` + sum for `total_all_timeframes_audit` | No single mixed aggregate without per-TF breakdown; total is arithmetic sum of explicit buckets. |
| `SELECT MAX(snapshot_id) FROM snapshots` (e.g. `tools/phase2_forward_write_verify.py`) | Global **ID sequence** diagnostic; not used for mixed-timeframe **label** or **cohort** analytics. |
| `WHERE snapshot_id = ?` | Single-row PK; timeframe is a column on that row. |

---

## D. Final counts (v2 definitions)

| Category | Count |
|----------|------:|
| **SAFE** | **270** (every `FROM snapshots` substring occurrence classified SAFE under v2 §Classification) |
| **UNSAFE** | **0** |
| **BYPASS** | **0** (v2: enforcement bypass / unscoped analytical read — not “raw SQL outside `db.py`”) |
| **UNKNOWN** | **0** |

---

## E. FINAL

### **PASS**
