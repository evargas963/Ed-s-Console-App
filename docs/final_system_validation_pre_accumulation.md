# Final system validation — pre-accumulation

**Date:** 2026-04-03  
**Method:** Read-only **`data/ed_console.db`** + traced **current code** (no live market, no architecture changes, no calibration).  
**Evidence bundle:** `python tools/final_system_validation_pre_accumulation_v1.py --db data/ed_console.db --json-out data/final_system_validation_pre_accumulation_v1.json`

---

## Phase 1 — 1m pipeline integrity (historical)

### 1.1 Database facts (measured)

| Check | Result |
|--------|--------|
| Rows with `timeframe = '1m'` | **39 693** (latest `data/final_system_validation_pre_accumulation_v1.json`; drifts with ingest) |
| `zone` NULL or empty on `1m` | **0** |
| `ts_utc` range | **min** ≈ `1774276649.78`, **max** ≈ `1775255487.76` (see JSON) |

**Zone distribution (`1m`):**

| Zone | Count |
|------|------:|
| breakdown | 18 293 |
| pin_bull | 16 187 |
| pin_bear | 3 442 |
| breakout | 1 510 |
| pin_chaos | 261 |
| pin_neutral | **0** (absent from histogram — consistent with prior reachability audit) |

### 1.2 Continuity (sampled, not full merge)

For **SPY** (largest `1m` count: **11 266** rows in latest JSON), consecutive `ts_utc` gaps:

- **Median gap:** ~**32 s** (consistent with sub-minute refresh cadence, not literal one row per 60s wall clock).
- **p95 gap:** ~**67 s**.
- **Max gap:** ~**161 598 s** (~**44.9 hours**) — **major gap** vs median.

**Verdict:** **ANY ANOMALIES: YES** — at least one **large inter-snapshot gap** on the busiest ticker sample; **UNCERTAIN** without per-ticker gap ranking whether this is SPY-only or systemic (not computed in this pass).

### 1.3 Zone assignment trace (code)

1. **`cur_zone = derive_zone(bias_sig, nd_raw)`** for zone tracker (`server.py`).  
2. **`ms.zone = derive_zone(ms.bias_signal, ms.net_delta)`** in `build_market_state` (`market_state.py`).  
3. Snapshot insert: **`zone=ms.zone`** (`server.py`).

```1865:1871:server.py
    # ── Zone tracking ─────────────────────────────────────────────────────────
    ...
    bias_sig = (consensus_summary.bias_signal if consensus_summary else "") or ""
    nd_raw   = (consensus_summary.net_delta   if consensus_summary else None)
    cur_zone = derive_zone(bias_sig, nd_raw)
```

```935:936:market_state.py
    # ── 3. Zone — single derivation ─────────────────────────────────────────
    ms.zone = derive_zone(ms.bias_signal, ms.net_delta)
```

```2341:2341:server.py
                    zone=ms.zone,
```

**Phase 1 outputs**

- **PIPELINE ACTIVE:** **YES** — substantial `1m` snapshot history with populated `zone`.  
- **ZONE ASSIGNMENT ACTIVE:** **YES** — traced **`zone = ms.zone`** ← **`derive_zone`**.  
- **DISTINCT ZONES PRESENT:** **`breakdown`, `pin_bull`, `pin_bear`, `breakout`, `pin_chaos`** (no `pin_neutral` in this DB’s `1m` rows).  
- **ANY ANOMALIES:** **YES** — large **max gap** on SPY sample (§1.2).

---

## Phase 2 — Issue 19 with valid data (`pin_bull`)

**pin_neutral** has **0** `1m` rows on this DB; validation uses **`pin_bull`** per objective.

### 2.1 Anchor choice (data-driven)

Densest labeled cohort: **`$SPX`**, **`pin_bull`**, **`vwap_side=below`**, **`nearest_above_dist=9.68`**, **`nearest_below_dist=0.32`** — **126** rows with **`outcome_1c IS NOT NULL`** in that key group (hint from GROUP BY query in tool).

### 2.2 Tier SQL counts (same predicates as tier 1 / tier 2 in `get_similar_setups`)

- **Tier 1 count:** **130**  
- **Tier 2 count:** **164**  
- **`EdDB.get_similar_setups(..., timeframe=CANONICAL_TIMEFRAME, ...)`** returned **130** rows; first row **`match_tier = 1`**.

**FUNNEL BREAK STAGE:** **None** for this anchor — **tier 1** is **non-empty** and similarity **stops at tier 1** when tier-stop viability is met (per existing widening logic).

**Phase 2 output**

- **ISSUE19 WORKS WITH VALID DATA:** **YES** (for this **`pin_bull`** anchor on this DB).

---

## Phase 3 — Horizon independence (hard validation)

### 3.1 Contract and bar source

- **`horizon_outcomes.py`** defines forward keys as **minutes on the UTC **1m** grid** via **`forward_bar_start_utc`**; authoritative series is **`price_bars_1m`**.

```4:12:horizon_outcomes.py
Contract (schema version 3, BAR_ANCHOR_V1):
- Anchor at snapshot time T: **close** of the last fully completed canonical 1m bar such that
  bar_end_ts_utc <= T (from price_bars_1m only; never snapshots.spot or quote-derived values).
...
Authoritative price series: persisted rows in price_bars_1m (Schwab 1m history + live accumulator).
```

