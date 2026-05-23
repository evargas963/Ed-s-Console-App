> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/operations/backfill_et_clock_runbook.md`.

# ET clock backfill runbook (FIND-CAL-TS item-6)

Rewrites pre-cutover `et_hour`, `et_minute`, `market_session`, and `ts_et` on `snapshots` and `snapshots_1m_normalized` from authoritative `ts_utc` (DST-aware).

**Ceiling:** `ts_utc < COH_I_A_ET_BACKFILL_CEILING_TS_UTC` (`time_et.py` — COH-I-A landing + 1h deploy-restart pad).

**Tool:** `tools/backfill_et_clock_from_ts_utc_v1.py`

## Prerequisites

- Stop or quiesce writers if possible (SQLite busy-lock risk).
- Canonical DB only unless `--allow-noncanonical-db` (harness/backup).
- Backup under `backups/db/` per your usual migration discipline.

## Step 1 — Dry-run

```powershell
python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db
```

Review JSON output:

- `pre_scan.<table>.candidates` — rows under ceiling
- `pre_scan.<table>.mismatched` — rows that would change
- Audit written to `governance/audits/backfill_et_clock_from_ts_utc_v1_<timestamp>.json` (gitignored)

## Step 2 — Batched commit

```powershell
python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db --max-rows 50000 --commit
```

Repeat until `post_scan` shows `mismatched: 0` for both tables (or run one full commit without `--max-rows` once counts look safe).

`--max-rows` caps **updates** per invocation, not scans only.

## Step 3 — Verify sample

```powershell
python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db --commit --verify-sample 50
```

Exit `0` = success; `1` = sample mismatch or missing DB; `2` = canonical DB guard rejection.

## Post-backfill

1. If `snapshots_1m_normalized` row coverage lags `snapshots`, rematerialize via `snapshot_normalizer.materialize_normalized_table` / Issue-16 sync.
2. Resume calibration widen (cohort cutover floor optional once historical rows are correct).
3. Movement-threshold tools now filter RTH via `ts_utc` post-fetch (no `rth_where_clause()` in SQL).

## Idempotency

Second commit pass updates zero rows when stored ET clock fields already match `derive_et_clock_from_ts_utc(ts_utc)`.

## calibration_decision_log

No `et_hour` / `ts_et` columns. Session context for advisory paths is reconstructed from `ts_utc` at read time (`calibration/v2_advisory_backfill.py`).
