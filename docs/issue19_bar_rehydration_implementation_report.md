# Issue 19 — Bar rehydration implementation report

**Generated:** 2026-04-03 (execution session)  
**Database:** `data/ed_console.db`  
**Scope:** Historical 1-minute bar rehydration (Schwab), canonical ticker identity, `pin_neutral` outcome repair, derived refresh, Issue 19 coverage diagnostics. **No calibration.**

---

## 1. Executive conclusion

Rehydration **did run successfully** after fixing a **critical ingestion bug**: `schwab_candles_to_bars` produced dicts **without** a `datetime` field, while `EdDB.upsert_1m_bars` only read `datetime` / `ts`. Every Schwab candle therefore resolved to timestamp `0`, hit the new sub-epoch guard, and **no rows were written** for rehydrated windows (while inflating a misleading “bars passed to upsert” counter).

After **adapter + upsert key alignment**, **invalid epoch rows purged**, and **re-run**:

- `price_bars_1m` grew to **47 988** rows (from ~24 k), global **`min(bar_start_ts_utc)` = 1771848000** (aligned with Schwab cohort windows).
- **`pin_neutral_anchor_feasible_count` went from 0 → 656** (141 still infeasible; see §6).
- **`pin_neutral_outcome_repair_v1` applied 612 row updates**; `snapshot_normalizer.py` completed with `returncode: 0`.
- **SQLite `PRAGMA integrity_check`:** `ok`.
- **Invalid epochs** (`bar_start_ts_utc < 1700000000`): **0** rows after cleanup.

**Remaining gap:** Early **`$SPX`** `pin_neutral` snapshots still sit **~24.5 hours** before the first stored Schwab minute in-range (`min_snap_minus_min_bar_start_sec` ≈ **−88 143** s in post-audit). **190** `pin_neutral` rows remain **`outcome_filled = 0`** (anchor / forward bar contract still not satisfiable for that cohort).

**Issue 19 similarity pools** (`tools/issue19_option_a_post_validate.py`): **`pin_neutral` anchor tier1/tier2 counts remain 0** — that metric reflects **labeled similar-set availability**, not bar ingestion; outcome repair does not by itself populate those pools.

---

## 2. Scope and constraints

- **In scope:** Schwab windowed 1m fetch → `schwab_candles_to_bars` → `upsert_1m_bars`; audit JSON; `pin_neutral` repair; normalized materialization when repair updates &gt; 0; Issue 19 post validate JSON.
- **Out of scope:** Calibration, synthetic bars, mixed ticker aliases in storage, silent fallbacks.
- **Rollback:** Restore SQLite from backup taken immediately before repair (see §3); re-copy `ed_console.db` from that file if needed.

---

## 3. Backup and baseline

| Artifact | Path / value |
|----------|----------------|
| Repair pre-backup (audit) | `data/backups/ed_console.pre_pin_neutral_after_bar_rehydration_issue19_v1.1775236281.db` (path recorded in `pin_neutral_repair_after_rehydration_issue19_v1.json`) |
| Baseline audit (run start) | Embedded in `data/bar_rehydration_issue19_v1_last_run.json` → `baseline` |
| Baseline JSON snapshot | `data/bar_rehydration_baseline_issue19_v1.json` |
| Post-rehydration audit JSON | `data/bar_rehydration_post_issue19_v1.json` |
| Full orchestrator summary | `data/bar_rehydration_issue19_v1_last_run.json` |

**Note:** The successful orchestrator invocation used **`--skip-backup`** for the bar phase; the **repair step still created** the backup above. If a **pre-bar** file backup is required for your policy, copy `data/ed_console.db` before the next bar phase.

**Baseline metrics (from last run `baseline`):**

- `price_bars_1m_global.n_rows`: **24 587**; `min_bar_start_ts_utc`: **1774877460**; `max_bar_end_ts_utc`: **1775236200**
- `pin_neutral_anchor_feasible_count`: **0** / **797** infeasible

---

## 4. Canonical ticker identity hardening for rehydration

| Decision | Detail |
|----------|--------|
| **Storage key** | `EdDB.upsert_1m_bars` uses **`ticker_storage_key(ticker)`** so e.g. bare `SPX` maps to **`$SPX`**, matching `snapshots` / joins. |
| **Adapter contract** | `schwab_candles_to_bars` now includes **`"datetime": ts`** alongside `timestamp` / `_ts`, matching what `upsert_1m_bars` expects. |
| **Defense in depth** | `upsert_1m_bars` dict branch accepts **`datetime` → `ts` → `timestamp` → `_ts`**. |
| **Poison rows** | Bars with **`bar_start_ts_utc <= 0`** are **skipped** (stops `0`-epoch MIN() poisoning). A one-time **`DELETE`** removed legacy rows with **`bar_start_ts_utc < 1700000000`** before re-fetch; production Schwab seconds are always positive and large. |

