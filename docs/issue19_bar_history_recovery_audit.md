# Issue 19 — Bar history recovery audit (pin_neutral labeling)

**Date:** 2026-04-03  
**Mode:** read-only audit + evidence from `data/ed_console.db` and repository code.  
**No calibration. No label fabrication. No substitute bars.**

**Evidence bundle:** run `python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_history_recovery_audit_last.json` (output captured for this report).

---

## 1. Executive conclusion

1. **Required contract** for BAR_ANCHOR_V1 outcomes is **explicitly** defined in code: **only** `price_bars_1m`, canonical **60s** bars, anchor = last **`bar_end_ts_utc ≤ ts_utc`**, forward = **`close`** at **`forward_bar_start_utc`**. **`snapshots.spot` and snapshot candle fields are excluded** by that contract. This is **intentional architecture**, not an accidental quirk of one function.

2. **Why anchor bars are “missing”:** for all **797** repair-scoped `pin_neutral` rows on this database, **no** row in `price_bars_1m` exists with **`bar_end_ts_utc ≤ snapshots.ts_utc`** for the **same** `ticker`. **PROVEN:** `pin_neutral_anchor_feasible_count = 0` (see §6). There is **no** application code path that **deletes** from `price_bars_1m`; absence means **those intervals were never persisted** here (or the DB was replaced and only **recent** bars were re-ingested).

3. **Coverage gap shape:** `price_bars_1m` on this DB starts at **`min(bar_start_ts_utc) ≈ 1774877460`** globally, while `pin_neutral` snapshots run from **`≈ 1771914627` to `≈ 1773509166`**. **Every** outcome-labeled snapshot in this DB has **`ts_utc ≥` that global bar minimum** and **has** a matching anchor bar by ticker (**0** labeled rows violate anchor existence). So the gap is **temporal**: older snapshots (including all `pin_neutral` audited) sit **before** the retained bar series on this file — **not** a `pin_neutral`-only SQL bug.

4. **Alternative in-DB sources:** SQLite has **no** other table of canonical 1m OHLC bars (`price_bars_1m` only). `snapshots` carry **`candle_*`** (797/797 have `candle_close` on `pin_neutral` rows) but **must not** be used as the anchor series under the **current** written contract (`horizon_outcomes.py`). Using them would be a **contract change**, not “recovery.”

5. **Recoverability:** **From existing DB alone:** **0 / 797** rows are recoverable under the current contract. **From integrity-preserving future work:** bars can be **rehydrated** into `price_bars_1m` using the **same ingestion primitive** as production (`EdDB.upsert_1m_bars` / Schwab 1m candles), then **`fill_outcomes_pin_neutral_backfill_v1`** re-run. **Whether Schwab (or another feed) still exposes minute history for every needed interval** was **not** verified in this pass (no live API calls) → **UNCERTAIN** for **complete** coverage of all symbols/dates.

---

## 2. Scope and methodology

- **In scope:** BAR_ANCHOR_V1 labeling inputs, `price_bars_1m` lifecycle, server persistence, SQLite schema, `pin_neutral` cohort on `data/ed_console.db`.
- **Out of scope:** Implementing importers, calling Schwab in this pass, changing `horizon_outcomes` semantics.
- **Method:** static code review (`horizon_outcomes.py`, `db.py`, `server.py`, `math_exposure.py`); `grep` for `DELETE` / pruning on `price_bars_1m`; SQL on `data/ed_console.db`; `tools/bar_history_recovery_audit_v1.py`.

---

## 3. Required bar contract (pin_neutral labeling)

### 3.1 Labeling path

| Stage | Location | Role |
|--------|----------|------|
| Schema definition | `horizon_outcomes.py` | BAR_ANCHOR_V1 math: anchor + forward on **1m UTC grid**, **`price_bars_1m` only** |
| Live fill | `db.py` → `fill_outcomes` | Loads `price_bars_1m` for `ticker_storage_key(ticker)`; rolling **14d** snapshot window; **`timeframe` must be `CANONICAL_TIMEFRAME` (`1m`)** |
| Repair fill | `db.py` → `fill_outcomes_pin_neutral_backfill_v1` | Same **`_apply_bar_based_outcome_updates`** kernel; snapshots may be **`1m` or `5m`**; **still reads `price_bars_1m` only** |

Proof — authoritative contract (excerpt):

