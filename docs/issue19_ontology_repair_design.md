# Issue 19 — Ontology repair design (root cause + durable fix plan)

**Mode:** repair-design and root-cause only — **no retrieval patches, no calibration, no broad code changes** in this document.  
**Evidence:** `market_state.py`, `db.py` (`fill_outcomes`), `horizon_outcomes.py`, `adaptive_shadow_v2_calibration.py`, `price_bars_1m` / `snapshots` queries on `data/ed_console.db`, helper script `tools/_diag_pin_neutral_outcomes.py`.

---

## 1. Executive conclusion

| Blocker | Proven root cause (summary) | Repair class |
|---------|------------------------------|--------------|
| **Unlabeled `pin_neutral`** | **Not** excluded by zone in labeling code. Rows match **BAR_ANCHOR_V1** (`horizon_outcome_schema_version = 3`) but **`outcome_filled = 0`** and **`outcome_1c` IS NULL** for all **797** rows. **`fill_outcomes` only selects unfilled snapshots with `ts_utc` in `(now − 14 days, now)`**; **zero** `pin_neutral` rows fall in that window on the audited DB run (**newest `pin_neutral` ~20 days old**). **Effect:** the live labeling loop **never visits** these rows today — **implicit starvation** of the backfill path, not a `pin_neutral`-specific predicate. **UNCERTAIN (secondary):** whether bars/anchor logic failed during the historical 14-day window when each row was “fresh” — requires per-`snapshot_id` replay against `price_bars_1m`. | **Data/backfill job** with extended or full-history eligibility + bar join validation; optional **policy** change to rolling window for ops. |
| **`SPX` vs `$SPX`** | **`snapshots.ticker`** and **`price_bars_1m.ticker`** use **`$SPX`** (7888 snapshot rows; bars distinct query returns `('$SPX',)`). **`load_survivorship_anchors_v1`** strips a leading `$`, producing anchor ticker **`SPX`**. **`get_similar_setups`** uses **`ticker = ?`** **exact** match → **0 rows** for anchor queries using `SPX`. | **Single canonical instrument key** shared by **snapshots, bars, anchors, and diagnostics** — either **normalize storage + bars + all FK-like joins** to one string, or **stop stripping `$` in anchor/query path** and treat broker symbol as canonical. **Cannot** change only anchors without aligning bars (see §4). |
| **`zone` vs `regime_primary`** | **Semantically distinct** in code: `zone` = `derive_zone(bias, net_delta)` structural pin/expansion class; `regime_primary` = `regime_engine` environment family. **Issue 19 structural SQL uses `zone` only**, not `regime_primary`. **Risk** is **narrative / documentation / human** conflation (“pinning regime” vs `pin_neutral` zone) and UI text that juxtaposes both without explicit labels. | **Documentation + naming hygiene** in reports/diagnostics; **no mandatory retrieval change** for separation (logic already separate). |

---

## 2. Scope and methodology

- **In scope:** the three audited blockers; labeling pipeline for outcomes; ticker join between `snapshots` and `price_bars_1m`; shadow/calibration **inputs** only where they repeat the ticker bug.
- **Out of scope:** changing Issue 19 SQL text, tier thresholds, or adaptive calibration weights (explicit program boundary).
- **Method:** read implementation of `fill_outcomes`, schema version constants, anchor loader, and run read-only SQL + `tools/_diag_pin_neutral_outcomes.py`.

---

## 3. Phase 1 — `pin_neutral` unlabeled history

### 3.1 PIN_NEUTRAL ROOT CAUSE table

