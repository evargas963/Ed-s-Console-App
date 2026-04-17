# Issue 19 — `pin_neutral` 1m vs 5m divergence audit

**Date:** 2026-04-03  
**Database:** `data/ed_console.db`  
**Scope:** Prove why **1m** Issue 19 pools are **zero** while **5m** has a **labeled** `pin_neutral` population; separate **repair**, **labeling**, **eligibility**, and **retrieval**. **No calibration.**

---

## 1. Executive conclusion

1. **This database has no `pin_neutral` rows at all on `1m` under BAR_ANCHOR_V1** — **0 / 797** in scope. **All** `pin_neutral` history here is stored as **`timeframe = '5m'`** (`data/pin_neutral_1m_5m_divergence_audit_v1.json`, `pin_neutral_all_schemas`).

2. **The “1m pool = 0” outcome is not because repair logic is stricter on `1m` than on `5m`.** Shared repair uses the same **`price_bars_1m`** grid and **`_apply_bar_based_outcome_updates`** for every unfilled row; there is **no `timeframe` branch** inside that writer. The divergence is **(a)** **no `1m` rows exist** in this cohort, plus **(b)** Issue 19 **`_count_tier_sql` / `get_similar_setups`** filter on **`snapshots.timeframe = anchor.timeframe`**, and survivorship anchors default to **`1m`**, so the **official** tier counts **ignore the entire `5m` labeled set**.

3. **5m labeled population (609 rows with `outcome_1c` set)** **does** produce **non-zero** tier1/tier2 counts **when the same SQL is evaluated with `timeframe = '5m'`** — e.g. **SPY** tier1 **192** / **140** (above/below anchors). **`$SPX` stays at 0** on **5m** too for those anchors → **distance / `vwap_side` mismatch** against anchor buckets (not a 1m vs 5m split).

4. **Architectural verdict:** **`1m` is the intended canonical snapshot timeframe** (`timeframe_config.py`, `server.py`). **Expecting a non-zero historical `1m` `pin_neutral` pool on this file without migration is incorrect** — the **meaningful historical cohort is `5m`**. Treating Issue 19’s **default anchor `timeframe='1m'`** as the **only** valid pool for **`pin_neutral` similarity** is an **over-strict assumption relative to the data that actually exists** unless anchors or SQL are aligned to **`5m`** for this zone (product decision).

5. **Forward RTH:** **New** `pin_neutral` rows **should** be **`1m`** if produced by the current server insert path; they **will** be labeled by **`fill_outcomes(..., CANONICAL_TIMEFRAME, ...)`** when bars exist. **Issue 19 eligibility then matches anchor `1m`**. **`5m` `pin_neutral` remains outside** the live `fill_outcomes` path.

---

## 2. Scope and methodology

- **Population / funnel:** `tools/pin_neutral_1m_5m_divergence_audit_v1.py` → `data/pin_neutral_1m_5m_divergence_audit_v1.json`.
- **Repair / labeling:** Read `db.py` (`fill_outcomes`, `fill_outcomes_pin_neutral_backfill_v1`, `_apply_bar_based_outcome_updates`), `server.py` (insert + `fill_outcomes` call).
- **Retrieval:** `tools/issue19_option_a_post_validate.py::_count_tier_sql`, `db.py:get_similar_setups` (same `WHERE timeframe = ?`).
- **Prior eligibility bundle:** `data/pin_neutral_eligibility_funnel_post_topup_v1.json` (cross-check).

---

## 3. 1m vs 5m population inventory (BAR_ANCHOR_V1 scope)

**Scope:** `zone = 'pin_neutral'` AND `COALESCE(horizon_outcome_schema_version, 3) = 3`.

| Metric | **1m** | **5m** |
|--------|--------|--------|
| **Total** | **0** | **797** |
| **`outcome_filled = 1`** | 0 | 607 |
| **`outcome_filled = 0`** | 0 | 190 |
| **Unfilled + anchor-feasible** (EXISTS `bar_end <= ts`) | 0 | 190 |
| **Unfilled + anchor-infeasible** | 0 | 0 |
| **`outcome_1c IS NOT NULL`** | 0 | 609 |

