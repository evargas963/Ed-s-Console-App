# Issue 19 — Repair implementation report

**Date:** 2026-04-03  
**Mode:** controlled repair implementation (no calibration).  
**Evidence:** pytest, `data/ed_console.db` SQL, CLI audits, `tools/repair_validation_counts_v1.py`, `tools/pin_neutral_anchor_feasibility_sample_v1.py`, `tools/issue19_option_a_post_validate.py`.

---

## 1. Executive conclusion

- **Canonical ticker identity (P1)** is implemented: broker literals with a leading `$` stay on the wire; bare Schwab index roots used in JSON or APIs map to the stored key for SQLite (`SPX` → `$SPX`). Query paths that embed `ticker = ?` now align with `snapshots` / `price_bars_1m` without renaming historical rows.
- **`pin_neutral` repair:** the dedicated backfill path is fixed to include **legacy `timeframe='5m'`** rows (all 797 audited rows in this DB are `5m`). The earlier design note about the **rolling 14-day** live window remains correct for **`fill_outcomes`**, but it was **not** the only reason rows were skipped—scope was also wrong until `5m` was included.
- **Production run on `data/ed_console.db`:** `updates_executed: 0` for all 797 rows. **Root cause:** `price_bars_1m` has **no** rows with `bar_end_ts_utc <= snapshot.ts_utc` for these pin_neutral samples (retention gap: snapshots are older than the earliest retained 1m bars). This is **legitimate “cannot label yet”**, not a silent query hack. **Next step** to realize labels is **extending `price_bars_1m` history** (ingestion/backfill) for the relevant tickers/times, then re-running `pin_neutral_outcome_repair_v1.py`.
- **Zone vs `regime_primary`:** no SQL conflation; a **contract test** ensures `get_similar_setups` does not reference `regime_primary`. `SnapshotRow` comments already separate structural `zone` from environment `regime_primary`.

---

## 2. Scope and constraints

- No Issue 19 tier SQL edits, no calibration weight changes.
- No bulk rename of `snapshots.ticker` / `price_bars_1m.ticker`.
- Live **`fill_outcomes`** keeps the **14-day rolling** eligibility window; historical repair uses **`fill_outcomes_pin_neutral_backfill_v1`** (full-history scope for eligible rows).

---

## 3. Exact files changed (this repair pass)

| File | Change |
|------|--------|
| `instrument_identity.py` | `ticker_storage_key`: preserve `$`; map bare **`BROKER_INDEX_BARE_ROOTS`** (`SPX`, `DJI`, `COMPX`, `VIX`) → `$…`; documented sources. |
| `db.py` | Import `DERIVED_TIMEFRAME`; `fill_outcomes_pin_neutral_backfill_v1` uses `timeframe IN ('1m','5m')`; audit includes `timeframes_in_scope`; `fill_outcomes` / `get_similar_setups` / `get_recent_snapshots` / `count_snapshots` / `get_avg_move` use `ticker_storage_key` (pre-existing where noted in audit). |
| `adaptive_shadow_v2_calibration.py` | `load_survivorship_anchors_v1` uses `ticker_storage_key` (no `$` strip). |
| `pin_neutral_outcome_repair_v1.py` | CLI repair; `run_repair` calls backfill once with `dry_run=` (cleanup). |
| `tests/test_instrument_identity_and_repair_v1.py` | Contract tests: SPX alias, 5m pin_neutral backfill, zone-vs-regime guard on `get_similar_setups` source. |
| `tools/repair_validation_counts_v1.py` | Counts pin_neutral scope, `SPX` vs `$SPX` labeled rows, anchor-feasibility SQL (`EXISTS` bar_end ≤ ts). |
| `tools/pin_neutral_anchor_feasibility_sample_v1.py` | Sample oldest/newest pin_neutral row and print anchor / forward bar diagnostics. |
| `docs/issue19_repair_implementation_report.md` | This document. |

---

## 4. Canonical ticker identity implementation

**Policy:** P1 broker literal in storage (`$SPX`, …). Inputs may be bare (`SPX`) or already prefixed (`$SPX`). **`ticker_storage_key`** is the single normalization for **DB equality** on `snapshots` / `price_bars_1m` / Issue 19 SQL.

