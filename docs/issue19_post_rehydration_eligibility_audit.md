# Issue 19 — Post-rehydration eligibility and remaining-gap audit

**Date:** 2026-04-03  
**Database:** `data/ed_console.db`  
**Scope:** Bar gap closure attempt, `pin_neutral` repair rerun, Issue 19 similarity eligibility trace, root-cause matrix (A–H), forward RTH pipeline evidence. **No calibration.**

---

## 1. Executive conclusion

1. **Lead-in anchor gap (Schwab window):** A **72-hour `--start-buffer-sec` (259200)** top-up **closed** the earlier **$SPX** lead-in problem in the **audit sense**: for the **190** still-unfilled `pin_neutral` rows, **`pin_neutral_anchor_feasible_count` became 190 / 190** (see §3). Global `price_bars_1m` **`min(bar_start_ts_utc)`** moved **1771848000 → 1771808400**; row count **48101 → 50514** (see §3).

2. **Structural bar hole (forward labeling):** There remains a **multi-day region with zero `$SPX` 1m bars** between the last bar that ends before the earliest cohort snapshot time and the start of the next stored segment. **Evidence:** for sample snapshot `ts_utc ≈ 1772974856.29`, **`MAX(bar_end_ts_utc) WHERE bar_end <= ts` = 1772835780**; **count of `$SPX` bars with `bar_start` strictly between that anchor region and 1773063000 = 0** (re-run 2026-04-03). Therefore **`outcome_1c` forward grid minutes in that window do not exist in `price_bars_1m`**, so **`fill_outcomes_pin_neutral_backfill_v1` cannot produce a full `OUTCOME_BAR_SPECS` update** for those rows → **`updates_executed` stayed 0** after top-up (§4).

3. **Issue 19 “tier1/tier2 pool = 0” for `pin_neutral`:** **Proven primary cause: timeframe mismatch (F).** All **797** historical `pin_neutral` rows in BAR_ANCHOR scope are **`timeframe = '5m'`**; Issue 19 **`_count_tier_sql`** and **`get_similar_setups`** filter on **`snapshots.timeframe = anchor.timeframe`**, and survivorship anchors default to **`'1m'`** → **official tier counts remain 0** even when **`outcome_1c` is populated on `5m`** (§5–6). **Counterfactual:** if the same SQL used **`5m`**, **SPY** `pin_neutral` tier pools are **non-zero** (e.g. tier1 **192 / 140** for above/below anchors) per `data/pin_neutral_eligibility_funnel_post_topup_v1.json`.

4. **`$SPX` on `5m`:** Even under the **5m counterfactual**, **`$SPX` pin_neutral tier1/tier2 remain 0** → additional **vwap_side and/or distance-bucket (tier1/tier2) mismatch (E / G)** for labeled rows vs anchor distances (§6).

5. **Forward RTH:** **By design**, live snapshots use **`timeframe = CANONICAL_TIMEFRAME` (`'1m'`)** and **`fill_outcomes(..., CANONICAL_TIMEFRAME, ...)`** runs each refresh. **`5m` rows are not filled by that path.** This DB snapshot shows **zero** `pin_neutral` **`1m`** rows in the **last 14 days** (`data/rth_pin_neutral_health_probe_v1.json`), so **empirical “recent RTH pin_neutral behavior” is not demonstrated on this file** — **PARTIAL** health (§7).

---

## 2. Scope and methodology

| Phase | Method |
|-------|--------|
| Bar gap | Compare `data/bar_audit_pre_gap_topup_issue19_v1.json` vs `data/bar_audit_post_gap_topup_issue19_v1.json`; Schwab rehydration via `bar_rehydration_issue19_v1.py --start-buffer-sec 259200 --no-repair`. |
| Repair | `pin_neutral_outcome_repair_v1.py` (with/without `--skip-backup`); audit JSON. |
| Eligibility | `tools/pin_neutral_eligibility_funnel_v1.py` (funnel + anchor vs `5m` counterfactual); `tools/issue19_option_a_post_validate.py` for official tier replication. |
| RTH | Code trace `server.py` + `db.py`; `tools/rth_pin_neutral_health_probe_v1.py` on live DB. |
| SQL spot checks | Unfilled counts by ticker/timeframe; `$SPX` gap bar count (executed during report finalization). |

