> **Classification:** Policy Specification | **Scope:** Governance policy/contract `STAGE_A2B_SNAPSHOT_OUTCOME_ROWID_FALLBACK_REMOVAL_CONTRACT.md`.

# Stage A2b — Snapshot Outcome `rowid` Update-Key Removal Contract

**Status:** IMPLEMENTED — 2026-05-08 (preconditions verified by O-39 post-checks; `db.py` rowid fallback removed)  
**Created:** 2026-05-08  
**Authority:** `governance/SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md` (O-38 explicit DDL; **out-of-scope** line: no `rowid` as permanent identity substitute for `snapshot_id`)  
**Related:** Stage A2a deferred governed-outcome refresh on bulk `upsert_1m_bars` (landed API: `refresh_governed_outcomes=`).

---

## Problem

`db.py` bar-anchor outcome maintenance uses `_snapshot_update_key()` to choose `UPDATE snapshots ... WHERE snapshot_id = ?` vs `WHERE rowid = ?`. When `snapshot_id` is **NULL** (legacy drifted schema), the code falls back to SQLite **`rowid`** so outcome columns can still be written.

That fallback is **not** endorsed as production identity. It is a bridge while `snapshots.snapshot_id` violates target DDL (nullable plain `INT` vs `INTEGER PRIMARY KEY AUTOINCREMENT`). Per the migration contract, **`rowid` must not substitute for `snapshot_id` as durable identity**, and after repair **NULL `snapshot_id` rows must not exist**.

Keeping the fallback after migration creates **unreachable / misleading** behavior: writes succeed via a key that is unrelated to application identity, masking future schema drift instead of failing loudly.

---

## Preconditions (must be true before removing fallback)

1. Production (and any shared dev DBs that claim parity) has run the snapshots schema repair per `SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md`: **no rows with `snapshot_id IS NULL`** on `snapshots`.
2. `snapshots.snapshot_id` is the **INTEGER PRIMARY KEY AUTOINCREMENT** row shape declared in `db.py::_init_schema` (or equivalent audited target).
3. Operators acknowledge a one-time window: legacy DBs that still have NULL ids **must not** run this removal until repaired (or must use a repair CLI first).

---

## Contract

After preconditions:

1. **`_snapshot_update_key`** MUST resolve updates **only** from non-null **`snapshot_id`**. If `snapshot_id` is missing or non-castable, the row MUST be **skipped** with an explicit log or metric (no silent no-op without visibility).
2. **SELECT** paths that exist only to supply `_rowid` for outcome refresh MAY be simplified to **`snapshot_id`-only** row shapes once no code path requires `rowid` for writes.
3. **`UPDATE ... WHERE rowid = ?`** for governed outcomes MUST be **removed** from production paths; `rowid` is not an application key.
4. Tests that assert `rowid`-based updates for NULL `snapshot_id` MUST be **deleted or rewritten** as migration/repair fixtures only — they MUST NOT document the fallback as intended long-term behavior.

---

## All-consumers disposition (removal scope)

| Site | Action | Note |
|------|--------|------|
| `db.py::_snapshot_update_key` | **remove `rowid` branch** | Return key only when `snapshot_id` is valid integer. |
| `db.py::_apply_bar_based_outcome_updates` | **consume snapshot_id-only rows** | Callers must not rely on `_rowid`. |
| `db.py::_snapshot_rows_affected_by_bar_mutations` / `_refresh_governed_outcomes_after_bar_mutation` / related SELECTs | **drop `rowid AS _rowid`** if unused after key change | Grep all `SELECT rowid AS _rowid` in outcome refresh flow. |
| `db.py::_already_filled` | **no change to signature** | Continues to use column name from `_snapshot_update_key`; must remain `snapshot_id`-only. |
| Tests under `tests/test_governed_outcome_refresh_after_bar_mutation_v1.py` | **remove or quarantine rowid test** | If retained temporarily, mark `pytest.mark` + docstring: legacy pre-repair only; delete when A2b lands. |
| Runbooks | **reference this contract** | `SNAPSHOTS_SCHEMA_REPAIR_APPLY_RUNBOOK_V1.md` already discusses deleting rowid workaround language — align on removal commit. |

---

## Verification

```text
python -m pytest tests/test_governed_outcome_refresh_after_bar_mutation_v1.py
python tools/check_schwab_csv_first.py --whole-repo
```

Expected: outcome refresh and bar-mutation tests pass on **repaired** DB shape only; no test requires `UPDATE ... WHERE rowid = ?` for snapshots.

---

## Sequencing

1. **A2a** (optional / may already land): bulk backfill `refresh_governed_outcomes=False` + explicit bulk repair — independent of this contract.  
2. **Schema repair migration** (production): per O-38 contract.  
3. **A2b implementation commit**: this contract + `db.py` + test updates.  
4. Re-run governed-outcome and integration tests; then resume Schwab batch work without conflating A2b with CSV slices.

**SYSTEM STATUS:** Independent of Schwab `FAIL`; A2b is data-plane / schema discipline.