### 3.2 `fill_outcomes` / writer

- **`fill_outcomes`** loads **only** **`price_bars_1m`** for **`close_by_start`** and anchor series; snapshots filtered by **`timeframe = ?`** with **`CANONICAL_TIMEFRAME`** at call site.

```2278:2295:db.py
            for r in conn.execute(
                """
                SELECT bar_start_ts_utc, close FROM price_bars_1m
                WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                """,
                ...
            bar_end_rows = conn.execute(
                """
                SELECT bar_end_ts_utc, close FROM price_bars_1m
                WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
```

### 3.3 `_apply_bar_based_outcome_updates`

- Iterates **`OUTCOME_BAR_SPECS`**; each horizon uses **`forward_bar_start_utc(t_snap, n_min)`** and **`close_by_start`** — **no** multi-TF bar tables.

```3105:3112:db.py
        for odir, opt, n_min in OUTCOME_BAR_SPECS:
            ...
            b_start = forward_bar_start_utc(t_snap, n_min)
            ...
            fwd_close = close_by_start.get(float(b_start))
```

### 3.4 Schema / grep

- **`sqlite_master`** bar-like tables on this DB: **`price_bars_1m`** only (JSON `phase3_bar_tables`).  
- **Ripgrep** across **`*.py`**: **no** `price_bars_5m` / `price_bars_15` / `price_bars_60` **table** references in outcome/fill paths (only snapshot `timeframe='5m'` and unrelated tooling).

**Leakage note (out of horizon math):** **`prediction_engine.build_ml_snapshot_for_fusion`** may use **`candles_5m`** for **volume** when `1m` volume is missing — **not** used by **`fill_outcomes`** or **`get_similar_setups`** SQL. **UNCERTAIN** whether any other path mixes 5m **prices** into **outcome** columns without a further audit of that file; **bar-anchor outcomes** are **proven 1m-only** above.

**Phase 3 outputs**

- **ALL HORIZONS DERIVED FROM 1M (bar-anchor contract):** **YES**  
- **ANY LEAKAGE (bar tables → outcomes):** **NO** (no multi-TF bar store; writer uses **`price_bars_1m` only**)  
- **Overall:** **PARTIAL** if interpreted as “every auxiliary UI/ML field is 1m-only” — **not proven** in this pass beyond outcomes.

---

## Phase 4 — Legacy contamination

### 4.1 Code

- **`get_similar_setups`:** non-canonical **`timeframe`** → **empty** result + warning (`db.py` ~2505–2522).  
- **`adaptive_similarity_engine._fetch_issue19_tier1_candidate_rows`:** rejects non-canonical (prior change set).  
- **`load_survivorship_anchors_v1`:** forces **`timeframe: CANONICAL_TIMEFRAME`** (`adaptive_shadow_v2_calibration.py` ~53–66).  
- **Tier SQL:** **`WHERE ticker = ? AND timeframe = ? AND ...`** — second **`?`** is the passed timeframe; production uses **`1m`**.

```2665:2668:db.py
            rows = conn.execute("""
                SELECT *, 1 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                  AND outcome_1c IS NOT NULL
```

### 4.2 Database

- **`5m` snapshot rows still exist:** **103 109** (historical artifact).  
- They are **not selected** when **`timeframe='1m'`** is bound — **proven** by SQL shape + measured Issue 19 run on **`1m`** only.

**Phase 4 outputs**

- **LEGACY DATA FULLY ISOLATED (from Issue 19 / canonical similarity):** **YES**  
- **ANY LEAK PATHS (5m rows into `timeframe=?` `1m` queries):** **NO** — parameter binding excludes them.  
- **Residual:** legacy **`5m`** rows **remain on disk** — **not** “deleted,” **isolated** by contract.

---

## Phase 5 — Final system state

| Area | Status |
|------|--------|
| **Pipeline integrity** | **Active** `1m` snapshots, zones populated; **gap anomaly** on SPY sample. |
| **Issue 19** | **Verified** on **`pin_bull`** with **tier1 > 0**, **`get_similar_setups`** returns pool. |
| **Horizon independence (outcomes)** | **All bar-anchor horizons** use **`price_bars_1m`** + **`forward_bar_start_utc`**; **no** multi-TF bar tables. |
| **Legacy** | **`5m`** rows present but **not in** canonical Issue 19 SQL when **`1m`** is bound; guards on **`get_similar_setups`**. |

---

## Artifacts

| Path | Purpose |
|------|---------|
| `tools/final_system_validation_pre_accumulation_v1.py` | Re-run validation |
| `data/final_system_validation_pre_accumulation_v1.json` | Frozen numbers for this run |

---

## Final output (exact lines)

- **PIPELINE VERIFIED:** **YES** (with **documented gap anomaly** on sampled ticker)  
- **ISSUE19 VERIFIED:** **YES**  
- **HORIZON INDEPENDENCE VERIFIED:** **PARTIAL** (outcomes **YES**; full stack beyond outcomes **not** fully audited here)  
- **LEGACY CONTAMINATION ELIMINATED:** **YES** (for **Issue 19 / canonical similarity paths**; **`5m` rows still in DB**)  
- **SYSTEM READY FOR ACCUMULATION:** **YES** — structure and canonical paths **verified** on current data; operators should **expect** occasional **large snapshot gaps** and **no `1m` `pin_neutral`** on this file until bias distribution or data era changes.