---

## 3. Remaining bar-gap audit

### 3.1 Pre top-up (unfilled cohort still had anchor infeasibles)

**File:** `data/bar_audit_pre_gap_topup_issue19_v1.json`

| Metric | Value |
|--------|--------|
| `price_bars_1m_global.n_rows` | 48 101 |
| `min_bar_start_ts_utc` | 1 771 848 000 |
| `max_bar_end_ts_utc` | 1 775 237 880 |
| `pin_neutral_scope` (unfilled) | **190** |
| `pin_neutral_anchor_feasible_count` | **49** |
| `pin_neutral_anchor_infeasible_count` | **141** |
| **$SPX** `min_snap_minus_min_bar_start_sec` | **−88 143.71** (~24.5 h lead-in) |

### 3.2 Post top-up (same command family, `start_buffer_sec = 259200`)

**Command:**

```text
python bar_rehydration_issue19_v1.py --db data/ed_console.db --skip-backup --start-buffer-sec 259200 --no-repair
```

**File:** `data/bar_audit_post_gap_topup_issue19_v1.json`

| Metric | Value |
|--------|--------|
| `price_bars_1m_global.n_rows` | **50 514** |
| `min_bar_start_ts_utc` | **1 771 808 400** |
| `max_bar_end_ts_utc` | 1 775 238 300 |
| `pin_neutral_anchor_feasible_count` (unfilled scope) | **190** |
| `pin_neutral_anchor_infeasible_count` | **0** |
| **$SPX** `bars_min_start_ts_utc` | **1 772 721 000** |
| **$SPX** `min_snap_minus_min_bar_start_sec` | **+253 856.29** |

**Bars written (orchestrator):** `total_bar_dicts_upserted` = **15 048** for that run (see `data/bar_rehydration_issue19_v1_last_run.json` after the top-up).

### 3.3 Verdict on “gap closed”

| Question | Result |
|----------|--------|
| **EXISTS anchor** (`bar_end_ts_utc <= ts_utc`) for all 190 unfilled? | **Yes** (post top-up audit). |
| **Continuous 1m coverage** through snapshot + forward horizons for **$SPX**? | **No** — **0** bars in the strict interval between last pre-snap bar end and the old cohort segment (SQL check; §1). |

So: **lead-in / audit anchor feasibility: closed; authoritative dense grid for labeling through the hole: not closed.**

---

## 4. `pin_neutral` repair rerun results

### 4.1 Runs after top-up

| Run | `snapshots_scanned` | `updates_executed` | Notes |
|-----|---------------------|-------------------|--------|
| With backup | 190 | **0** | `data/backups/ed_console.pre_pin_neutral_outcome_repair_v1.1775237975.db` |
| After `bar_low` widening (see §4.2) | 190 | **0** | `data/pin_neutral_repair_post_topup_issue19_v2.json` |

### 4.2 Code fix: repair prefetch window

**Issue:** `fill_outcomes_pin_neutral_backfill_v1` used **`bar_low = min_ts - 5000`**, which **excludes** valid anchor bars when **`bar_start` is more than ~83 minutes before `min_ts`** — fatal when a **multi-day Schwab hole** exists (anchor bar ends at **1772835780**, snapshot at **1772974856**, anchor `bar_start` ≪ `min_ts - 5000`).

**Change:** widen to **120 days**:

```2381:2387:c:\Users\evarg\Documents\Trading\EdWebConsole\db.py
            for tkr_raw, trows in sorted(by_ticker.items()):
                t_key = ticker_storage_key(tkr_raw)
                min_ts = min(float(x["ts_utc"]) for x in trows)
                # Historical pin_neutral rows can sit days/weeks after the last stored 1m bar before
                # rehydration; a 5000s window drops valid anchor bars (bar_start < min_ts-5000).
                bar_low = min_ts - 120.0 * 86400.0
                bar_high = tz + bar_pad
```