**Bare index set** (`BROKER_INDEX_BARE_ROOTS`): `SPX`, `DJI`, `COMPX`, `VIX` — tied to `schwab_full_field_inventory.py` index fallbacks and `market_context.py` (`$VIX`).

**Producer/storage:** ingestion was already writing `$SPX`; no migration performed.

**Anchors:** `load_survivorship_anchors_v1` applies `ticker_storage_key` so JSON anchors match DB.

**Retrieval:** `get_similar_setups`, `get_recent_snapshots`, `count_snapshots`, `get_avg_move` normalize the ticker argument.

**Proof (this workspace):**

```text
python -c "from pathlib import Path; from db import EdDB, CANONICAL_TIMEFRAME; ..."
→ similar SPX query rows 20
```

(Using `data/ed_console.db`: querying with **`SPX`** returns rows stored under **`$SPX`**.)

**Tests:** `python -m pytest tests/test_instrument_identity_and_repair_v1.py` → **6 passed** (run 2026-04-03).

---

## 5. `pin_neutral` repair implementation

**Live path:** `fill_outcomes` remains **14-day rolling** and **canonical `1m` timeframe only** (`timeframe != 1m` → return). That is unchanged by design.

**Dedicated backfill:** `EdDB.fill_outcomes_pin_neutral_backfill_v1`:

- Selects `zone='pin_neutral'`, `outcome_filled=0`, `horizon_outcome_schema_version=BAR_ANCHOR_V1`, **`timeframe IN (1m, 5m)`**.
- Reuses `_apply_bar_based_outcome_updates` (same bar-anchor contract as live `fill_outcomes`).
- **CLI:** `python pin_neutral_outcome_repair_v1.py --db data/ed_console.db`  
  Optional: `--dry-run`, `--skip-backup`.

**Additional root cause found:** all `pin_neutral` rows in `data/ed_console.db` are **`timeframe='5m'`** (797 rows). A filter on **`1m` only** selected **zero** rows before this fix.

**Production evidence (`tools/repair_validation_counts_v1.py --db data/ed_console.db`):**

```text
pin_neutral by timeframe: [('5m', 797)]
backfill SQL match count (1m+5m): 797
pin_neutral repair-scope rows with at least one anchor bar (bar_end <= ts_utc): 0 of 797
```

**Repair run audit** (`data/pin_neutral_outcome_repair_v1_last_audit.json`): `snapshots_scanned: 797`, `updates_executed: 0`.

**Legitimate unlabeled reason:** no anchor bar in `price_bars_1m` at or before `snapshots.ts_utc` (see `tools/pin_neutral_anchor_feasibility_sample_v1.py newest` — `anch_idx -1`, `bars with bar_end <= ts_utc: 0`).

**Separation:** Rows that **cannot** be labeled until bars exist are **not** mixed with “repair job failed”; the job ran deterministically and wrote **zero** updates because the bar series does not cover snapshot times.

---

## 6. Zone vs `regime_primary` hardening

- **Code:** `test_get_similar_setups_issue19_uses_zone_not_regime_primary` asserts `regime_primary` does not appear in `get_similar_setups` source (prevents silent conflation in tier SQL).
- **Model:** `SnapshotRow` in `db.py` already documents `zone` (structural, `derive_zone`) vs `regime_primary` (environment, `regime_engine`).
- **Reporting:** Issue 19 coverage JSON still reports distributions over **`regime_primary`** for **labeled** rows (`tools/issue19_option_a_post_validate.py`) — that is **context labeling**, not the structural `zone` filter in tier SQL. No change required; readers should keep the distinction explicit.

**Non-blocking cleanup:** UI copy that says “pinning regime” next to `pin_neutral` **zone** without labels remains a narrative risk; not changed in this pass.

---

## 7. Data rebuild / refresh steps

**After this pass:** `snapshots` outcome columns for pin_neutral were **not** updated (`updates_executed: 0`). **`snapshots_1m_normalized`** does **not** require a refresh for pin_neutral outcomes from this repair alone.

**When a future repair run executes non-zero updates**, run (from repo root, default DB path inside module):

```bash
python snapshot_normalizer.py
```

(`snapshot_normalizer.py` uses `data/ed_console.db` by default; `--validate`-only mode documented in that file.)