| file | function | role | evidence | effect on labeling | verdict |
|------|----------|------|----------|-------------------|---------|
| `market_state.py` | `derive_zone` | **Produces** `pin_neutral` from `bias_signal ∈ {balanced, neutral}` or **default** fallback | Lines 44–72 | Value is **written** to `SnapshotRow.zone` like any other zone | **Live ontology is real** |
| `server.py` | snapshot `SnapshotRow` build | **Persists** `ms.zone` | Region ~2359 `nearest_above_dist` kwargs | `pin_neutral` **stored** | **Storage path works** |
| `db.py` | `fill_outcomes` | **Only** mechanism under review for bar-based label writes on live path | Lines 2239–2355 | **No `zone` filter** in SQL — `pin_neutral` **not** explicitly skipped | **Not intentional anti–pin_neutral** |
| `db.py` | `fill_outcomes` unfilled query | **Eligibility** | `WHERE ticker=? AND timeframe=? AND outcome_filled=0 AND horizon_outcome_schema_version = BAR_ANCHOR_V1 AND ts_utc < ? AND ts_utc > ?` with `?` = `(now, now−14d)` | Snapshots **older than 14 days** are **never selected** | **Implicit exclusion** of stale rows |
| `horizon_outcomes.py` | `HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1` | Schema **3** | Constant `= 3` | Required for fill | **pin_neutral rows have v=3** (diag) |
| `server.py` | post-insert | Calls `fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)` | ~2581 | Uses **wall-clock `now`** as `ts_utc` bound, not per-row replay | **Rolling window** tied to **each server invocation** |

**DB facts (audited run, `tools/_diag_pin_neutral_outcomes.py`):**

- `pin_neutral` **797** rows; **`horizon_outcome_schema_version` = 3** for all 797.
- **`outcome_filled` = 0** for all 797; **`outcome_1c` NULL** for all 797.
- **Rows in approximate `fill_outcomes` window** `(now−14d, now)`:** 0**.
- **Newest** `pin_neutral` `ts_utc` ≈ **20 days** before diagnostic `now` (**outside** window).

### 3.2 Accidental vs intentional

- **Rolling 14-day lookback** in `fill_outcomes` is **intentional for operational scope** (performance / bounded bar prefetch — inferred from structure; **not** documented as “drops history forever” in docstring).
- **Side effect:** any snapshot that **never** receives a successful label update while it remains inside successive 14-day windows **will age out** and **never be processed again** by this function — **accidental archival gap** relative to “complete historical labels” goal.

### 3.3 Can `pin_neutral` be labeled under the same framework?

**Yes.** Same columns, same BAR_ANCHOR_V1 contract, same `classify_direction`; **no** code path asserts `zone != pin_neutral` for outcomes.

### 3.4 Is raw data sufficient to regenerate labels?

**Conditionally yes:** if `price_bars_1m` holds bars for each snapshot’s ticker and timestamps such that anchor bar and forward bars exist per `horizon_outcomes.py`, labels are **deterministically** recomputable.  
**UNVERIFIED** row-by-row without a job that joins each `snapshot_id` to bars.

### 3.5 `pin_neutral` repair design (implementation-grade)

| Item | Action |
|------|--------|
| **A. Backfill eligibility** | Introduce a **controlled** backfill entry point (batch or migration) that selects unfilled snapshots by **`snapshot_id` range** or **`ts_utc` range** **without** the **14-day** ceiling — **or** temporarily parameterize window depth with audit + backup (same discipline as distance backfill). |
| **B. Core reuse** | Reuse **`forward_bar_start_utc`**, `bar_complete_by_utc`, and classification from `horizon_outcomes` / `fill_outcomes` loop — **one labeling kernel**, two callers (“live rolling” vs “historical repair”). |
| **C. Per-row validation** | For each updated row, assert post-condition **`outcome_1c IS NOT NULL`** (or partial per-horizon policy if product allows) and log **skip reason** (`no_anchor_bar`, `forward_bar_incomplete`, `no_bar_series`, etc.). |
| **D. Normalized table** | After `snapshots` repair, **re-materialize** `snapshots_1m_normalized` so derived rows inherit labels. |
| **E. Policy** | Decide whether **live** `fill_outcomes` should **also** sweep a deeper backlog on a schedule (ops) vs **one-time repair** + keep 14d for steady state. |

