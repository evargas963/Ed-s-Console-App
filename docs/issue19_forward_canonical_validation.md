> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/issue19_forward_canonical_validation.md`.

# Issue 19 — Forward canonical validation + policy enforcement

**Date:** 2026-04-03  
**Purpose:** Enforce **canonical `1m`** for Issue 19–style similarity, validate **forward** `pin_neutral` + tier pools on real data, and document **horizon independence** (no silent `5m` mixing).

---

## 1. Executive summary

- **Policy:** Production **`get_similar_setups`**, **`_fetch_issue19_tier1_candidate_rows`**, **`run_adaptive_shadow_v2`**, and **survivorship anchors** now **refuse non-`CANONICAL_TIMEFRAME`** (`1m`) with **explicit logs** (no silent `5m` pool). **`fill_outcomes_pin_neutral_backfill_v1`** repairs **`1m` rows only** and reports **`legacy_timeframe_rows_excluded`** for unfilled legacy `5m` `pin_neutral` rows.

- **Real DB (`data/ed_console.db`, run recorded in `data/issue19_forward_canonical_validation_v1.json`):** **`pin_neutral` + `timeframe='1m'` = 0 rows all-time** → **no** recent (or any) forward `1m` `pin_neutral` cohort on this file. **Issue 19** `pin_neutral` tier1/tier2 counts are **0** for all eight anchors (**recent 14d** and **all-time**), because **`outcome_1c IS NOT NULL`** candidates on **`1m`** do not exist for that zone.

- **Root cause (proven):** Funnel **stage 0** = **0** — there is **no population** of `snapshots` with `zone='pin_neutral'` and `timeframe='1m'`. This is **not** a tier-math bug after enforcement; it is **absence of canonical rows** (historical `pin_neutral` lived on legacy `5m`, which Issue 19 now **excludes by design**).

- **Horizons:** **`outcome_1c` / `5c` / `15c` / `60c`** remain **forward offsets on the UTC **`price_bars_1m`** grid** via `OUTCOME_BAR_SPECS` and `_apply_bar_based_outcome_updates` — **no** `5m`/`15m`/`60m` bar tables. **Verdict: PARTIAL** independence (shared anchor, distinct forward minute keys) — unchanged from `docs/issue19_canonical_timeframe_horizon_independence_audit.md`.

---

## 2. Policy enforcement changes

| Area | Behavior | Evidence |
|------|----------|----------|
| **`EdDB.get_similar_setups`** | If `timeframe != CANONICAL_TIMEFRAME`, **WARNING** log and **return `[]`** (or `([], trace)` with `rejected`, `reject_reason`) | `db.py` |
| **`_fetch_issue19_tier1_candidate_rows`** | Non-canonical → **WARNING**, **return `[]`** | `adaptive_similarity_engine.py` |
| **`run_adaptive_shadow_v2`** | Non-canonical → **WARNING**, empty **`AdaptiveShadowRun`** with `extra.reject_reason` | `adaptive_similarity_engine.py` |
| **`load_survivorship_anchors_v1`** | Anchor **`timeframe` forced to `CANONICAL_TIMEFRAME`**; JSON non-`1m` → **WARNING** | `adaptive_shadow_v2_calibration.py` |
| **`fill_outcomes_pin_neutral_backfill_v1`** | **Only `timeframe='1m'`** in scope; **`legacy_timeframe_rows_excluded`** count for unfilled `5m` | `db.py` |

**Tests:** `test_get_similar_setups_rejects_non_canonical_timeframe`, `test_pin_neutral_backfill_excludes_legacy_5m_timeframe`, existing Issue 19 viability suite (still passes).

---

## 3. Forward `pin_neutral` counts (real data)

**Command:**

```text
python tools/issue19_forward_canonical_validation_v1.py --db data/ed_console.db --include-all-time-pools --json-out data/issue19_forward_canonical_validation_v1.json
```

**Snapshot from this repo’s `data/ed_console.db` (see JSON for exact `generated_ts_utc`):**

- **`pin_neutral_1m_all_time.n_rows`:** **0** — no `1m` `pin_neutral` rows exist on this database.
- **Recent 14d** (`pin_neutral_1m_since`): **0** rows (same root cause).
- **Legacy `5m` in last 14d** (`pin_neutral_5m_since_excluded_from_issue19`): **0** on this snapshot (DB-dependent).

**Why zero is exact:** With **no** rows at funnel stage 0, **`fill_outcomes`** / **`outcome_filled`** cannot apply to a non-existent `1m` `pin_neutral` cohort on this file. **Live RTH** would create **`1m`** rows via `insert_snapshot` + `fill_outcomes(ticker, CANONICAL_TIMEFRAME, …)` when the server logs `pin_neutral` — that population is **not present** in this artifact.

---

## 4. Issue 19 pool validation (recent + all-time)

**Recent window (default 14d):** `issue19_pin_neutral_pools_recent` — **all** `tier1_count` / `tier2_count` **0** for eight `pin_neutral` anchors (canonical `1m` enforced in anchor load).

**All-time (optional block):** `issue19_pin_neutral_pools_all_time` — still **0** / **0** on this DB (no labeled `1m` `pin_neutral` history).

**Eligibility funnel (recent, canonical `1m` only):**

| Stage | Meaning | Count (this DB) |
|-------|---------|-----------------|
| 0 | `pin_neutral` + `1m` + `ts_utc >= since` | **0** |
| 1 | + `horizon_outcome_schema_version = 3` | **0** |
| 2 | + `outcome_1c IS NOT NULL` | **0** |
| 3 | + `outcome_filled = 1` | **0** |

**Drop-off:** **Stage 0** — **no candidates**.

---

## 5. Horizon independence (hard check)

| Horizon | Derived from | 5m / higher-TF bar grid? |
|---------|--------------|-------------------------|
| `outcome_1c`, `5c`, `15c`, `60c` | `forward_bar_start_utc(ts, N)` + `price_bars_1m` closes | **No** — only **`price_bars_1m`** in schema |
| Shared anchor | Last `bar_end_ts_utc <= ts_utc` on **`price_bars_1m`** | N/A |

**Code:** `horizon_outcomes.py` (`OUTCOME_BAR_SPECS`, `forward_bar_start_utc`); `db.py` `_apply_bar_based_outcome_updates`.

**Partial / out-of-scope:** `prediction_engine.build_ml_snapshot_for_fusion` still uses **`candles_5m`** only as a **volume fallback** when `1m` volume is missing — **not** used for Issue 19 tier SQL or bar-anchor outcomes. Documented as **non-authoritative** for labels.

---

## 6. Remaining blockers

1. **Populate** canonical **`1m`** `pin_neutral` rows in production RTH (server path already forces `1m`).
2. **Ensure** `price_bars_1m` continuity per ticker so **`fill_outcomes`** can set horizons and **`outcome_filled`** when bars exist.
3. **Optional:** One-time migration or **explicit** research path if legacy **`5m`** `pin_neutral` must be studied — **not** mixed into Issue 19 production pools under this policy.

---

## 7. Next step toward calibration

Re-run **`tools/issue19_forward_canonical_validation_v1.py`** after a period of **live RTH** logging; confirm **`pin_neutral_1m_all_time.n_rows > 0`**, then **`stage 2+` > 0`**, then **`issue19_pin_neutral_pools_recent.max_tier1_pool > 0`**. Only then treat empirical **`pin_neutral`** pools as calibration-ready.

---

## 8. Artifacts

| Artifact | Role |
|----------|------|
| `data/issue19_forward_canonical_validation_v1.json` | Latest measured bundle |
| `tools/issue19_forward_canonical_validation_v1.py` | Reproducible probe |
| `tools/issue19_option_a_post_validate.py` | `_count_tier_sql(..., min_ts_utc=...)` for recent-window tier replication |

---

## 9. Final output (binary)

- **CANONICAL POLICY ENFORCED:** **YES**
- **FORWARD 1M pin_neutral GENERATED:** **NO** (on `data/ed_console.db` as measured; **0** all-time `1m` `pin_neutral` rows)
- **FORWARD pin_neutral LABELED:** **NO** (same population absence)
- **ISSUE19 POOLS NON-ZERO (FORWARD DATA):** **NO** (14d window; tier pools **0**)
- **HORIZON INDEPENDENCE CONFIRMED:** **PARTIAL** (1m bar grid only; shared anchor; see §5)
- **SAFE TO PROCEED TO CALIBRATION:** **NO**