**Optional sync:** `normalized_training_sync.py` / project-specific training pipelines if your workflow expects them after snapshot mutations.

---

## 8. Validation results

### A. Canonical ticker identity

- Pytest contract tests pass.
- Live DB smoke: **`get_similar_setups('SPX', …)`** returns **20** rows on `data/ed_console.db`.
- Labeled row counts: **`SPX`** ticker key still **0** labeled rows (expected — storage is **`$SPX`**); **`$SPX`** **718** labeled (`tools/repair_validation_counts_v1.py`).

### B. `pin_neutral` repair

- **Repaired rows (this DB):** **0** (bar history gap).
- **Remaining unlabeled:** **797** in repair scope; **all** lack `price_bars_1m` coverage for anchor at `ts_utc` (`0 of 797` anchor-feasible).
- **Query eligibility:** Backfill **now selects** all 797 (5m included); previously **0** were selected under 1m-only filter.

### C. Zone / regime

- Contract test on `get_similar_setups` source; no functional conflation introduced.

### D. Mixed-era

- No snapshot ticker rewrites; `5m` pin_neutral rows remain `5m` with schema v3. Bar-key alignment uses **stored** `snapshots.ticker` (e.g. `$SPX`) matching `price_bars_1m.ticker`.

### E. Coverage (Issue 19)

Re-ran `python tools/issue19_option_a_post_validate.py --db data/ed_console.db`.

- **`pin_neutral` anchors:** tier1 **0/8** nonempty, tier2 **0/8** nonempty — **unchanged** in substance because **pin_neutral** rows are still **unlabeled** (`outcome_1c` NULL).
- **Not attributed to ticker bug anymore** for anchors that use `$SPX` in JSON — similarity engine uses DB keys consistent with repair design.

### F. Rollback / backup

- **Backup path:** `data/backups/ed_console.pre_pin_neutral_outcome_repair_v1.1775231955.db`
- **Rollback:** stop the app; copy backup over `data/ed_console.db` (or restore with your standard SQLite procedure). If you wish to remove the audit flag: delete row `pin_neutral_outcome_repair_v1` from `ed_schema_flags` after restore (optional; restore file reflects pre-run state including flags).

---

## 9. Remaining risks

1. **`BROKER_INDEX_BARE_ROOTS` completeness:** Only **proven** index names are mapped; unknown symbols that should use `$` may still need adding **with evidence** from ingestion inventory.
2. **`pin_neutral` labels:** Require **historical `price_bars_1m`** backfill/retention; until then Issue 19 pin_neutral pools stay empty regardless of SQL.
3. **`fill_outcomes` and `5m` snapshots:** Live **`fill_outcomes`** still **ignores** `5m` snapshot rows (`timeframe != 1m` → return). New **`5m`** rows may still **not** get outcomes from the live path; the **repair/backfill** path is the supported fix for historical `5m` + pin_neutral (and any future extension should be explicit).

---

## 10. Exact next actions

1. **Bars:** Ingest or import **`price_bars_1m`** for all tickers/time ranges covering `pin_neutral` `ts_utc` (and forward horizons).
2. Re-run **`python pin_neutral_outcome_repair_v1.py --db data/ed_console.db`** (backup on).
3. Re-run **`tools/repair_validation_counts_v1.py`** until anchor-feasible count matches repairable expectations; then **`python snapshot_normalizer.py`** if outcomes updated.
4. Re-run **`tools/issue19_option_a_post_validate.py`** for tier-1/tier-2 pin_neutral coverage.

---

## Required closing lines

- CANONICAL TICKER IDENTITY REPAIRED: **YES**
- pin_neutral HISTORY REPAIRED: **NO** (code path and scope repaired; **0** rows updated on `data/ed_console.db` — **no `price_bars_1m` anchor** for snapshot times; requires bar history before labels can be written)
- ZONE / REGIME HARDENING COMPLETE: **YES**
- MIXED-ERA DATA RISK REMOVED: **PARTIAL** (ticker identity unified; `5m` pin_neutral + bar retention are explicit remaining data-era issues)
- SAFE TO RE-RUN COVERAGE REVIEW: **YES**
- SAFE TO PROCEED TO CALIBRATION: **NO** (pin_neutral empirical pools still empty until bars + successful repair run; other anchors may proceed per your program discipline)
