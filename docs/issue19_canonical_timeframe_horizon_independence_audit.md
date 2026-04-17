# Issue 19 — Canonical timeframe + horizon independence audit

**Date:** 2026-04-03  
**Mode:** Read-only proof (no patches, no calibration).  
**Goal:** Establish whether **`1m` remains authoritative**, whether **`outcome_*` horizons are independent labels on canonical 1m truth**, whether **`5m` `pin_neutral` is legacy vs live**, and whether **missing `price_bars_1m` can be cleanly reconstructed** from higher timeframes.

---

## 1. Executive conclusion

1. **`1m` is canonical in current design and in the authoritative **price** series:** only **`price_bars_1m`** backs bar-anchor outcomes; **`CANONICAL_TIMEFRAME = "1m"`** in `timeframe_config.py`; live **`insert_snapshot`** **overrides** any non-`1m` timeframe to **`1m`** (```2123:2141:db.py```).

2. **Outcome horizons (`outcome_1c`, `outcome_5c`, `outcome_15c`, `outcome_60c`, plus `3c`/`8c`/`13c` in code)** are **distinct forward targets on the same UTC **1m** bar grid** (`forward_bar_start_utc(ts, N)` in `horizon_outcomes.py`). They are **not** read from 5m/15m/60m bar tables (those tables **do not exist** in this SQLite schema). They **share one anchor** per snapshot (last completed **`price_bars_1m`** close ≤ `ts_utc`). So: **independent forward legs on canonical 1m; not independent of each other’s anchor.**

3. **`5m` snapshot rows are not “current canonical truth” for **live** ingestion through `EdDB.insert_snapshot`:** the code path **forces `1m`**. The large **`5m`** population in **`snapshots`** (including **`pin_neutral`**) is **consistent with a legacy / alternate-ingest era**: on `data/ed_console.db` (verified **2026-04-03**), **`pin_neutral` `5m`** rows occupy **`snapshot_id` 22020–90661** (**797** rows) while **`timeframe='1m'`** rows begin at **`snapshot_id` 103664** (max/count grow on a live DB; **~39 k** `1m` rows vs **103 109** `5m` on **`data/ed_console.db`** as verified **2026-04-03**). **Exact calendar date of the `insert_snapshot` guard is not proven from DB alone** → **UNcertain** when the guard landed relative to imports, but **current code cannot persist new `5m` through this API.**

4. **Reconstruction of authoritative **`price_bars_1m`** from stored higher-timeframe OHLC in this DB:** **No** — there is **no** `price_bars_5m` / `15m` / `60m` table. **`snapshots.candle_*`** are **sparse** (only at refresh times), not a full exchange grid. **`snapshots_1m_normalized`** is **explicitly non-exchange-1m** (resampled from sub-minute rows; see `snapshot_normalizer.py` docstring).

5. **Durable policy (evidence-backed):** **A + B** — keep **`price_bars_1m`** as **sole production truth** for bar-anchor labels; treat **legacy `5m` snapshot rows** as **historical artifacts** (sub-minute-era labeling + retrieval mismatch with Issue 19 default **`1m`** anchors); any **synthetic 1m** from aggregates is **research / training convenience only**, not authoritative for **`fill_outcomes`**.

---

## 2. Scope and methodology

- **Code:** `timeframe_config.py`, `horizon_outcomes.py`, `db.py` (`insert_snapshot`, `fill_outcomes`, `fill_outcomes_pin_neutral_backfill_v1`, `_apply_bar_based_outcome_updates`, `upsert_1m_bars`), `server.py`, `snapshot_normalizer.py`, `normalized_training_sync.py`.
- **Schema:** `db.py` `CREATE TABLE` for `snapshots`, `price_bars_1m`, `snapshots_1m_normalized`.
- **Data (evidence run):** SQLite on `data/ed_console.db` — `sqlite_master` for bar tables; `MIN/MAX(snapshot_id)` for `pin_neutral` `5m` vs global `1m`.

---

## 3. Canonical timeframe contract

