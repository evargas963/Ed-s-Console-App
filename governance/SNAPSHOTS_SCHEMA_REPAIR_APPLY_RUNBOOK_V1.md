# Snapshots Schema Repair Apply Runbook V1

**Status:** Draft production apply runbook  
**Date:** 2026-05-07  
**Migration tool commit:** `d5df10c` or descendant containing `tools/migrate_snapshots_schema_repair_v1.py` unchanged for the apply  
**Contract:** `governance/SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md`  
**Scope:** Operator-gated production apply of the governed `snapshots` schema repair migration.

This runbook is the production apply procedure for the O-38 explicit-DDL/no-CTAS snapshots schema repair. It is procedural only. It does not modify code, split held `db.py` work, introduce the Stage B schema drift audit tool, or perform any backfill.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

The migration repairs SQLite table metadata and durable row identity. It does not promote model authority, trading authority, strategy thresholds, lifecycle policy, or order-routing behavior.

---

## Preconditions

Before any dry-run or apply command:

1. Confirm the working tree is clean and the checked-out commit is known:

   ```powershell
   git status --short
   git rev-parse --short HEAD
   ```

   Expected: no uncommitted changes. Record the SHA. It must be `d5df10c` or a reviewed descendant containing the same migration tool behavior.

2. Stop the app/server and all DB writers.

   No web server, scheduler, backfill, training, notebook, or manual process may hold a write connection to `data/ed_console.db`.

3. Verify current DB integrity:

   ```powershell
   python -c "import sqlite3; c=sqlite3.connect('data/ed_console.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"
   ```

   Expected: `ok`.

4. Verify backup capacity.

   The backup root must have free disk space at least `2x` the live DB size. Default backup root is `backups/db/`.

5. Confirm no operator concern is open against the migration tool or this runbook.

---

## Dry-Run Command

Run dry-run first. Do not use `--apply`.

```powershell
python tools/migrate_snapshots_schema_repair_v1.py --db-path data/ed_console.db
```

The dry-run JSON must be reviewed before authorization to apply.

---

## Dry-Run Review Checklist

All fields below must match before `--apply` is authorized:

- `success == true`
- `status == "dry_run"`
- `errors == []`
- `pre_integrity_check == "ok"`
- `counts_before.snapshots == 186347`
- `counts_before.snapshots_null_snapshot_id == 7311`
- `id_assignment_preview.first_new_snapshot_id == 179721`
- `id_assignment_preview.last_new_snapshot_id == 187031`
- `collision_count == 664`
- `snapshots_schema_before.is_repaired == false`
- `target_column_count` is recorded as the canonical reference count for this apply
- `target_extra_live_columns` is enumerated and operator-reviewed

Every `target_extra_live_columns` entry is a live column not declared by `db.py::_init_schema`. The operator must explicitly accept each listed column as legitimate before proceeding. If any entry is unexpected, stop and open a contract addendum.

---

## Apply Command

Only run after dry-run authorization.

Capture the apply JSON verbatim to a governance audit file:

```powershell
$ts = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$audit = "governance/audits/snapshots_schema_repair_v1_$ts.json"
New-Item -ItemType Directory -Force -Path "governance/audits" | Out-Null
python tools/migrate_snapshots_schema_repair_v1.py --db-path data/ed_console.db --apply | Tee-Object -FilePath $audit
```

Record the audit file path and the exact commit SHA used for the apply.

---

## Apply Success Criteria

The captured apply JSON must satisfy all of the following:

- `success == true`
- `status == "applied"`
- `errors == []`
- `pre_integrity_check == "ok"`
- `post_integrity_check == "ok"`
- `backup_path` exists on disk
- the database at `backup_path` returns `PRAGMA integrity_check == "ok"`
- `counts_before.snapshots == 186347`
- `counts_after.snapshots == 186347`
- `assigned_null_snapshot_ids.count == 7311`
- `assigned_null_snapshot_ids.first == 179721`
- `assigned_null_snapshot_ids.last == 187031`
- `counts_after.snapshots_null_snapshot_id == 0`
- `counts_after.snapshots_distinct_snapshot_id == counts_after.snapshots`
- `snapshots_schema_after.is_repaired == true`
- `normalized_schema_after.is_repaired == true`
- `normalized_validation.ok == true`
- `indexes_after` includes:
  - `idx_snap_ticker_tf_ts`
  - `idx_snap_outcome_unfilled`
  - `idx_snap_ts`

---

## Independent Post-Condition Verification

Do not trust the migration self-audit alone. Run separate read-only checks after apply.

### Snapshot Schema Metadata