---

## 4. Phase 2 — `SPX` vs `$SPX`

### 4.1 INSTRUMENT IDENTITY inventory

| layer | file/function/script | representation used | evidence | compatible with “single canonical broker symbol” policy? |
|-------|---------------------|---------------------|----------|------------------------------------------------------------|
| **Bars authoritative series** | `db.fill_outcomes` / `upsert_1m_bars` | Same string as `snapshots.ticker` for joins | `price_bars_1m` query: only **`$SPX`** for SPX pattern | **Must match** snapshots ticker for joins **today** |
| **Historical snapshots** | `snapshots.ticker` | **`$SPX`** | 7888 rows; 718 labeled under `$SPX` | **Yes** as-is |
| **Anchor loader** | `adaptive_shadow_v2_calibration.load_survivorship_anchors_v1` | Strips **`$` → `SPX`** | Lines 43–45, 53 | **No** — breaks SQL match |
| **Issue 19 / similar SQL** | `db.get_similar_setups`, `_fetch_issue19_tier1_candidate_rows` | **`ticker = ?`** exact | `db.py` tier SQL | Requires **identity match** |
| **Diagnostics** | `tools/ontology_mismatch_evidence.py` | Probes `SPX` vs `$SPX` counts | `count_labeled_SPX = 0`, `count_labeled_$SPX = 718` | Proves mismatch |

**Where `$` is introduced:** **UNVERIFIED** at UI/API boundary without tracing browser → server route; **verified** downstream in **storage** as **`$SPX`**. Schwab-oriented code comments (`schwab_full_field_inventory.py`) show **`$SPX`** as index convention.

**Where `$` is removed:** **`load_survivorship_anchors_v1`** explicitly (`if tid.startswith("$"): tid = tid[1:]`).

### 4.2 Canonical policy recommendation (non-hand-wavy)

Choose **one**:

| Option | Canonical key | Actions |
|--------|---------------|---------|
| **P1 (minimal write risk)** | **Broker literal** **`$SPX`** everywhere persistent | (1) **Remove** `$`-strip in anchor loader **or** map `SPX → $SPX` at query construction only for known index set. (2) Ensure **all** new diagnostics use same literal. (3) **Do not** rename `snapshots` or `price_bars_1m` without a paired migration. |
| **P2 (normalized storage)** | **Normalized** e.g. `SPX` | (1) **Migrate** `snapshots.ticker` and **`price_bars_1m.ticker`** **in lockstep** for affected symbols. (2) **Migrate** any other table keyed by ticker (logging universe, etc.) — full inventory required before execution. (3) **Upsert** and ingestion must emit normalized form. |

**Recommendation:** **P1** unless a broader **instrument master** project is approved — **because** `fill_outcomes` **joins** `snapshots` to `price_bars_1m` on **raw ticker string**; changing **only** snapshots **breaks** labeling.

### 4.3 Mixed-era risk

- **Partial** migration (some rows `SPX`, some `$SPX`) **splits** cohorts and **duplicates** bar logic — **unacceptable** without a **symbol_alias** table and join rewrite.

### 4.4 Validation after repair

- **Zero** `SPX` / `$SPX` ambiguity queries in anchors vs DB: **`SELECT COUNT(*)` with anchor key = stored key**.
- **`fill_outcomes('$SPX')`** smoke test after any ticker change.
- **Tier-1 pool count** for `$SPX` anchors **> 0** where history exists.

---

## 5. Phase 3 — `zone` vs `regime_primary`

### 5.1 ZONE vs REGIME table