| Component | File / function | Value / behavior | Evidence | Verdict |
|-----------|-----------------|------------------|----------|---------|
| Constant | `timeframe_config.py` | `CANONICAL_TIMEFRAME = "1m"` | ```40:44:timeframe_config.py``` | **CONSISTENT** |
| Derived label | `timeframe_config.py` | `DERIVED_TIMEFRAME = "5m"` for “structure / legacy streams” | ```43:44:timeframe_config.py``` | **CONSISTENT** (naming; not price authority) |
| Live snapshot insert | `db.py` `insert_snapshot` | **Overrides** `snap.timeframe` to **`CANONICAL_TIMEFRAME`** if different; logs warning | ```2123:2141:db.py``` | **CONSISTENT** (live canonical enforcement) |
| Live server | `server.py` | `timeframe=CANONICAL_TIMEFRAME` in snapshot kwargs; `fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)` | ```2314:2317:server.py```, ```2576:2581:server.py``` | **CONSISTENT** |
| Live `fill_outcomes` | `db.py` `fill_outcomes` | **Returns immediately** if `timeframe != CANONICAL_TIMEFRAME` | ```2264:2265:db.py``` | **CONSISTENT** — **`5m` never live-labeled** by this function |
| Authoritative prices | `db.py` / `horizon_outcomes.py` | **`price_bars_1m`** only for anchor + forward | ```2187:2195:db.py```, ```4:12:horizon_outcomes.py``` | **CONSISTENT** |
| Repair / backfill | `db.py` `fill_outcomes_pin_neutral_backfill_v1` | Selects **`timeframe IN (1m, 5m)`**; still reads **`price_bars_1m`** for math | ```2339:2341:db.py```, ```2356:2371:db.py``` | **CONSISTENT** — repair **accepts legacy rows**; **truth** still **1m bars** |
| Normalizer fingerprint | `normalized_training_sync.py` | Fingerprint groups **`1m` + `SUBMINUTE_SOURCE_TIMEFRAME` (`5m`)** raw rows | ```67:87:normalized_training_sync.py``` | **CONSISTENT** — acknowledges **two raw snapshot timeframes** in DB |
| Normalized training table | `snapshot_normalizer.py` | Output **`timeframe='1m'`**; input may be legacy **`5m`** sub-minute | ```50:54:snapshot_normalizer.py``` | **DERIVED 1m** — **not** redefinition of **`price_bars_1m`** |

**Inconsistency (data vs current API, not vs contract text):** **`snapshots`** still contains **103 109** rows with **`timeframe='5m'`** vs **~39 020** `1m` (`data/ed_console.db`, verified **2026-04-03**; **counts drift** on live ingest). That is **INCONSISTENT with “all live inserts are 1m”** unless those **`5m`** rows were created **without** going through today’s **`insert_snapshot`** or **before** the override existed. **Verdict: LEGACY ONLY / MIXED DB** — not a proof that **`1m` lost authority**, but proof of **coexisting eras**.

---

## 4. Horizon independence audit

**Contract source:** `OUTCOME_BAR_SPECS` and `forward_bar_start_utc` in `horizon_outcomes.py`.

```38:46:horizon_outcomes.py
OUTCOME_BAR_SPECS: tuple[tuple[str, str, int], ...] = (
    ("outcome_1c", "outcome_1c_pts", 1),
    ("outcome_3c", "outcome_3c_pts", 3),
    ("outcome_5c", "outcome_5c_pts", 5),
    ("outcome_8c", "outcome_8c_pts", 8),
    ("outcome_13c", "outcome_13c_pts", 13),
    ("outcome_15c", "outcome_15c_pts", 15),
    ("outcome_60c", "outcome_60c_pts", 60),
)
```

| Horizon | Source series for forward close | Grid basis | Derived from canonical `price_bars_1m`? | Independent from other horizons? | Evidence | Verdict |
|---------|----------------------------------|------------|----------------------------------------|----------------------------------|----------|---------|
| **1c** (`N=1`) | `close_by_start[forward_bar_start_utc(ts,1)]` | UTC **1m** start times | **Yes** | Forward **minute** distinct from 5c/15c/60c; **shares anchor** with all | ```3059:3067:db.py``` + ```50:53:horizon_outcomes.py``` | **Canonical 1m forward** |
| **5c** | same pattern, `N=5` | UTC **1m** | **Yes** | Distinct forward key vs 1c/15c/60c; shared anchor | same | **Canonical 1m forward** |
| **15c** (`outcome_15c`, `N=15`) | same, `N=15` | UTC **1m** | **Yes** | Distinct forward key; **`outcome_13c`** is separate legacy column (`N=13`) | same | **Canonical 1m forward** |
| **60c** | same, `N=60` | UTC **1m** | **Yes** | Distinct forward key | same | **Canonical 1m forward** |

