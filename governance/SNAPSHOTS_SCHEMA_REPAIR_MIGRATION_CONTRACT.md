# Snapshots Schema Repair Migration Contract

**Status:** Draft schema repair migration contract  
**Date:** 2026-05-07  
**Module:** Database infrastructure  
**Scope:** One-shot repair of `snapshots` identity schema and rebuild discipline for `snapshots_1m_normalized`.

This contract defines the governed repair path for the production SQLite `snapshots` table after live schema drift was discovered between `db.py` and `data/ed_console.db`. The migration is infrastructure repair only. It does not alter trading authority, model authority, lifecycle authority, or operator-facing decision semantics.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

The migration is an operator-authorized one-shot data-store repair. It does not place orders, promote runtime behavior, change model predictions, or change A2 lifecycle authority.

---

## Scope

In scope:

- repair `data/ed_console.db::snapshots` so `snapshot_id` is `INTEGER PRIMARY KEY AUTOINCREMENT`;
- assign fresh deterministic IDs to rows whose live `snapshot_id` is `NULL`;
- preserve all `snapshots` rows and columns through an explicit-DDL rebuild;
- recreate required `snapshots` indexes;
- run integrity, uniqueness, non-null, count-parity, and idempotence checks;
- document the `snapshots_1m_normalized` rebuild plan after `snapshots` repair;
- open follow-up governance gaps for production post-migration audit and future schema drift detection;
- bind O-38 explicit-DDL / no-CTAS migration discipline.

Out of scope:

- implementing or running the migration script in this commit;
- running production DB migration in this commit;
- committing the held historical backfill deferred-refresh performance patch;
- using `rowid` as a permanent identity substitute for `snapshot_id`;
- changing model labels, predictions, strategy thresholds, lifecycle policy, or trading behavior;
- repairing unrelated tables not identified as drifted in the snapshot-schema audit;
- deleting or preserving de-enrolled `snapshots_1m_normalized` orphan rows beyond the rebuild plan stated below.

---

## Root Cause

The code-declared `snapshots` schema in `db.py::_init_schema` declares:

```sql
snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT
```

The live production schema in `data/ed_console.db` has:

```sql
snapshot_id INT
```

This live column is a plain nullable integer column, not the SQLite rowid alias and not an autoincrementing primary key. `CREATE TABLE IF NOT EXISTS` did not repair the live table because it is a no-op once the table already exists.

The audit also found a table-rebuild signature in the live schema. `CREATE TABLE ... AS SELECT ...` strips SQLite constraints, primary keys, defaults, and indexes. The normalized snapshot table has the same drift pattern and is addressed separately in this contract.

Observed production facts at contract time:

- total `snapshots` rows: `186,347`;
- rows with non-null `snapshot_id`: `179,036`;
- rows with `snapshot_id IS NULL`: `7,311`;
- current non-null `snapshot_id` range: `1..179,720`;
- NULL rows with `rowid <= 179,720`: `664`;
- NULL rows with `rowid > 179,720`: `6,647`.

Because 664 NULL rows have `rowid` values that collide with existing `snapshot_id` values, `COALESCE(snapshot_id, rowid)` is forbidden as an ID assignment rule.

---

## Target Schema

The migration MUST create the target `snapshots` table with a full explicit `CREATE TABLE` statement whose first column is:

```sql
snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT
```

The target DDL MUST preserve the column set and compatible declared types from `db.py::_init_schema` for `snapshots`, including all columns currently present in production. The migration script MUST derive any additional production-only columns from `PRAGMA table_info(snapshots)` and include them explicitly in the target DDL if they are not already represented in the code-declared schema.

The migration MUST NOT use `CREATE TABLE ... AS SELECT ...` for the repaired table. CTAS is forbidden by O-38 because it does not preserve primary keys, defaults, constraints, or indexes.

Allowed shape:

```sql
CREATE TABLE snapshots_new (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ...
);

INSERT INTO snapshots_new (snapshot_id, ...)
SELECT repaired_snapshot_id, ...
FROM ...
ORDER BY old_rowid;
```

Forbidden shape:

```sql
CREATE TABLE snapshots_new AS
SELECT ...
FROM snapshots;
```

---

## ID Assignment Rule

The migration MUST assign IDs as follows:

1. Rows with non-null `snapshot_id` keep their existing `snapshot_id` value.
2. Rows with `snapshot_id IS NULL` receive fresh sequential IDs starting at `MAX(snapshot_id) + 1`.
3. At contract time, `MAX(snapshot_id) + 1 = 179,721`.
4. NULL rows are assigned in source `rowid ASC` order to preserve chronological insertion order.
5. The repaired target table MUST have no duplicate `snapshot_id` values and no `snapshot_id IS NULL` rows.

Equivalent SQLite window-function shape is acceptable:

```sql
CASE
  WHEN snapshot_id IS NOT NULL THEN snapshot_id
  ELSE :max_existing_snapshot_id + ROW_NUMBER() OVER (
    PARTITION BY snapshot_id IS NULL
    ORDER BY old_rowid
  )
END
```

The script may implement the assignment through a staging query or temporary table, but it MUST prove the final uniqueness and non-null invariants before replacing the production table.

---

## Migration Safety Bar

The migration script MUST implement all of the following:

- dry-run / audit mode by default;
- explicit `--apply` flag required for production writes;
- fresh backup immediately before `--apply`;
- backup path recorded in the audit output;
- `PRAGMA integrity_check` before migration;
- `PRAGMA integrity_check` after migration;
- source vs target row-count parity assertion; for the current production DB this must equal `186,347`;
- `snapshot_id` uniqueness assertion in target;
- `snapshot_id IS NOT NULL` assertion in target;
- explicit recreation of at least:
  - `idx_snap_ticker_tf_ts`;
  - `idx_snap_outcome_unfilled`;
  - `idx_snap_ts`;
- preservation or recreation of any additional production indexes discovered via `PRAGMA index_list(snapshots)`;
- `ANALYZE snapshots` after successful replacement;
- single transaction around target-table creation, copy, index recreation, verification, drop/rename, and analyze;
- failure leaves the original `snapshots` table intact or requires restore from the fresh backup;
- JSON audit output that includes row counts, max IDs, null counts, collision counts, backup path, integrity check results, and idempotence status.

The script MUST refuse to proceed if:

- no fresh backup can be created;
- `PRAGMA integrity_check` is not `ok` before migration;
- the source table is already repaired but still has `snapshot_id` nulls;
- ID assignment would collide;
- target parity, uniqueness, or non-null checks fail;
- any required index cannot be recreated.

---

## Idempotence

Running the migration script twice MUST be safe.

The script MUST probe the live schema before applying. If `snapshots.snapshot_id` is already an `INTEGER PRIMARY KEY` rowid alias and all rows have non-null `snapshot_id`, the script MUST exit as a no-op with a successful audit status.

Idempotence detection MUST NOT rely only on row counts. It must inspect schema metadata and data invariants.

---

## `snapshots_1m_normalized` Plan

Audit result:

- `snapshots_1m_normalized` has 24 rows that do not correspond to current `snapshots` rows;
- all 24 belong to de-enrolled tickers not in `logging_universe`;
- orphan tickers are `Q` x 20, plus `COP`, `KO`, `UUUU`, and `VZ` x 1 each;
- these rows are accepted as non-load-bearing detritus from past backfills.

After `snapshots` migration succeeds, `snapshots_1m_normalized` SHOULD be rebuilt from migrated `snapshots` using the existing normalize-from-snapshots/materialization path. The existing `snapshots_1m_normalized` table may be dropped as part of that rebuild. Loss of the 24 orphan rows is explicitly accepted.

If no public rebuild routine exists, the migration implementation commit MUST either:

- expose a governed rebuild routine using existing normalization logic; or
- leave `snapshots_1m_normalized` untouched and record a follow-up blocker in the migration audit.

The schema repair script for `snapshots` MUST NOT silently migrate orphan normalized rows as if they were source-of-truth rows.

---

## Rollback

Rollback authority is manual operator action using the fresh backup created immediately before `--apply`.

Rollback steps:

1. Stop the app/server and all DB writers.
2. Move the failed or undesired `data/ed_console.db` aside.
3. Restore the fresh backup file recorded in the migration audit to `data/ed_console.db`.
4. Run `PRAGMA integrity_check`.
5. Re-run the migration dry-run to confirm the pre-migration state is restored.

The previously created backup at `backups/db/20260507_115157_ed_console.db` remains useful as historical insurance but is not sufficient for the production apply required by this contract. A fresh backup is mandatory.

---

## Test Bar

The migration script implementation MUST include tests covering:

- synthetic fixture with mixed non-null and NULL `snapshot_id` rows;
- explicit collision case where NULL rows have `rowid` values that overlap existing `snapshot_id` values;
- dry-run produces projected row counts and ID assignment ranges without mutating the DB;
- `--apply` creates a table whose `snapshot_id` is `INTEGER PRIMARY KEY AUTOINCREMENT`;
- all rows have non-null, unique `snapshot_id` values after apply;
- NULL rows receive fresh IDs above prior `MAX(snapshot_id)`, ordered by source `rowid`;
- count parity is enforced;
- required indexes are recreated;
- `PRAGMA integrity_check` is required and recorded;
- `ANALYZE snapshots` is executed or audit-visible;
- second apply is no-op when the schema is already repaired;
- failure in any guardrail does not replace the source table.

No runtime trading tests are required for this contract because the migration does not change trading logic.

---

## Named Gaps

Opened by this contract:

- `db_schema_repair_post_migration_audit_pending` — remains open until the production migration run is verified with row-count parity, non-null/unique `snapshot_id`, integrity check, required indexes, and normalized snapshot rebuild disposition.
- `db_schema_drift_detection_pending` — remains open until a future startup or CI drift-detection mechanism compares code-declared critical schemas against live `sqlite_master`/`PRAGMA table_info` state.

No named gaps are retired by this doc-only contract.

---

## Crosswalk

`db.py::_init_schema`:

- Declares `snapshots.snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT`.
- The live production table drifted from this declaration and must be repaired before additional historical backfill runs.

`db.py` normalized snapshot materialization path:

- A prior `CREATE TABLE ... AS SELECT ...` rebuild pattern is the root cause class for `snapshots_1m_normalized` losing key constraints.
- This contract requires the normalized table to be rebuilt from migrated `snapshots`, not preserved through orphan-row migration by default.

`tests/test_governed_outcome_refresh_after_bar_mutation_v1.py`:

- Held tests around the `NoneType` failure are diagnostic only until schema repair lands.
- Fresh temp DB tests use the code-declared schema and therefore do not reproduce live production drift unless a legacy fixture is explicitly constructed.

Held historical backfill performance patch:

- Deferred per-window governed outcome refresh is a valid performance change, but it is a follow-up commit after schema repair.
- It must not be treated as the correctness fix for NULL `snapshot_id`.

`governance/OPERATOR_DECISION_REGISTER.md`:

- O-38 binds explicit-DDL / no-CTAS discipline for schema repair migrations.

---

## Non-Goals

This contract does not:

- implement the migration script;
- run the migration on `data/ed_console.db`;
- commit the held historical backfill deferred-refresh patch;
- use `rowid` as permanent production identity;
- repair unrelated tables not identified as drifted;
- continue historical backfill;
- change model, strategy, A2 lifecycle, or execution behavior;
- retire `db_schema_repair_post_migration_audit_pending`;
- implement schema drift detection.