**All schemas (`zone = 'pin_neutral'` only):** only **`5m`** appears — **797** rows (same as BAR_ANCHOR scope here).

### By ticker (**5m** only)

| ticker | total | filled | `outcome_1c` set |
|--------|------:|-------:|-----------------:|
| SPY | 541 | 539 | 540 |
| **$SPX** | **183** | **0** | **0** |
| AMZN | 35 | 35 | 35 |
| MSFT | 21 | 21 | 21 |
| META | 11 | 10 | 10 |
| NVDA | 2 | 2 | 2 |
| COP, KO, UUUU, VZ | 1 each | mixed | KO has `outcome_1c` but not `outcome_filled` |

**Interpretation:** **1m row count is zero** before any repair or tier logic runs. **`$SPX` is entirely unfilled** in this cohort; **SPY** carries almost all **5m** labels.

---

## 4. Repair logic divergence

**Verdict:** **No meaningful divergence by timeframe inside the shared writer.** Differences are **which code paths run in production** and **whether rows exist**.

| File | Function / location | Condition | **1m effect** | **5m effect** | Evidence | Verdict |
|------|---------------------|-----------|---------------|---------------|----------|---------|
| `server.py` | Snapshot build | `timeframe=CANONICAL_TIMEFRAME` | New rows are **`1m`** | **No `5m` inserts** from this path | ```2314:2317:server.py``` | **5m cohort is historical / non-server** |
| `db.py` | `fill_outcomes` | `if timeframe != CANONICAL_TIMEFRAME: return` | Only **`1m`** can be filled here | **`5m` never processed** by live fill | ```2264:2265:db.py``` | **Live labeling = 1m only** |
| `db.py` | `fill_outcomes` | `ts_utc` in `(now−14d, now)` | Bounds which **`1m`** rows update | N/A for **`5m`** | ```2299:2315:db.py``` | **Old `1m` outside window stays unfilled** until backfill |
| `db.py` | `fill_outcomes_pin_neutral_backfill_v1` | `timeframe IN (1m, 5m)` | **Would** scan **`1m`** unfilled | **Does** scan **`5m`** unfilled | ```2356:2371:db.py``` | **Same repair entry for both** |
| `db.py` | Prefetch `bar_low` / `bar_high` | `bar_low = min_ts − 120d` (per ticker batch) | Same formula | Same formula | ```2381:2387:db.py``` | **No `timeframe` factor** |
| `db.py` | `_apply_bar_based_outcome_updates` | Uses **`price_bars_1m`** + `forward_bar_start_utc` | Same bar grid | Same grid (**5m snapshot still uses 1m bars for outcomes**) | `horizon_outcomes.py`; ```3032:3091:db.py``` | **Labels are always on 1m bar grid** |

**Forward grid:** **Identical** for **`1m`** and **`5m`** snapshot rows — **`OUTCOME_BAR_SPECS`** minutes are **always** resolved on **`price_bars_1m`**. There is **no** relaxed path for **`5m`**. If forward minutes are missing (e.g. **`$SPX`** hole), **both** would fail — **`5m` “succeeds” here only where bars exist**.

**Architectural intent (docstring):** Repair **explicitly** includes **legacy `5m`** rows and states labeling still uses **`price_bars_1m`** (```2339:2341:db.py```).

---

## 5. Eligibility funnel divergence (Issue 19 tier SQL)

Funnel stages use **BAR_ANCHOR** `pin_neutral` rows only. Tier counts use **`_count_tier_sql`** (same predicates as `get_similar_setups` tiers 1–2).

### 5m — where counts live

| Stage | Count | Note |
|-------|------:|------|
| 1 Total | 797 | |
| 2 `outcome_1c` NOT NULL | 609 | 188 without `outcome_1c` or NULL |
| 3–5 Schema / ticker / zone | 797 | |
| 6 Labeled subset | 609 | |
| 8 Tier1 **sum** over 8 anchors | 332 | **not distinct** across anchors |
| 8 Tier1 **max** single anchor | **192** | SPY above |
| 9 Tier2 max | **289** | SPY above |