**Anchor (shared):** ```3053:3056:db.py``` — one `anchor_close` per snapshot from **`price_bars_1m`** `bar_end_ts_utc <= ts_utc`.

**Not used as primary source:** **5m / 15m / 60m aggregated bar tables** — **none** in `sqlite_master` (**only `price_bars_1m`** among `*bar*` tables on this DB).

**“Shortcuts”:** Horizons are **not** computed as “5m bar close” or “15m bar close”; they are **always** specific **1m** bar starts from **`ts + N minutes`** on the floor-to-minute grid.

---

## 5. Legacy vs live-era analysis

| Cohort / path | Timeframe | Era classification | Evidence | Impact on canonical truth |
|---------------|-----------|--------------------|----------|---------------------------|
| **`snapshots` `pin_neutral` `5m` (797)** | `5m` | **LEGACY HISTORICAL** (relative to current `insert_snapshot`) | **`snapshot_id` ∈ [22020, 90661]** on `data/ed_console.db`; **global `1m` rows** **`snapshot_id` ≥ 103664** (max/count grow live) | Rows are **not** authoritative **price** truth; **outcomes** still **defined** from **`price_bars_1m`** when filled |
| **Live `EdDB.insert_snapshot`** | forced `1m` | **CURRENT LIVE** | ```2133:2141:db.py``` | **Cannot** persist caller `5m` through this API today |
| **`fill_outcomes` live** | `1m` only | **CURRENT LIVE** | ```2264:2265:db.py``` | **`5m`** snapshots **not** updated by rolling fill |
| **`snapshots_1m_normalized`** | output `1m` | **DERIVED (training)** | ```1:14:snapshot_normalizer.py``` | **Does not replace** **`price_bars_1m`** for `fill_outcomes` |

**UNcertain (explicit):** **Git history / migration log** was not consulted in this pass — **cannot prove** the calendar date **`insert_snapshot` coercion** was introduced vs when **`5m`** rows were bulk-loaded.

**Live reproduction of `5m` rows:** **Not through `insert_snapshot` as written today.** Possible alternate sources: raw SQL, older binary, tests, or one-off imports — **not enumerated here** (would require `grep` / provenance outside DB).

---

## 6. Reconstruction policy audit

| Source | Authoritative `price_bars_1m`? | Approximate research-only? | Production-safe for `fill_outcomes` contract? | Evidence | Verdict |
|--------|-------------------------------|-----------------------------|-----------------------------------------------|----------|---------|
| **`price_bars_1m`** | **Yes** | N/A | **Yes** | Schema + `horizon_outcomes.py` | **Canonical** |
| **5m / 15m / 60m OHLC tables** | **No** (not present) | N/A | **No** | DB: only `price_bars_1m` | **N/A** |
| **`snapshots.candle_*` + `spot`** | **No** — sparse, not full grid | Possible ad-hoc studies | **No** under Issues 3–4 contract (“never `snapshots.spot`” for anchor/forward in bar contract text) | `horizon_outcomes.py` header | **Forbidden for authoritative labels** |
| **`snapshots_1m_normalized`** | **No** | **Yes** — resampled OHLC from sub-minute | **No** for exchange-faithful 1m | ```5:14:snapshot_normalizer.py``` | **Explicitly non-native 1m** |
| **Upsample higher TF → 1m** | **No** — information destroyed | **Yes**, with known error | **No** for production truth | No persisted multi-TF bar series to upsample in-schema | **Not clean / not available** |

**Conclusion:** **Clean production reconstruction of missing **`price_bars_1m`** from **only** higher-timeframe aggregates **in this DB** — **NO**. **Research-only approximate paths** exist in principle (e.g. normalized table, hand-built models) — **YES**, but **must not** be treated as **`price_bars_1m`** authority.

---

## 7. Durable policy recommendation

**Selected: A + B (evidence-backed)**

- **A.** **`1m` (`price_bars_1m`) remains the sole canonical truth** for **bar-anchor / forward `outcome_*`** under **`HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1`.**