```4:12:horizon_outcomes.py
Contract (schema version 3, BAR_ANCHOR_V1):
- Anchor at snapshot time T: **close** of the last fully completed canonical 1m bar such that
  bar_end_ts_utc <= T (from price_bars_1m only; never snapshots.spot or quote-derived values).
- Forward reference at T + N minutes: **close** of the canonical 1m bar whose period
  **starts** at floor((T + N*60) / 60) * 60 (UTC epoch seconds) — unchanged from Issue 3.
- Bar length: 60 seconds (canonical 1m timeframe only).
...
Authoritative price series: persisted rows in price_bars_1m (Schwab 1m history + live accumulator).
```

### 3.2 Required source table(s)

- **`price_bars_1m` only** for anchor and forward **closes** under BAR_ANCHOR_V1.

### 3.3 Required timestamp relationships

- **Anchor:** `bisect_right(bar_ends, t_snap) - 1` on **`bar_end_ts_utc`** values loaded from `price_bars_1m` with `bar_end_ts_utc <= tz_eval` (evaluation “now” for completeness checks) and `bar_start_ts_utc >= bar_low` (see `db.py`). Requires at least one bar with **`bar_end_ts_utc ≤ t_snap`**.
- **Forward:** `close_by_start[float(forward_bar_start_utc(...))]` must exist; `bar_complete_by_utc(forward_start, tz_eval)` must be true (for repair, `tz_eval = time.time()`, so historical forwards are complete if bars exist through the forward horizon).

Proof — shared writer (excerpt):

```3023:3056:db.py
def _apply_bar_based_outcome_updates(
    conn: sqlite3.Connection,
    *,
    tz: float,
    unfilled_rows,
    bar_ends: list[float],
    bar_end_closes: list[float],
    close_by_start: dict[float, float],
) -> int:
    ...
    for row in unfilled_rows:
        snap_id = int(row["snapshot_id"])
        t_snap = float(row["ts_utc"])
        anch_idx = bisect.bisect_right(bar_ends, t_snap) - 1
        if anch_idx < 0:
            continue
        anchor_close = bar_end_closes[anch_idx]
        ...
            b_start = forward_bar_start_utc(t_snap, n_min)
            if not bar_complete_by_utc(b_start, tz):
                continue
            fwd_close = close_by_start.get(float(b_start))
            if fwd_close is None:
                continue
```

### 3.4 Ticker identity

- **`snapshots.ticker`** must match **`price_bars_1m.ticker`** after `ticker_storage_key` (e.g. `$SPX`). Repair uses `t_key = ticker_storage_key(tkr_raw)` when querying bars.

### 3.5 Timeframe compatibility (`snapshots.timeframe` vs bars)

- **`snapshots.timeframe = '5m'`** denotes **legacy snapshot cadence** (sub-minute source clock), **not** a request to use 5-minute bar closes for anchor math. Comments in `fill_outcomes_pin_neutral_backfill_v1` state labeling **still uses** the **1m grid** in `price_bars_1m` — consistent with `horizon_outcomes.py` (“canonical 1m timeframe only”).

Proof (excerpt):

```2327:2332:db.py
        Same bar-anchor contract as fill_outcomes. Evaluation time is wall-clock now
        so forward horizons are complete when 1m bar history exists.

        Scope: zone='pin_neutral', outcome_filled=0, BAR_ANCHOR_V1, timeframe in {1m, 5m}.
        Includes legacy ``timeframe='5m'`` snapshot rows (sub-minute source clock); labeling
        still uses ``price_bars_1m`` bar grid from ``horizon_outcomes`` (same as ``fill_outcomes``).
```

### 3.6 Intentional vs accidental use of `price_bars_1m`

- **Intentional:** documented in `horizon_outcomes.py`, `timeframe_config.py`, migrations in `db.py` (Issue 3/4 invalidation copy), and `SnapshotRow` / `fill_outcomes` docstrings. **Not** a stray implementation detail.

---

## 4. Missing-bar root-cause audit