**Test:** `tests/test_instrument_identity_and_repair_v1.py::test_schwab_candles_to_bars_round_trips_through_upsert_1m` (plus existing `$SPX` storage test).

---

## 5. Rehydration execution details

**Command:**

```text
python bar_rehydration_issue19_v1.py --db data/ed_console.db --skip-backup
```

**Parameters (defaults):** `window_days=7`, `forward_pad_sec=3720`, `start_buffer_sec=86400`; single-window mode when span ≤ `window_days * 5` days; `end_datetime` capped to **now − 60s**.

**Cohort tickers (10):** `$SPX`, AMZN, COP, KO, META, MSFT, NVDA, SPY, UUUU, VZ.

**HTTP:** 10× **200** for the minute `pricehistory` calls in the successful run.

**Rows written:** `total_bar_dicts_upserted` in the summary now reflects **`upsert_1m_bars` return value** (validated row count), **23 400** in the successful run.

**Per-window log:** See `windows` array in `data/bar_rehydration_issue19_v1_last_run.json` (request range, `n_candles`, first/last candle ms, status).

---

## 6. Post-rehydration validation

### A. Coverage

| Metric | Post value |
|--------|------------|
| `price_bars_1m_global.n_rows` | **47 988** |
| `n_tickers` | **23** |
| `min_bar_start_ts_utc` | **1771848000** |
| `max_bar_end_ts_utc` | **1775236200** |
| `pin_neutral_anchor_feasible_count` | **656** |
| `pin_neutral_anchor_infeasible_count` | **141** |

**Per-ticker:** All cohort symbols except the residual `$SPX` early gap show **positive** `min_snap_minus_min_bar_start_sec` (bars start at or before snapshot times). **`$SPX`:** `bars_min_start_ts_utc` **1773063000** vs `min_snap_ts_utc` **1772974856** → **~24.5 h** gap at the **start** of the `$SPX` cohort window.

### B. Identity

- **`spx_family_ticker_rows`:** only **`$SPX`** present (**3518** rows); no parallel `SPX` bucket in audit slice.
- **Legacy poison cleanup:** **`COUNT(*) WHERE bar_start_ts_utc < 1700000000` = 0** after one-time delete (operational audit query; ongoing upsert only rejects **`<= 0`**).

### C. Anchor feasibility

- **Bar-history audit:** `tools/bar_history_recovery_audit_v1.py` logic via `collect_bar_recovery_audit` as invoked from the orchestrator — **656 / 797** feasible after fix.

### D. Integrity

- **`PRAGMA integrity_check`:** **`ok`**.

**Post-rehydration JSON:** `data/bar_rehydration_post_issue19_v1.json`.

---

## 7. `pin_neutral` repair rerun results

**Command:** Invoked automatically after rehydration when `pin_neutral_anchor_feasible_count > 0`.

| Field | Value |
|-------|--------|
| `snapshots_scanned` | **797** |
| `updates_executed` | **612** |
| `backup_path` | `data/backups/ed_console.pre_pin_neutral_after_bar_rehydration_issue19_v1.1775236281.db` |
| `tickers_touched` | AMZN, COP, KO, META, MSFT, NVDA, SPY, UUUU (**not** `$SPX`, VZ in this list — consistent with remaining anchor gaps) |

**Repair audit JSON:** `data/pin_neutral_repair_after_rehydration_issue19_v1.json` (mirrors `data/pin_neutral_outcome_repair_v1_last_audit.json`).

**Still unfilled:** **190** rows with `zone='pin_neutral'`, `outcome_filled=0`, `timeframe IN ('1m','5m')` after repair (SQLite count). Primary driver: **insufficient `price_bars_1m` before snapshot time** for **`$SPX`** (and any row whose forward horizons lack completed bars through evaluation time).

---

## 8. Derived-layer refresh steps

After **`updates_executed` &gt; 0**, the orchestrator ran:

```text
python snapshot_normalizer.py
```

**Result:** `returncode: 0`; materialization summary in `bar_rehydration_issue19_v1_last_run.json` → `snapshot_normalizer.stdout_tail` (raw_rows **38742**, normalized **32764**, validation `ok: True`).

---

## 9. Post-repair coverage review (Issue 19 diagnostics)

**Command:**

```text
python tools/issue19_option_a_post_validate.py --db data/ed_console.db --json-out data/issue19_coverage_after_bar_rehydration_issue19_v1.json
```