```powershell
python -c "import sqlite3, json; c=sqlite3.connect('data/ed_console.db'); c.row_factory=sqlite3.Row; rows={r['name']: dict(r) for r in c.execute('PRAGMA table_info(snapshots)')}; print(json.dumps({k: rows[k] for k in ['snapshot_id','ticker','timeframe','ts_utc','ts_et','spot','outcome_filled','horizon_outcome_schema_version','created_at']}, indent=2)); c.close()"
```

Expected:

- `snapshot_id.type == "INTEGER"` and `snapshot_id.pk == 1`
- `ticker.notnull == 1`
- `timeframe.notnull == 1`
- `ts_utc.notnull == 1`
- `ts_et.notnull == 1`
- `spot.notnull == 1`
- `outcome_filled.dflt_value == "0"`
- `horizon_outcome_schema_version.notnull == 1`
- `horizon_outcome_schema_version.dflt_value == "3"`
- `created_at.dflt_value` is `datetime('now')` or `(datetime('now'))`

### Identity Invariants

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/ed_console.db'); print('null_ids', c.execute('SELECT COUNT(*) FROM snapshots WHERE snapshot_id IS NULL').fetchone()[0]); print('max_count_distinct', c.execute('SELECT MAX(snapshot_id), COUNT(*), COUNT(DISTINCT snapshot_id) FROM snapshots').fetchone()); c.close()"
```

Expected:

- `null_ids == 0`
- `MAX(snapshot_id) >= 187031`
- `COUNT(*) == 186347`
- `COUNT(DISTINCT snapshot_id) == 186347`

### Required Indexes

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/ed_console.db'); print([r[1] for r in c.execute('PRAGMA index_list(snapshots)').fetchall()]); c.close()"
```

Expected required indexes:

- `idx_snap_ticker_tf_ts`
- `idx_snap_outcome_unfilled`
- `idx_snap_ts`

### Normalized Row Count

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/ed_console.db'); print(c.execute('SELECT COUNT(*) FROM snapshots_1m_normalized').fetchone()[0]); c.close()"
```

Expected: matches the row count reported by `normalized_validation.row_count` / `normalized_rebuild.normalized_rows` in the apply JSON.

---

## Failure Branches

No branch below permits "rerun and hope."

### 1. Dry-Run JSON Anomaly

Examples: unexpected counts, unexpected `target_extra_live_columns`, failed integrity check, unexpected ID range, or unexpected collision count.

Operator action: stop. Do not run `--apply`. Open a contract addendum or implementation revision.

### 2. Backup Creation Fails

Operator action: stop. Resolve disk space, path, lock, or permission problem. Do not retry `--apply` until backup creation succeeds and can be integrity-checked.

### 3. Apply Fails Inside Transaction

The migration reports failure before committing the schema replacement.

Operator action:

1. Run `PRAGMA integrity_check`.
2. Verify `snapshots` still exists and row count is unchanged.
3. Triage the JSON `errors` field.
4. Do not reattempt until the failure is explained and reviewed.

### 4. Apply Commits But Normalized Rebuild Fails

Status example: `status == "normalized_rebuild_failed"`.

State: `snapshots` may be repaired, while `snapshots_1m_normalized` may be empty or incomplete.

Operator must choose explicitly:

- restore from `backup_path` using the contract rollback procedure; or
- accept the half-state and run normalization manually under a separate reviewed procedure.

No default action is implied.

### 5. Independent Post-Condition Fails

Operator action: restore from `backup_path`. Do not attempt fix-forward without a new reviewed migration or addendum.

---

## Rollback Reference

Rollback follows the contract:

1. Stop the app/server and all DB writers.
2. Move the failed or undesired `data/ed_console.db` aside.
3. Restore the fresh `backup_path` recorded in the apply JSON to `data/ed_console.db`.
4. Run `PRAGMA integrity_check`.
5. Re-run migration dry-run to confirm the pre-migration state is restored.

---

## Gap Closure Criteria

The named gap `db_schema_repair_post_migration_audit_pending` may be retired only after all criteria below are met:

- `--apply` returned `success == true` and `errors == []`
- apply JSON is saved under `governance/audits/`
- all independent post-condition checks passed
- post-condition outputs are recorded in the closure artifact or commit notes
- `governance/OPERATOR_DECISION_REGISTER.md` is updated in the same closure commit with an audit-file SHA reference

---

## Out Of Scope

- Stage A2 held `db.py` split
- deleting or landing the `rowid` fallback workaround
- deferred-refresh performance commit
- Stage B schema drift audit tool
- Stage C table-specific migrations
- Stage D startup/CI drift detection
- backfill or training
- code changes to `db.py`, the migration tool, tests, or runtime modules