| Layer | File / function | Role | Evidence | Possible cause | Verdict |
|--------|-----------------|------|----------|----------------|---------|
| Authoritative store | `db.py` `price_bars_1m` DDL + `upsert_1m_bars` | Sole persisted 1m bar table; upsert by `(ticker, bar_start_ts_utc)` | Schema + `INSERT ... ON CONFLICT DO UPDATE`; **no** `DELETE` anywhere in repo (`grep`) | N/A | **PROVEN** sole canonical store |
| Persistence driver | `server.py` `_fetch_state` | After snapshot insert, `upsert_1m_bars(ticker, _candles_1m.get_bars(ticker))` | ```2575:2580:server.py``` | Only persists what the in-memory accumulator holds | **PROVEN** |
| In-memory cap | `server.py` `_CandleAccumulator` + `math_exposure.CANDLE_1M_MAX_BARS` | Rolling completed-bar deque per ticker, **max 390** | ```19:20:math_exposure.py``` `CANDLE_1M_MAX_BARS: int = 390`; ```518:519:server.py``` truncates | Limits **RAM** history, not SQLite row count | **PROVEN** |
| Seed window | `server.py` seed path | If no bars, `safe_get_price_history(..., frequency_minutes=1, period_days=1)` | ```1416:1431:server.py``` | **~1 trading day** of Schwab 1m per cold start | **PROVEN** |
| SQLite pruning | (none found) | — | No `DELETE FROM price_bars_1m` in `.py` | — | **PROVEN: no app-level prune** |
| Outcome vs bars alignment | SQL on `data/ed_console.db` | Consistency check | **0** labeled snapshots with `ts_utc < min(bar_start_ts_utc)` globally; **0** labeled rows missing anchor bar by ticker | Labels only exist where bars exist on this file | **PROVEN** |
| `pin_neutral` vs bars | `bar_history_recovery_audit_v1.py` | Per-ticker `min_snap_ts` vs `min(bar_start)` | All `pin_neutral` **`min_snap_ts` < `bars_min_start`** where bars exist; **4** tickers have **0** bar rows | Bars for those symbols **never** written | **PROVEN** gap is **missing historical persistence**, not pin-specific filtering |

**Synthesis (root cause):** On this database, **`price_bars_1m` does not contain 1m bars that extend back to `pin_neutral` snapshot times.** The pipeline **only writes** bars when the server runs `upsert_1m_bars` from the **rolling** accumulator (seeded from **1-day** Schwab 1m). There is **no** evidence of deletion; the **parsimonious** explanation is **never ingested for those timestamps** on this file (or DB rebuilt and only recent activity repopulated bars).

---

## 5. Recovery source inventory

| Source | Coverage (this DB) | Timeframe | Ticker key | Integrity vs contract | Truthful recovery under **current** contract? | Verdict |
|--------|--------------------|-----------|------------|-------------------------|-----------------------------------------------|---------|
| **`price_bars_1m`** | 24 383 rows; 19 tickers; global `min(bar_start_ts_utc) ≈ 1774877460` | 1m (`bar_end = start+60`) | As stored (e.g. `$SPX`) | **Canonical** per `horizon_outcomes.py` | **Yes** for rows where anchor+forward bars exist | **YES** (when populated) |
| **`snapshots` `candle_*`** | `797/797` `candle_close` set on scoped `pin_neutral` | Not native exchange 1m bar table; mixed cadence | N/A | **Explicitly excluded** from anchor in BAR_ANCHOR_V1 | **No** without **changing** the written contract | **NO** |
| **`snapshots_1m_normalized`** | Derived from `snapshots` bucketing; not native 1m candles | Synthetic 1m bucket | Same as snapshots | Documented as **derived**, not authoritative exchange 1m | **No** as drop-in for `price_bars_1m` closes | **NO** |
| **Other SQLite tables** | `grep` of `sqlite_master` | — | — | No other `*bar*` / `price_*` price history | **No** | **NO** |
| **Schwab `get_price_history` (1m)** | Not queried in this audit | API 1m | Symbol as requested | Same family as live seed | **Yes** *if* API returns data for needed ranges (unverified here) | **UNCERTAIN** (availability) |

---

## 6. Recoverability classification (`pin_neutral` repair scope, `data/ed_console.db`)

**Scope:** `zone='pin_neutral'`, `outcome_filled=0`, `horizon_outcome_schema_version=3`, `timeframe ∈ {1m,5m}` → **n = 797** (all **`5m`**).

| Class | Definition | Count | Evidence |
|--------|------------|------:|----------|
| **RECOVERABLE FROM EXISTING CANONICAL BARS** | `EXISTS` `price_bars_1m` row with `ticker = snapshots.ticker` and `bar_end_ts_utc ≤ ts_utc` | **0** | `pin_neutral_anchor_feasible_count` |
| **RECOVERABLE FROM VALID DERIVATION (within current contract)** | Reconstruct **`price_bars_1m`** from another **authoritative** 1m feed, then re-run repair | **797** *conditionally* | No in-DB source; **Schwab (or equivalent) re-import** matches `upsert_1m_bars` design — **not executed here** |
| **NOT CURRENTLY RECOVERABLE** | No anchor bar in DB; no other allowed source | **797** | Same as infeasible count |
| **UNCERTAIN (external)** | Broker/API may not retain all symbols or deep history | **Unknown** | No API calls in this pass |