**`issue19_coverage_at_scale` (excerpt):**

- `tier1_nonempty_count`: **6** / **20** anchors → rate **0.3**
- `tier2_nonempty_count`: **9** → rate **0.45**
- `tier2_rescue_count_among_tier1_empty`: **3**; `tier2_rescue_rate_among_tier1_empty`: **~0.214**
- **`breakdown_by_zone.pin_neutral`:** `tier1_nonempty` **0**, `tier2_nonempty` **0** (all eight `pin_neutral` anchors still have **empty** similarity pools under Issue 19 SQL)

**Interpretation:**

- **Improvement from restored bars** shows up in **outcome columns** and **anchor-feasibility counts**, not necessarily in **tier1/tier2 similar-set counts** for `pin_neutral`.
- **Remaining sparsity** in similarity pools is **real** under current tier definitions.
- **Non-recoverable (for outcomes)** without more history: rows in the **`$SPX`** early gap and any snapshot whose forward bar grid is still incomplete at eval time.

---

## 10. Remaining risks

1. **`$SPX` history tail at cohort start:** May need **earlier `startDate`** / extra window or documented acceptance that **~1 trading day** of `pin_neutral` `$SPX` rows stay unlabeled until Schwab range extends.
2. **Schwab API limits / 400s:** Windowing logic mitigates; re-run is idempotent via upsert.
3. **Upsert epoch rule:** Only **`bar_start <= 0`** is rejected on insert; absurdly small positive test fixtures could still be inserted in dev DBs — production Schwab paths remain the authority.

---

## 11. Exact next actions

1. Extend **`$SPX`** (and if needed **VZ**) Schwab fetch **earlier than `min(pin_neutral.ts_utc) − start_buffer`** until `pin_neutral_anchor_feasible_count == 797` or document accepted residual.
2. Re-run **`pin_neutral_outcome_repair_v1`**; target **`updates_executed`** for the remaining **190** rows.
3. Re-run **`snapshot_normalizer.py`** if further outcome updates occur.
4. Re-run **`tools/issue19_option_a_post_validate.py`** and compare JSON to `data/issue19_coverage_after_bar_rehydration_issue19_v1.json`.
5. **Calibration:** still **out of scope** until bar coverage and outcome repair are complete for the intended cohort.

---

## 12. Artifact index

| Deliverable | Path |
|-------------|------|
| Baseline audit JSON | `data/bar_rehydration_baseline_issue19_v1.json` |
| Post-rehydration audit JSON | `data/bar_rehydration_post_issue19_v1.json` |
| Repair audit JSON | `data/pin_neutral_repair_after_rehydration_issue19_v1.json` |
| Issue 19 coverage JSON | `data/issue19_coverage_after_bar_rehydration_issue19_v1.json` |
| Last full run JSON | `data/bar_rehydration_issue19_v1_last_run.json` |
| Tests | `tests/test_instrument_identity_and_repair_v1.py` |

---

## 13. Exact commands used

```text
python -m pytest tests/test_instrument_identity_and_repair_v1.py -q
python bar_rehydration_issue19_v1.py --db data/ed_console.db --skip-backup
python tools/issue19_option_a_post_validate.py --db data/ed_console.db --json-out data/issue19_coverage_after_bar_rehydration_issue19_v1.json
```

(Additionally, during remediation: manual `DELETE FROM price_bars_1m WHERE bar_start_ts_utc < 1700000000 OR bar_start_ts_utc <= 0` via `EdDB` / sqlite3, and a **`--no-repair`** rehydration pass while debugging — superseded by the final full run above.)

---

## 14. Required closing lines

- **BAR REHYDRATION EXECUTED:** YES  
- **CANONICAL TICKER IDENTITY PRESERVED:** YES  
- **REQUIRED BAR COVERAGE RESTORED:** NO — **141 / 797** `pin_neutral` rows remain anchor-infeasible; **`$SPX`** early cohort gap (~**24.5 h**) persists; **190** rows still `outcome_filled=0`.  
- **pin_neutral ANCHOR FEASIBILITY RESTORED:** YES — **656 / 797** feasible (**not** full cohort).  
- **pin_neutral HISTORY REPAIRED:** YES — **612** snapshot updates executed; **190** still unfilled.  
- **SAFE TO RE-RUN FULL COVERAGE REVIEW:** YES  
- **SAFE TO PROCEED TO CALIBRATION:** NO — finish **`$SPX`** (and residual) bar coverage and **close out** remaining `pin_neutral` **outcome_filled=0** rows first; calibration remains **out of scope** for this pass.