| file | function/query | field | intended meaning | actual behavior | conflation risk | verdict |
|------|----------------|-------|------------------|----------------|-----------------|---------|
| `market_state.py` | `derive_zone` | `zone` | Structural pin/expansion class from **gamma bias** | 7-value taxonomy + default | Low in **code** | **CLEAR** |
| `regime_engine.py` | scoring + `RegimePayload` | `primary` → `regime_primary` | **Environment** regime (8 families) | Uses **`inp.zone`** only as **input feature** to scoring, not as output label | Medium if reader equates “pinning regime” with “pin_neutral zone” | **Distinct** |
| `db.py` | `snapshots.zone` | `zone` | Persisted structural class | As produced | — | **CLEAR** |
| `db.py` | `snapshots.regime_primary` | `regime_primary` | Persisted environment | Examples: `pinning`, `breakout`, … | **Name collision:** English “pin” appears in both | **Document** |
| `db.py` | `get_similar_setups` tiers 1–5 | `zone` | **Exact** SQL filter | Does **not** filter `regime_primary` | Low | **Correct separation** |
| `adaptive_similarity_engine.py` | Tier 3 soft | `regime_primary` | Soft score only | Not Issue 19 structural | Analyst confusion possible | **OK** |
| `prediction_engine.py` | narrative `format_prediction_text` / regime lines | `regime.primary` vs `inp.zone` | UI copy | Shows **regime** sentence; **zone** elsewhere | **Human** conflation if labels not explicit | **Harden copy** optional |

**Exact semantic definitions (proven):**

