# Repo-wide canonical snapshot timeframe enforcement (v2)

**Supersedes:** `repo_wide_canonical_enforcement_v1.md` for policy wording; v2 closes all **UNSAFE** paths identified in `repo_wide_canonical_enforcement_proof_v1.md`.

## Policy

- **No silent unscoped reads** of the multi-timeframe `snapshots` table: every `SELECT` / aggregate must include an **explicit `timeframe` predicate** (`= ?`, `IN (?, ?)`, or equivalent), **or** a **documented multi-timeframe-safe** pattern (`GROUP BY timeframe`, global `snapshot_id` PK lookup, `MAX(snapshot_id)` over the whole table for ID-sequence diagnostics).
- **Canonical live path:** `timeframe_config.CANONICAL_TIMEFRAME` (`'1m'`).
- **Legacy + repair scope:** `timeframe IN (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)` where both 1m and 5m rows must be included (explicit `IN`, never implicit “all rows”).

## Classification (v2 proof)

| Tag | Meaning |
|-----|--------|
| **SAFE** | Explicit `timeframe` filter; or `snapshots_1m_normalized` (1m table); or PK `snapshot_id`; or `GROUP BY timeframe` distribution; or global `MAX(snapshot_id)` / `COALESCE(MAX(snapshot_id))` (ID space, not mixed-TF analytics). |
| **UNSAFE** | `FROM snapshots` without the above — **must be zero** for PASS. |
| **BYPASS** | **v2:** Attempt to read **snapshot analytics** without timeframe scoping — **must be zero** for PASS. (Not “any raw SQL outside `db.py`.”) |
| **UNKNOWN** | Unclassified — **must be zero** for PASS. |

## Files changed in this enforcement pass (v2)

See `repo_wide_canonical_enforcement_proof_v2.md` §A.

## Intentionally multi-timeframe (explicit)

- **`WHERE timeframe IN (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)`** in audit/repair/cleanup scripts that must see both 1m and 5m rows (`audit_expiry_data.py`, `clean_db.py`, `backfill_flow_imbalance.py`, `db_health_audit.py` duplicate-ID check, `pin_neutral_anchor_feasibility_sample_v1.py`, etc.).
- **`GROUP BY timeframe`** in `get_db_stats` / health inventory — composition audit, not a single mixed total without breakdown.
- **`total_all_timeframes_audit`** in `get_db_stats` — **sum of `GROUP BY timeframe` counts**, not `SELECT COUNT(*) FROM snapshots` without a `WHERE`.