**Test:** `tests/test_instrument_identity_and_repair_v1.py::test_pin_neutral_backfill_bar_low_uses_wide_lookback`.

### 4.3 Why `updates_executed` is still 0

Shared writer **`_apply_bar_based_outcome_updates`** requires, for **each** horizon, a **forward** `close_by_start` at the **exact 1m grid** `forward_bar_start_utc(ts, N)` (`horizon_outcomes.py`). **Missing any required bar** → incomplete `updates` → either no UPDATE or **`outcome_filled` stays 0**. For **$SPX** in the hole, **`outcome_1c` grid minute absent** (forward `bar_start` **1772974860** not in table) → **no full repair**.

### 4.4 Current unfilled distribution (DB, 2026-04-03)

| ticker | timeframe | n |
|--------|-----------|---|
| $SPX | 5m | 183 |
| SPY | 5m | 2 |
| COP, KO, META, UUUU, VZ | 5m | 1 each |

**Total `outcome_filled = 0`:** **190**. All **`horizon_outcome_schema_version` = BAR_ANCHOR_V1** in scope.

**Normalized refresh:** Not run for this pass (`updates_executed = 0`).

---

## 5. `pin_neutral` eligibility funnel / filter trace

**Source:** `data/pin_neutral_eligibility_funnel_post_topup_v1.json`

| Stage | Count | Meaning |
|-------|------|---------|
| 1. Total `pin_neutral` (BAR_ANCHOR, 1m+5m) | **797** | Full historical cohort |
| 2. `outcome_filled = 1` | **607** | Backfill-complete flag |
| 2b. `outcome_filled = 0` | **190** | Still incomplete |
| 3. `timeframe = 1m` | **0** | **No 1m `pin_neutral` rows in this cohort** |
| 3b. `timeframe = 5m` | **797** | Entire cohort is **5m** |
| 4. `outcome_1c` NOT NULL, **1m** | **0** | Nothing for Issue 19 “as wired” |
| 4b. `outcome_1c` NOT NULL, **5m** | **609** | Labeled on **5m** rows |
| 5. Unfilled, no anchor bar | **0** | Post top-up |
| 5b. Unfilled, anchor exists, still not filled | **190** | Forward / partial horizon block |

**Official Issue 19 tier counts (anchor timeframe = `1m`):** **0** for all eight `pin_neutral` anchors (same JSON).

**Counterfactual tier counts (`timeframe = 5m`):**

| Anchor | Tier1 (5m) | Tier2 (5m) |
|--------|------------|------------|
| SPY above / below | 192 / 289; 140 / 148 | Non-zero |
| QQQ, $SPX, IWM pin_neutral | **0** | **0** |

**Where the count goes to zero for Issue 19 “official” path:** **Step 3 → 4**: **`timeframe = 1m` pool is empty** (0 rows), so **tier SQL never sees candidates**.

**Where it goes to zero for `$SPX` even on 5m:** After fixing timeframe in SQL, **tier1/tier2 still 0** → **distance / vwap filters** eliminate all labeled `$SPX` `pin_neutral` rows for those anchors (**E / G**).

---

## 6. Root cause of zero `pin_neutral` pools (A–H)

| ID | Hypothesis | Yes? | Evidence | Severity | Primary? |
|----|------------|------|----------|----------|----------|
| **A** | Remaining unlabeled | **Yes** | **190** `outcome_filled = 0` | High | Blocks **full** history repair |
| **B** | Missing bar coverage | **Partial** | Anchor EXISTS fixed; **0** `$SPX` bars in forward hole | High | **Primary for repair** on **$SPX** |
| **C** | Ticker mismatch | **No** | `$SPX` / `ticker_storage_key` aligned in upsert + snapshots | None | — |
| **D** | Zone mismatch | **No** | Rows are `zone = pin_neutral` | None | — |
| **E** | `vwap_side` mismatch | **Yes** for **$SPX** | **0** counterfactual tier rows on **5m** for `$SPX` anchors | Medium | **Co-primary for $SPX pools** |
| **F** | **Timeframe mismatch** | **Yes** | **797** rows on **5m**; anchors + SQL use **1m**; **0** labeled **1m** `pin_neutral` | **Critical** | **Primary for Issue 19 tier = 0** |
| **G** | Tier SQL over-constraint | **Yes** for **$SPX** | Tier1 needs both distance buckets; **0** rows even tier2 path for `$SPX` | Medium | Secondary vs F for SPY |
| **H** | Other | — | e.g. `get_similar_setups` also needs `outcome_1c` + tier viability | Low | — |