- **`zone`:** `derive_zone` output — **`pin_bull` | pin_bear | pin_neutral | pin_chaos | breakout | breakdown`** (+ error paths may yield **`unknown`**).
- **`regime_primary`:** one of **`ALL_REGIMES`** in `regime_engine.py` — **`pinning | acceleration | breakout | mean_reversion | vol_compression | vol_expansion | trend_continuation | reversal_prone`**.

**Retrieval dependency:** **Tier design does not require** `regime_primary` **separation** for **SQL** — it requires **not mixing** the two when **interpreting** coverage reports (“pinning” density ≠ “pin_neutral” density).

### 5.2 Repair design (separation hygiene)

| Item | Action |
|------|--------|
| Documentation | Single **glossary** section in internal docs: **Structural zone** vs **Regime primary** (this file + ontology audit). |
| Reporting | Prefix columns: **`struct_zone`**, **`env_regime`** in exports where both appear. |
| Code | **No mandatory split** of storage columns; optional **rename** is high churn — prefer **external naming** first. |
| Validation | Static check: **no SQL** that `WHERE regime_primary = inp.zone` (grep gate in CI — future). |

---

## 6. Integrated repair plan (Phase 4)

### 6.1 REPAIR PLAN table

| issue | root cause | repair action | affected files/tables | rebuild? | validation | blocker severity |
|-------|------------|-------------|------------------------|----------|------------|------------------|
| `pin_neutral` labels | Rolling **14d** `fill_outcomes` window + **all current rows aged out**; **no zone blocklist** | Historical **label backfill** (extended window / by `snapshot_id`) + optional scheduled deeper sweep | `db.py` (new controlled path or script module), **`snapshots`**, then **`snapshots_1m_normalized`** | **Yes** (normalized refresh) | Post: `pin_neutral` labeled count > 0; invariant queries | **HARD** |
| `$SPX` identity | **`$` strip** in anchor loader vs **`$SPX`** in DB/bars | **P1:** align anchor/query to **`$SPX`** OR **P2:** locked dual-table migration | `adaptive_shadow_v2_calibration.py`, anchor JSON consumers, any tool using strip, **`snapshots`**, **`price_bars_1m`**, downstream tickers | **P2: Yes**; **P1: minimal** | Labeled count match for index anchors; bar join test | **HARD** |
| zone vs regime | **Narrative** collision | Docs + report column naming; optional CI grep | docs, report scripts | No | Human QA on dashboards | **Process** (not SQL) |

### 6.2 Data rebuild / backfill design

1. **Backup** SQLite file (mandatory).  
2. **`pin_neutral` / all stale unfilled:** run **repair labeling** with **documented** `ts_utc` bounds and **skip reasons** logged.  
3. **Ticker:** apply **P1 or P2** with **no** mixed-era state.  
4. **`snapshots_1m_normalized`:** **materialize** after snapshot truth stable.  
5. **Flags:** optional `ed_schema_flags` key e.g. `ontology_repair_v1` = `complete` with audit JSON.

### 6.3 Tests (next implementation phase)

- **Label repair:** golden `snapshot_id`s with known bar fixture → expected `outcome_1c`.  
- **Ticker:** anchor load → DB query returns **nonzero** count for `$SPX` cohort.  
- **Regression:** `fill_outcomes` **14d** behavior unchanged for live path unless explicitly changed.

### 6.4 Rollback

- Restore DB from backup; remove schema flag; revert normalized table from backup or re-materialize from restored raw.

### 6.5 Guards

- **Scheduled read-only** audit: `COUNT(*) WHERE zone='pin_neutral' AND outcome_1c IS NULL` **after** repair should be **zero** or **explained** (bars truly missing — list tickers).  
- **Anchor vs DB ticker** check in CI for survivorship JSON.

---

## 7. Validation and rollback plan (summary)

| Step | Action |
|------|--------|
| Pre | Full DB copy; record counts per `zone` × `outcome_1c` NULL; record ticker distinct. |
| Post | Re-run `tools/_diag_pin_neutral_outcomes.py`; re-run `tools/ontology_mismatch_evidence.py`; tier-1 counts for anchors. |
| Rollback | File restore + documented flag revert. |

---

## 8. Risks of getting this wrong

- **Label backfill without bars:** writes **nothing** or **wrong** if bar series gaps — must **skip with reason**, not silent NULL.  
- **Ticker migration desync:** **permanent** breakage of `fill_outcomes` joins.  
- **Conflating regime and zone during QA:** mis-attributed “fixes” to wrong dimension.

---

## 9. Exact next implementation actions (ordered)

1. **Decision:** **P1** vs **P2** for ticker canonical (recommend **P1** unless committing to full symbol migration).  
2. **Implement** historical outcome repair module / job (transaction-wrapped, audited) — **extend** eligibility beyond 14d for repair only.  
3. **Run** repair on **pin_neutral** subset first; validate counts; expand.  
4. **Fix** anchor loader / query construction for **`$SPX`**.  
5. **Re-materialize** normalized snapshots.  
6. **Update** docs glossary; add CI ticker consistency check.  
7. **Only after above:** re-run calibration readiness diagnostics (separate phase).

---

## 10. Required closing lines

- **PIN_NEUTRAL ROOT CAUSE PROVEN:** **YES** — **no zone exclusion**; **BAR_ANCHOR_V1** satisfied; **rolling 14-day `fill_outcomes` selection** explains **current** non-processing; **all 797 rows outside window** on audited DB; **per-row bar failure during historical window** remains **UNCERTAIN** without replay.

- **SPX CANONICAL IDENTITY PROVEN:** **YES** — **`$SPX`** in **`snapshots`** and **`price_bars_1m`**; **`SPX`** after anchor `$` strip; **exact SQL** mismatch **proven**.

- **ZONE / REGIME SEPARATION PROVEN:** **YES** in **code** — distinct producers and vocabularies; **Issue 19 SQL** uses **`zone` only**; **conflation risk** is **human/reporting**, not tier logic.

- **REBUILD / REPAIR PLAN COMPLETE:** **YES** — integrated actions, tables, validation, rollback, and mixed-era controls specified.

- **SAFE TO IMPLEMENT NEXT PHASE:** **YES** — **implementation** of this repair plan (still **not** safe for **calibration** until repairs are **executed** and **validated**).

---

*Supporting diagnostic: `python tools/_diag_pin_neutral_outcomes.py` (repo root). Evidence is DB-time-dependent; re-run after backups.*