- **B.** **Legacy `5m` snapshot cohorts** (especially **`pin_neutral`**) are **not** interchangeable with **live `1m` Issue 19 retrieval** without **either** migrating rows / anchors **or** explicitly defining **`5m`** as the retrieval clock for that historical slice.

- **Not C:** Current implementation **does** treat **`1m`** as authoritative for **prices** and **outcome math**; the tension is **historical snapshot `timeframe` metadata + Issue 19 SQL**, not **`price_bars_1m`** being demoted.

---

## 8. Risks of getting this wrong

- **Training on `snapshots_1m_normalized`** while **labeling** from **`price_bars_1m`** → **silent misalignment** if treated as the same object.
- **Treating legacy `5m` rows as “wrong”** and deleting them → **lose valid features** that still **could** pair with **`price_bars_1m`** labels after repair.
- **Upsampling or inventing 1m** to fill gaps → **violates** “no approximate bars” production rules from prior workstreams.

---

## 9. Exact next actions

1. **Document** in operational runbooks: **`insert_snapshot` forces `1m`**; **`5m`** in **`snapshots`** = **legacy or non-API ingest**.
2. **Product choice:** Issue 19 **`1m`** anchors vs **`5m`** historical cohort — **explicit** alignment (see `docs/issue19_pin_neutral_1m_5m_divergence_audit.md`).
3. **Continue** authoritative **`price_bars_1m`** backfill where Schwab (or allowed source) provides minutes — **only** path to **production-complete** forward grids.
4. **Do not** promote **`snapshots_1m_normalized`** or **`candle_*`** interpolation to **`fill_outcomes`** truth without a **new schema version** and contract text.

---

## 10. Commands used (DB evidence)

From repo root (PowerShell-safe):

```text
python tools/canonical_timeframe_db_evidence_v1.py data/ed_console.db
```

**Structural result (stable):** `bar_like_tables` = **`['price_bars_1m']`** only. **`pin_neutral` `5m`:** **`(22020, 90661, 797)`** — fixed legacy band. **`1m` min `snapshot_id`:** **103664** (proves non-overlap with low-id `5m` era). **`by_tf` example:** **`[('1m', ~39k), ('5m', 103109)]`** — re-run `canonical_timeframe_db_evidence_v1.py` for current counts.

---

## 11. Required closing lines

- **1M IS CANONICAL AUTHORITY:** **YES** — for **`price_bars_1m`** and live **`insert_snapshot` / `fill_outcomes`** as implemented.

- **1C/5C/15C/60C ARE TRULY INDEPENDENT FROM CANONICAL 1M:** **PARTIAL** — all are **distinct forward targets on the same canonical 1m bar grid** and **share one anchor**; they do **not** use higher-TF bar series as primary source. *(Code also defines **3c / 8c / 13c** in the same tuple.)*

- **5M pin_neutral COHORT IS LEGACY, NOT CURRENT CANONICAL TRUTH:** **YES** — **proven as legacy snapshot-era relative to current API** via **`snapshot_id` band vs `1m` floor**; **UNcertain** exact ingest mechanism/date without VCS archaeology.

- **CLEAN PRODUCTION RECONSTRUCTION OF 1M FROM HIGHER TIMEFRAMES EXISTS:** **NO** — no higher-TF bar store; **`snapshots_1m_normalized`** is **explicitly approximate / derived**.

- **RESEARCH-ONLY APPROXIMATION PATH EXISTS:** **YES** — **`snapshots_1m_normalized`** resampling (documented as non-exchange 1m).

- **DURABLE POLICY DEFINED:** **YES** — §7.

- **SAFE TO PROCEED TO CALIBRATION:** **NO**

---

## 12. Binary closure (exact lines)

- 1M IS CANONICAL AUTHORITY: YES
- 1C/5C/15C/60C ARE TRULY INDEPENDENT FROM CANONICAL 1M: PARTIAL
- 5M pin_neutral COHORT IS LEGACY, NOT CURRENT CANONICAL TRUTH: YES
- CLEAN PRODUCTION RECONSTRUCTION OF 1M FROM HIGHER TIMEFRAMES EXISTS: NO
- RESEARCH-ONLY APPROXIMATION PATH EXISTS: YES
- DURABLE POLICY DEFINED: YES
- SAFE TO PROCEED TO CALIBRATION: NO
