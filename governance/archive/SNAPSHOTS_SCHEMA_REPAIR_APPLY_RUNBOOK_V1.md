# Snapshots Schema Repair Apply Runbook V1

**Status:** Draft production apply runbook  
**Date:** 2026-05-07  
**Baseline drift note (2026-05-08):** Integer snapshots in `SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md` (e.g. 186,347 rows) are **historical author-time samples**. Production row counts move while writers stay on the drifted schema. This runbook uses **relational checks** on the emitted JSON so the dry-run/apply checklist does not go stale.  
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

Before **any** dry-run **or** `--apply` command (same bar for both — dry-run is not “safe pre-window research” while writers are active):

1. Confirm the working tree is clean and the checked-out commit is known:

   ```powershell
   git status --short
   git rev-parse --short HEAD
   ```

   Expected: no uncommitted changes. Record the SHA. It must be `d5df10c` or a reviewed descendant containing the same migration tool behavior.

2. Stop the app/server and all DB writers.

   No web server, scheduler, backfill, training, notebook, or manual process may hold a write connection to `data/ed_console.db`.

   **Hard requirement for dry-run too:** With active writers (WAL growth, concurrent connections), `PRAGMA integrity_check` and the migration tool’s read probes can **block, stall, or appear hung** for extended periods. Do not run dry-run against a live-writing production DB; treat the **first dry-run JSON as the first artifact of the maintenance window**, after writers are stopped.

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

All **Preconditions** above must be satisfied (including **all writers stopped**) before running this command. Dry-run first. Do not use `--apply`.

```powershell
python tools/migrate_snapshots_schema_repair_v1.py --db-path data/ed_console.db
```

The dry-run JSON must be reviewed before authorization to apply.

---

## Dry-Run Review Checklist

All fields below must match before `--apply` is authorized. Use **only** the dry-run JSON from **this** run against **this** DB (not contract prose integers).

- `success == true`
- `status == "dry_run"` (if `status == "noop_already_repaired"` and `idempotence == "already_repaired"`, schema is already fixed — do not run `--apply` for repair; treat as closure verification only)
- `errors == []`
- `pre_integrity_check == "ok"`
- **Row-count coherence:** `counts_before.snapshots == id_assignment_preview.total_rows`
- **Null backlog:** `counts_before.snapshots_null_snapshot_id == id_assignment_preview.null_count`
- **Distinct-ID invariant (pre-repair):** `counts_before.snapshots_distinct_snapshot_id == counts_before.snapshots - counts_before.snapshots_null_snapshot_id`  
  (If this fails, existing non-null `snapshot_id` values are not unique — stop; see migration tool `duplicate_existing_snapshot_id` refusal.)
- **ID range preview (when `id_assignment_preview.null_count > 0`):**
  - `id_assignment_preview.first_new_snapshot_id == id_assignment_preview.max_existing_snapshot_id + 1`
  - `id_assignment_preview.last_new_snapshot_id == id_assignment_preview.max_existing_snapshot_id + id_assignment_preview.null_count`
- **When `id_assignment_preview.null_count == 0`:** `id_assignment_preview.first_new_snapshot_id` and `last_new_snapshot_id` should be `null` — repair may be schema-only or noop; align with `snapshots_schema_before` and contract.
- **`collision_count`:** must be present and a non-negative integer (tool-computed). **Do not** compare to any fixed historical number. If `collision_count > 0`, the migration contract’s rowid / `snapshot_id` overlap case applies — operator must explicitly accept the emitted count (and re-read `SNAPSHOTS_SCHEMA_REPAIR_MIGRATION_CONTRACT.md` Test Bar) before authorizing `--apply`.
- `snapshots_schema_before.is_repaired == false` (for the standard drifted production case requiring repair)
- `target_column_count` is recorded as the canonical reference count for this apply
- `target_extra_live_columns` is enumerated and operator-reviewed

Every `target_extra_live_columns` entry is a live column not declared by `db.py::_init_schema`. The operator must explicitly accept each listed column as legitimate before proceeding. If any entry is unexpected, stop and open a contract addendum.

---

## Apply Command

Only run after dry-run authorization.

Capture the apply JSON verbatim to a governance audit file:

```powershell
$ts = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$audit = "reports/audits/snapshots_schema_repair_v1_$ts.json"
New-Item -ItemType Directory -Force -Path "governance/audits" | Out-Null
python tools/migrate_snapshots_schema_repair_v1.py --db-path data/ed_console.db --apply | Tee-Object -FilePath $audit
```

Record the audit file path and the exact commit SHA used for the apply.

---

## Apply Success Criteria

The captured apply JSON must satisfy all of the following. Compare **within the same JSON object** (before/after/preview fields are all from one apply run).

- `success == true`
- `status == "applied"`
- `errors == []`
- `pre_integrity_check == "ok"`
- `post_integrity_check == "ok"`
- `backup_path` exists on disk
- the database at `backup_path` returns `PRAGMA integrity_check == "ok"`
- **Row parity:** `counts_after.snapshots == counts_before.snapshots`
- **Null backlog cleared:** `assigned_null_snapshot_ids.count == counts_before.snapshots_null_snapshot_id`
- **Assigned range matches preview (when `counts_before.snapshots_null_snapshot_id > 0`):**
  - `assigned_null_snapshot_ids.first == id_assignment_preview.first_new_snapshot_id`
  - `assigned_null_snapshot_ids.last == id_assignment_preview.last_new_snapshot_id`
- **When `counts_before.snapshots_null_snapshot_id == 0`:** `assigned_null_snapshot_ids.count == 0` (and `first`/`last` null/absent per tool)
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

Expected (compare SQL output to the **captured apply JSON** — no fixed row counts):

- `null_ids == 0`
- `COUNT(*)` equals `counts_after.snapshots` from the apply JSON
- `COUNT(DISTINCT snapshot_id) == COUNT(*)`
- `MAX(snapshot_id) >= id_assignment_preview.max_existing_snapshot_id` (IDs only increase for former NULL rows; must be at least the pre-repair max)
- When `assigned_null_snapshot_ids.last` is present: `MAX(snapshot_id) >= assigned_null_snapshot_ids.last`

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

Examples: relational checklist failures (count coherence, ID preview math), unexpected `target_extra_live_columns`, failed integrity check, or `collision_count` / overlap semantics not explicitly accepted when non-zero.

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

**Status:** Gap retired 2026-05-09 — apply audit `reports/audits/snapshots_schema_repair_v1_20260509_011607.json`, register **O-39**, migration contract Named Gaps. The historical retirement preconditions (`--apply` success + apply JSON saved under `reports/audits/` + independent post-condition checks + closure-commit register update with audit-file SHA) were all met at retirement; full evidence is captured in O-39 and the apply audit JSON.

---

## Out Of Scope

- Stage A2 held `db.py` split
- **`rowid` fallback for governed snapshot outcomes** — removed under Stage A2b (`STAGE_A2B_SNAPSHOT_OUTCOME_ROWID_FALLBACK_REMOVAL_CONTRACT.md`) after O-39; not part of this runbook’s apply step
- deferred-refresh performance commit
- Stage B schema drift audit tool
- Stage C table-specific migrations
- Stage D startup/CI drift detection
- backfill or training
- ad hoc code changes to `db.py`, the migration tool, tests, or runtime modules **except** follow-on contracts explicitly sequenced after closure (e.g. Stage A2b rowid removal)