**Distinction (user request):**

- **Data repair:** Bars + outcome columns in `snapshots` / `price_bars_1m`.
- **Eligibility:** Row matches anchor **ticker, timeframe, zone, vwap_side, distances** for tier SQL.
- **Retrieval:** `get_similar_setups` / Issue 19 counts > 0.
- **Calibration:** Out of scope; not started.

---

## 7. Forward RTH health check

### 7.1 Live producer path

- **`server.py`** builds `SnapshotRow` with **`timeframe=CANONICAL_TIMEFRAME`** (must be **`'1m'`**; guarded in server).

```2314:2317:c:\Users\evarg\Documents\Trading\EdWebConsole\server.py
                _snapshot_kwargs = dict(
                    ticker=ticker,
                    timeframe=CANONICAL_TIMEFRAME,
```

### 7.2 Labeling path

- After insert: **`_ed_db.fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)`**.

```2576:2581:c:\Users\evarg\Documents\Trading\EdWebConsole\server.py
                _bars_persist = _candles_1m.get_bars(ticker)
                if _bars_persist:
                    _ed_db.upsert_1m_bars(ticker, _bars_persist)
            except Exception as _pe:
                log.warning("upsert_1m_bars %s: %s", ticker, _pe)
            _ed_db.fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)
```

### 7.3 `5m` gap

- **`fill_outcomes`** returns immediately if **`timeframe != CANONICAL_TIMEFRAME`**.

```2264:2265:c:\Users\evarg\Documents\Trading\EdWebConsole\db.py
        if timeframe != CANONICAL_TIMEFRAME:
            return
```

So **historical-style `5m` `pin_neutral` rows will never be labeled by the live loop**; only **`fill_outcomes_pin_neutral_backfill_v1`** (or future work).

### 7.4 Rolling window

- Live fill considers snapshots with **`ts_utc` in (now−14d, now)** (`db.py` `fill_outcomes`).

### 7.5 Empirical probe on this DB

**File:** `data/rth_pin_neutral_health_probe_v1.json`

- **`pin_neutral` + `1m` + last 14d:** **0** rows.  
- **`pin_neutral` + `1m` + `market_session = rth` + last 14d:** **0** rows.

**Assessment:** **Design = healthy for future `1m` `pin_neutral`**. **This database does not contain recent examples**, so **operational health is PARTIAL / not empirically proven here.**

**Risks:** (1) **`upsert_1m_bars` / Schwab path regressions** (previously fixed `datetime` key). (2) **Retention**: only **~14 days** of snapshots get live `fill_outcomes`; older **`1m`** rows need backfill. (3) **Bar gaps** (weekends, API limits) can still block forward horizons until bars exist.

---

## 8. Remaining blockers

1. **Ingest authoritative `$SPX` (and any other) minutes across the calendar hole** *or* accept **non-recoverable** rows under the current bar-only contract.
2. **Decide product contract:** either **migrate Issue 19 anchors / similarity SQL to include `5m`** where history lives, or **backfill `1m` snapshot rows** for `pin_neutral` (large migration).
3. **Align `$SPX` survivorship distances / `vwap_side`** with empirical `pin_neutral` distributions **or** relax tiers for `$SPX`.
4. **Re-run `pin_neutral_outcome_repair_v1`** after (1); then **`snapshot_normalizer.py`** if `updates_executed > 0`.

---

## 9. Exact next actions