**Per-anchor tier1 on 5m:** **SPY** non-zero; **QQQ / $SPX / IWM** **0** at tier1 (distance + `vwap_side` filters eliminate all labeled **`5m`** `pin_neutral` rows for those anchor tuples).

### 1m — exact collapse point

| Stage | Count |
|-------|------:|
| 1 Total | **0** |

**Proven collapse:** **Stage 1** — **`zero rows in `snapshots` with `pin_neutral` + BAR_ANCHOR_V1 + `timeframe = '1m'`**.  
Therefore stages 2–9 are **0**; **Issue 19 official** (anchor `timeframe` default **`1m`**) **tier pools are empty by population absence**, not by tier math.

**If Issue 19 SQL is run with `timeframe = '5m'`** (counterfactual): **SPY** pools are **non-zero** (JSON `issue19_funnel` **5m** `per_anchor_tier1`).

---

## 6. Is the **1m** expectation architecturally correct?

| Question | Answer | Evidence |
|----------|--------|----------|
| Is **`1m` canonical** for live snapshots? | **Yes** | `timeframe_config.py` lines 6–8, 40–41; `server.py` `timeframe=CANONICAL_TIMEFRAME` |
| Should **`fill_outcomes`** run on **`1m`?** | **Yes** | `server.py` calls `fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)` |
| Is **`1m` pin_neutral` a first-class *retrieval* cohort under Issue 19 defaults? | **Only if such rows exist** | `_count_tier_sql(..., timeframe=anchor["timeframe"])` with default anchor **`1m`** |
| Is the **meaningful historical `pin_neutral` cohort on this DB `5m`?** | **Yes** | Population JSON: **797 @ 5m**, **0 @ 1m** |
| Is **zero 1m pool a “bug”**? | **No** — it reflects **missing `1m` rows**, not miscounted **`1m`** rows | Stage-1 collapse |
| Is demanding **1m** pools **over-strict** vs stored data? | **Yes, for historical pin_neutral on this file** | Anchors assume **`1m`**; data is **`5m`** unless migrated |

**Conclusion:** **1m expectation is architecturally correct for live RTH going forward.** For **this historical slice**, **Issue 19’s default `1m` anchor timeframe is misaligned with the only rows that exist (`5m`)** — that is a **design/data alignment** issue, not a proof that **`1m` is “wrong”** globally.

---

## 7. Forward RTH health (by layer)

| Layer | **1m `pin_neutral`** | **5m `pin_neutral`** |
|-------|----------------------|----------------------|
| **Raw capture** | **Yes** — server inserts **`1m`** snapshots | **No** — not produced by current server insert path |
| **Outcome labeling** | **`fill_outcomes` `1m`** within **14d** + **`price_bars_1m`** forward grid | **Not** via `fill_outcomes`; only **`fill_outcomes_pin_neutral_backfill_v1`** |
| **Issue 19 eligibility** | **Yes**, if rows exist and match anchor distances / `vwap_side` | **No** under **default** anchor **`1m`** SQL |
| **Practical similarity** | Same as eligibility | Historical **`5m`** rows **invisible** to default Issue 19 **`1m`** queries |

**This DB (empirical):** `tools/rth_pin_neutral_health_probe_v1.py` showed **0** `pin_neutral` **`1m`** rows in the last **14d** — so **operational proof of healthy RTH `pin_neutral` on this file is absent**; **design** still says **`1m` is the live path**.

---

## 8. Exact next repair (evidence-based)

1. **Bar continuity for `$SPX` (and any other tickers)** so **`forward_bar_start_utc`** targets exist for unfilled rows — otherwise **`outcome_filled`** cannot flip (already documented in `docs/issue19_post_rehydration_eligibility_audit.md`).