**Clustering:**

- **Time:** `ts_utc` **min ≈ 1771914627**, **max ≈ 1773509166**; **all** before earliest stored bars for tickers that have bars (`min_snap_minus_min_bar_start_sec` **negative** in audit JSON).
- **Tickers:** `$SPX`(183), SPY(541), AMZN(35), MSFT(21), META(11), NVDA(2), COP/KO/UUUU/VZ(1 each with **0** bar rows in `price_bars_1m`).
- **Breadth:** **Not** confined to one symbol; **systemic** on this file for **“old snapshots vs young bar table.”**

**Meaningful pool repair?** After **successful** bar rehydration for the needed intervals, **`fill_outcomes_pin_neutral_backfill_v1`** can label rows **deterministically** per existing code. **Material improvement** depends on **obtaining** that history — **not** proven here.

---

## 7. Exact next repair path (justified)

**Recommended (durable):** **B + C** — **extend historical loading** into `price_bars_1m` via a **controlled ETL** (script or job) that:

1. For each **`(ticker, min_ts, max_ts)`** needed by repair cohorts (here: per-ticker `min_snap_ts` / `max_snap_ts` from audit JSON), fetches **Schwab 1m** candles (or another **explicitly approved** authoritative feed) with **`period` / paging** appropriate to span the gap — **not** limited to `period_days=1` as in cold seed.
2. Normalizes to the same shape as `upsert_1m_bars` (60s bars, UTC starts).
3. **`EdDB.upsert_1m_bars`** in batches with **DB backup** and **idempotent** upserts.
4. Re-run **`python pin_neutral_outcome_repair_v1.py --db …`**.
5. If outcomes change, run **`python snapshot_normalizer.py`** (materialize per project norms).

**Why this path:** It respects **`horizon_outcomes.py`** (no invented anchors), reuses **`upsert_1m_bars`**, and matches the **documented** authoritative source family.

**What NOT to do:**

- Do **not** label from **`snapshots.candle_close`** or **normalized** synthetic OHLC **without** a **versioned contract change** and migration plan.
- Do **not** assume **`period_days=1`** seeding is sufficient for historical repair.
- Do **not** treat **UNCERTAIN** API depth as **PROVEN** full coverage — validate per symbol/range after fetch.

**Validation after next step:**

- Re-run `tools/bar_history_recovery_audit_v1.py` → `pin_neutral_anchor_feasible_count` should rise toward **797** (subject to API).
- Re-run repair CLI → `updates_executed > 0` where bars suffice for forward horizons.
- Spot-check rows: `outcome_1c` non-null, `horizon_outcome_schema_version=3`.
- Re-run `tools/issue19_option_a_post_validate.py` for pool metrics.

---

## 8. Risks of faking or approximating recovery

- **Using snapshot candles as `price_bars_1m`:** violates the **written** BAR_ANCHOR_V1 contract; mixes **poll-time** OHLC with **exchange 1m grid** definitions; **not** integrity-preserving under current docs.
- **Downsampling 5m to 1m:** invents intra-bar structure; **rejected** unless the product defines a **new** schema version and math.
- **Partial Schwab history:** some rows may remain unlabeled → must be reported as **residual** with reason (`no_bar_at_forward_start`, etc.), not silently scored.

---

## 9. Exact next actions

1. **Prove API depth:** for each ticker in `per_ticker_pin_neutral_vs_bars`, call Schwab (or chosen feed) for 1m history covering **`[min_snap_ts_utc, max_snap_ts_utc + 60m]`** (or full DB gap); record **HTTP payload metadata** (period, bar count).
2. **Implement controlled `price_bars_1m` rehydration** using **`upsert_1m_bars`** + backup.
3. Re-run **`bar_history_recovery_audit_v1.py`** and **`pin_neutral_outcome_repair_v1.py`**.
4. Update **`docs/issue19_repair_implementation_report.md`** counters after evidence.

---

## Required closing lines

- REQUIRED BAR CONTRACT PROVEN: **YES**
- MISSING BAR ROOT CAUSE PROVEN: **YES**
- ALTERNATIVE RECOVERY SOURCE FOUND: **NO**
- MEANINGFUL pin_neutral HISTORY RECOVERY POSSIBLE: **NO**
- SAFE TO IMPLEMENT BAR-RECOVERY PHASE: **YES**
- SAFE TO PROCEED TO CALIBRATION: **NO**