1. Fetch additional Schwab (or other allowed) **`$SPX`** minute history **covering** **[1772835780, 1773063000)** UTC (or equivalent session grid) **without** synthetic bars.
2. Re-run **`pin_neutral_outcome_repair_v1`**; confirm **`updates_executed > 0`** for affected IDs.
3. **Either** change **`_count_tier_sql` / anchors to `5m` for pin_neutral** **or** document that **`1m`-only Issue 19 pools exclude this cohort by design**.
4. Re-run **`tools/issue19_option_a_post_validate.py`** and **`tools/pin_neutral_eligibility_funnel_v1.py`**; archive JSONs.

---

## 10. Deliverables index

| Artifact | Path |
|----------|------|
| Bar audit (pre top-up) | `data/bar_audit_pre_gap_topup_issue19_v1.json` |
| Bar audit (post top-up) | `data/bar_audit_post_gap_topup_issue19_v1.json` |
| Repair audit (post top-up attempts) | `data/pin_neutral_repair_post_topup_issue19_v2.json` |
| Eligibility funnel (pre) | `data/pin_neutral_eligibility_funnel_pre_topup_v1.json` |
| Eligibility funnel (post) | `data/pin_neutral_eligibility_funnel_post_topup_v1.json` |
| Issue 19 coverage (post top-up) | `data/issue19_coverage_post_topup_issue19_v1.json` |
| RTH probe | `data/rth_pin_neutral_health_probe_v1.json` |
| Funnel tool | `tools/pin_neutral_eligibility_funnel_v1.py` |
| RTH probe tool | `tools/rth_pin_neutral_health_probe_v1.py` |
| Test | `tests/test_instrument_identity_and_repair_v1.py::test_pin_neutral_backfill_bar_low_uses_wide_lookback` |

---

## 11. Exact commands used

```text
python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_audit_pre_gap_topup_issue19_v1.json
python bar_rehydration_issue19_v1.py --db data/ed_console.db --skip-backup --start-buffer-sec 259200 --no-repair
python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_audit_post_gap_topup_issue19_v1.json
python pin_neutral_outcome_repair_v1.py --db data/ed_console.db
python pin_neutral_outcome_repair_v1.py --db data/ed_console.db --skip-backup
python tools/pin_neutral_eligibility_funnel_v1.py --db data/ed_console.db --json-out data/pin_neutral_eligibility_funnel_post_topup_v1.json
python tools/issue19_option_a_post_validate.py --db data/ed_console.db --json-out data/issue19_coverage_post_topup_issue19_v1.json
python tools/rth_pin_neutral_health_probe_v1.py --db data/ed_console.db --json-out data/rth_pin_neutral_health_probe_v1.json
python -m pytest tests/test_instrument_identity_and_repair_v1.py -q
```

---

## 12. Required closing lines

- **REMAINING BAR GAP CLOSED:** **NO** — **anchor-feasibility** gap for the 190-row cohort is **closed**; **dense forward 1m grid** for **$SPX** in the affected calendar region is **not** (0 bars in the verified hole).

- **pin_neutral REPAIR COMPLETE:** **NO** — **190** rows **`outcome_filled = 0`**; **`updates_executed = 0`** on post–top-up repair runs.

- **pin_neutral ELIGIBLE FOR ISSUE19 RETRIEVAL:** **NO** — official **`1m`** tier pools **0**; cohort is **`5m`**.

- **ZERO pin_neutral POOLS ROOT CAUSE PROVEN:** **YES** — **F (timeframe)** is the **dominant** explanation; **E/G** for **`$SPX`**; **B** explains **repair** failure on **$SPX**.

- **FORWARD RTH pin_neutral PIPELINE HEALTHY:** **PARTIAL** — **code path** supports **`1m` + `fill_outcomes`**; **this DB** shows **no** recent **`1m` `pin_neutral`** in **14d**; **`5m`** not live-labeled.

- **SAFE TO RE-RUN FULL COVERAGE REVIEW:** **YES**

- **SAFE TO PROCEED TO CALIBRATION:** **NO**