2. **Choose one alignment path for Issue 19 `pin_neutral` similarity (product + code):**
   - **Option A:** Add **`5m`** survivorship anchors (or `timeframe='5m'` overrides) for **`pin_neutral`** so **`get_similar_setups` / post_validate** query the **cohort that exists**; **or**
   - **Option B:** **Migrate / re-log** historical `pin_neutral` as **`1m`** rows (heavy, may duplicate semantics).

3. **For `$SPX` tier pools at `5m`:** After (1), re-run repair; then **revisit anchor distances / `vwap_side`** vs empirical distributions (tier1 still **0** for **`$SPX`** on **`5m`** in JSON).

4. **Keep `fill_outcomes_pin_neutral_backfill_v1`** for **legacy `5m`** until no longer needed.

---

## 9. Remaining risks

- **Silent mismatch:** Operators assume Issue 19 **`1m`** pools reflect **`pin_neutral`**, but **history is `5m`** → **false “sparse” diagnosis**.
- **`$SPX` structural holes** in **`price_bars_1m`** → perpetual **`outcome_filled = 0`** for affected IDs.
- **Partial outcomes** (e.g. **`outcome_1c` set, `outcome_filled = 0`**) → tier SQL may count rows but **empirical viability** may still fail downstream.

---

## 10. Exact next actions

1. Run (and archive) the audit JSON after any DB change:  
   `python tools/pin_neutral_1m_5m_divergence_audit_v1.py --db data/ed_console.db --json-out data/pin_neutral_1m_5m_divergence_audit_v1.json`
2. Implement **(8.1)** then **(8.2)** per product choice.
3. Re-run **`tools/issue19_option_a_post_validate.py`** and compare **`pin_neutral`** block.

---

## 11. Deliverables

| Item | Path |
|------|------|
| **1m vs 5m population + funnel JSON** | `data/pin_neutral_1m_5m_divergence_audit_v1.json` |
| **Prior eligibility funnel (reference)** | `data/pin_neutral_eligibility_funnel_post_topup_v1.json` |
| **Audit script** | `tools/pin_neutral_1m_5m_divergence_audit_v1.py` |
| **Test** | `tests/test_pin_neutral_1m_5m_divergence_audit_v1.py` |
| **This report** | `docs/issue19_pin_neutral_1m_5m_divergence_audit.md` |

---

## 12. Exact commands used

```text
python tools/pin_neutral_1m_5m_divergence_audit_v1.py --db data/ed_console.db --json-out data/pin_neutral_1m_5m_divergence_audit_v1.json
python -m pytest tests/test_pin_neutral_1m_5m_divergence_audit_v1.py -q
```

---

## 13. Required closing lines

- **1M pin_neutral POPULATION SUFFICIENT:** **NO** — **0** BAR_ANCHOR rows at **`1m`** on this DB.

- **5M pin_neutral POPULATION SUFFICIENT:** **NO** — **609** labeled rows support **SPY-only** tier pools; **`$SPX` / QQQ / IWM** anchors remain **0** at tier1; **190** still **`outcome_filled = 0`**.

- **1M ZERO-POOL STAGE PROVEN:** **YES** — **Stage 1**: **zero** `pin_neutral` **`1m`** population (BAR_ANCHOR scope).

- **1M EXPECTATION ARCHITECTURALLY CORRECT:** **YES** — for **live** design (`timeframe_config`, `server`, `fill_outcomes`); **misaligned** with **this historical `5m`-only cohort** unless anchors/SQL or data are reconciled.

- **FORWARD RTH 1M pin_neutral HEALTHY:** **PARTIAL** — **code path is correct**; **this DB** showed **no** recent **`1m` `pin_neutral`** in the **14d** probe (`data/rth_pin_neutral_health_probe_v1.json`).

- **FORWARD RTH 5M pin_neutral HEALTHY:** **NO** — **not** live-labeled; **repair-only**.

- **EXACT NEXT REPAIR DEFINED:** **YES** — **(8.1)** bar continuity + **`$SPX` forward grid**; **(8.2)** **Issue 19 timeframe alignment** (`5m` anchors vs migration to **`1m`** rows).

- **SAFE TO PROCEED TO CALIBRATION:** **NO**
