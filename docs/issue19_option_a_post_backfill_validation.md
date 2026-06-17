> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/issue19_option_a_post_backfill_validation.md`.

# Issue 19 / Option A — Post-backfill validation report

This document records a **read-only, evidence-backed** validation pass after the `distance_magnitude_option_a_v1` backfill. It separates **storage contract correctness** from **calibration / coverage readiness**.

**Evidence bundle (machine-readable):** run

`python tools/issue19_option_a_post_validate.py --db data/ed_console.db --json-out data/option_a_post_validate_last.json`

and compare with the committed audit `data/distance_option_a_backfill_v1_last_audit.json`.

**Generated:** Unix timestamp `1775228184` (`option_a_post_validate_last.json` on the workstation that executed the diagnostic).

---

## 1. Executive conclusion

| Question | Verdict | Evidence |
|----------|---------|----------|
| Are stored `nearest_*_dist` magnitudes non-negative (or NULL) everywhere discovered? | **Yes** | §5 — zero rows with `nearest_above_dist < 0` or `nearest_below_dist < 0` on `snapshots` and `snapshots_1m_normalized`. |
| Did backfix remove the **sign mismatch** between Issue 19 SQL (`BETWEEN` on non-negative bucket bounds) and historical **negative** `nearest_below_dist`? | **Yes** | §5 + §6 — prior audit showed 136,267 + 28,560 negative below-dist rows; post backfill zeros; tier-1/tier-2 **COUNT** queries now see magnitudes inside the same intervals as anchor parameters (after `normalize_anchor_distances_for_issue19_sql` / `canonicalize_distance_read`). |
| Is **sparse tier-1** for many anchors “fixed” by backfill? | **No** | §6 — `pin_neutral` does not appear in labeled `snapshots.zone`; **SPX** has **zero** rows; these are **taxonomy / universe** issues, not magnitude sign. |
| **Contract-clean** (storage + writers + intended read contract)? | **Yes** | §3–§5, §7 — with documented **compatibility** `abs()` on read paths (§4). |
| **Calibration-ready** (pools, stability)? | **No** | §8 — tier-1 nonempty rate 30% on the default 20-anchor file; median tier-1 pool size **0** across anchors; anchor labels vs DB zones/tickers misaligned for many anchors. |

---

## 2. Scope

- **In scope:** SQLite tables carrying **both** `nearest_above_dist` and `nearest_below_dist`; writer paths that persist those columns; runtime readers that interpret signs; Issue 19 tier-1/tier-2 **structural** pool counts at scale; `ed_schema_flags.distance_magnitude_option_a_v1`; normalized table **magnitude** consistency (aggregate min/max); tests and diagnostics that still use negative distances **as inputs** (not storage).
- **Out of scope (per program):** changing Issue 19 SQL text, `get_similar_setups`, tier ordering, thresholds, transport/logging authority, Adaptive Shadow v2 calibration execution.
- **Not claimed:** “Backfill complete ⇒ all anchors get tier-1 pools.” That depends on **zone/ticker/vwap** alignment and history volume.

---

## 3. Writer inventory

All paths below **persist** or **mutate** `nearest_above_dist` / `nearest_below_dist` on store tables (or are the controlled migration).

| file | function / entry | write target | field(s) | contract | evidence |
|------|------------------|--------------|----------|----------|----------|
| `market_state.py` | `build_market_state` (nearest level block) | in-memory `MarketState` → later `SnapshotRow` | both | **PASS** | Uses `canonical_nearest_distances()` → `abs(level - spot)` per side; never encodes direction in sign (Option A). |
| `server.py` | snapshot logging (`SnapshotRow(...)`, `insert_snapshot`) | `snapshots` | both | **PASS** | Passes `ms.nearest_above_dist` / `ms.nearest_below_dist` from `MarketState` (see above). |
| `db.py` | `insert_snapshot` | `snapshots` | both (via row dict) | **PASS** | Generic INSERT; values come from callers; production path is `server` + `canonical_nearest_distances`. |
| `snapshot_normalizer.py` | `materialize_normalized_table` | `snapshots_1m_normalized` | both (copied/resampled from raw row dicts) | **PASS** | Inherits distances from source snapshots; no reintroduction of signed-below convention in code. If raw is Option A, normalized is Option A. |
| `backfill_snapshot_derived.py` | `backfill` | `snapshots` | *(not distance columns)* | **PASS** | UPDATE touches VWAP, IV rank, pressure fields only — verified in source. |
| `backfill_flow_imbalance.py` | flow backfill | `snapshots` | — | **PASS** | No `nearest_*` references in file; does not touch distance columns. |
| `distance_option_a_backfill_v1.py` | `run_distance_option_a_backfill_v1` | `snapshots`, `snapshots_1m_normalized` | `ABS()` fix on negatives | **PASS** (migration) | Controlled migration only; not a live writer. |
| `tools/phase2_forward_write_verify.py` | test harness `insert_snapshot` | `snapshots` | both from `ms` | **PASS** | Uses `build_market_state` → same canonical distances as production. |
| External / manual | raw SQL or non-repo tools | any | both | **UNKNOWN** | Any non-repo writer could still insert negatives; **§5** shows current DB has **zero** negatives — no evidence of such a path **currently** polluting the store. |

**Runtime “can this still write negative?”**

- **Production plumbing:** `canonical_nearest_distances` only produces non-negative magnitudes (or NULL). The only way to persist a negative is to **bypass** that path (custom script, corrupted row, or test harness intentionally inserting negatives).
- **Tests:** several tests INSERT negative `nearest_below_dist` for **backfill** or **legacy read** coverage (`tests/test_distance_option_a_backfill_v1.py` deliberately uses pre-migration negatives on temp DBs only).

---

## 4. Read-path inventory

Rule: **`nearest_above_dist` / `nearest_below_dist` are magnitudes; direction is by column name.** Anything that uses **sign** of these two fields for “above vs below” direction is **semantically wrong** under Option A. **`abs()` for bucketing or legacy compatibility** is acceptable if it does not reinterpret direction.

| file | function / area | old assumption (signed-below on stored `nearest_below_dist`)? | severity | runtime impact | recommended action |
|------|----------------|------------------------------------------------------------------|----------|----------------|---------------------|
| `canonical_distances.py` | `canonicalize_distance_read` | Documented legacy compat: applies `abs()` | **low** | Normalizes any stray negative to magnitude; safe for Option A rows (idempotent). | Keep; optional later **warn** if negative observed in dev builds. |
| `prediction_engine.py` | `compute_prediction`, `build_ml_snapshot_for_fusion` | Uses `canonicalize_distance_read` before SQL | **none** | Aligns live/query params with buckets | None. |
| `regime_engine.py` | `_score_mean_reversion` | Uses `canonicalize_distance_read` then ratio test | **none** | Same | None. |
| `similarity_audit.py` | `normalize_anchor_distances_for_issue19_sql` | Explicitly maps anchors to magnitudes | **none** | Ensures anchor params match `BETWEEN` intervals | None. |
| `math_probabilities.py` | `dist_bucket` | `d = abs(dist)` | **none** | Bucketing always magnitude-based | None; correct for Option A. |
| `db.py` | `get_similar_setups`, `get_avg_move` | SQL `BETWEEN` on **stored** values vs **non-negative** bucket bounds | **was high pre-backfill** if rows had negative below-dist | **Resolved** for historical stores by backfill; live anchors normalized before call | None (SQL unchanged by design). |
| `adaptive_similarity_engine.py` | `_fetch_issue19_tier1_candidate_rows` | Same as `get_similar_setups` tier 1 | **was high pre-backfill** | **Resolved** for stores | None. |
| `ml_train.py` | feature prep | `canonicalize_distance_read` on snapshot dict | **none** | Safe | None. |
| `server.py` | sweep score (`nearest_above_dist` / `nearest_below_dist`) | Uses `abs()` for **minimum wall distance** | **low** | Interprets magnitudes only | None. |
| `live_decision_bundle.py` | alternate spot mirror | `canonical_nearest_distances` | **none** | Option A | None. |
| `verification/replay_diagnostic.py` | replay | `canonicalize_distance_read` | **none** | Safe | None. |
| `similarity_audit.py` | `audit_above_below_symmetry_hint` | May take **negative** `nearest_below_dist` as **hypothetical anchor** input for diagnostics | **low** | Test/diagnostic only; not storage | Keep for hint tests; do not use for persisted rows. |
| `tests/test_similarity_feature_audit.py` | calls `audit_above_below_symmetry_hint(..., nearest_below_dist=-2.5)` | Explicit negative **input** | **none** | Tests only | None. |
| `db.py` `SnapshotRow` dataclass comment | line ~173 | Says wall **dist_*** fields can be signed — **different columns** than `nearest_*_dist` | **low** | Documentation drift only for readers who conflate field groups | Optional doc fix only; **not** a logic bug for `nearest_*_dist`. |

**Grep sweep:** comparisons and `nearest_below_dist < 0` in production code cluster in **migration/diagnostics/tests** (`distance_option_a_backfill_v1.py`, `tools/_audit_distance_signs_db.py`, `tools/phase2_forward_write_verify.py`), not in similarity matching logic after `canonicalize_distance_read`.

---

## 5. DB invariant validation

**Tool:** `tools/issue19_option_a_post_validate.py` (see JSON artifact).

**Tables discovered:** `snapshots`, `snapshots_1m_normalized` (no other tables in `sqlite_master` with both columns).

### 5.1 Live counts (validation run)

| table | total rows | `nearest_above_dist < 0` | `nearest_below_dist < 0` | `nearest_above_dist` NULL | `nearest_below_dist` NULL |
|-------|-----------:|---------------------------:|---------------------------:|--------------------------:|--------------------------:|
| `snapshots` | 141,281 | 0 | 0 | 2,604 | 4,735 |
| `snapshots_1m_normalized` | 28,729 | 0 | 0 | 206 | 169 |

**Invariant:** for all non-NULL values, `nearest_*_dist >= 0`. **Satisfied** (violations 0 / 0).

**Note on row drift:** `snapshots` total differs from `distance_option_a_backfill_v1_last_audit.json` **post_backfill** snapshot (141,336) and current (141,281) — inserts/deletes or different machine/time are possible. Negatives remain **zero**, so contract is intact on the validated file.

### 5.2 Schema flag

| flag_key | flag_value | row_present |
|----------|------------|-------------|
| `distance_magnitude_option_a_v1` | `backfill_complete` | yes (`set_ts_utc` recorded) |

**Lifecycle:** written only by `distance_option_a_backfill_v1.py` (in-progress → complete) and readable via `EdDB.get_schema_flag` / `set_schema_flag` in `db.py`. **No** evidence of conflicting writers.

### 5.3 Normalized vs raw (aggregate)

From JSON `raw_vs_normalized_minmax` — all **min** distances ≥ 0 for non-null extremes; normalized table max magnitudes sit in a similar range to raw (resampling does not reintroduce sign semantics).

**Row-level join** between `snapshots` and `snapshots_1m_normalized` was **not** performed: normalized rows receive **new** `snapshot_id` values during materialization, so ID-based parity is **not** meaningful; aggregate min/max sufficed for this pass.

### 5.4 Before vs after (stored sign blocker)

From `data/distance_option_a_backfill_v1_last_audit.json`:

| table | pre `nbd < 0` | post `nbd < 0` | rows fixed |
|-------|---------------|----------------|------------|
| `snapshots` | 136,267 | 0 | 136,267 |
| `snapshots_1m_normalized` | 28,560 | 0 | 28,560 |

**Conclusion:** the **blocker** “SQL `BETWEEN` on [0, hi] vs negative stored `nearest_below_dist`” is **removed** for these tables on the audited DB.

---

## 6. Issue 19 coverage at scale

### 6.1 Anchor population

- Source: `data/survivorship_multi_anchor_20.json` via `load_survivorship_anchors_v1()` in `adaptive_shadow_v2_calibration.py` (20 anchors).

### 6.2 Headline metrics (same SQL shape as Issue 19 tier 1 / tier 2)

| metric | value |
|--------|------:|
| anchors_total | 20 |
| tier1_nonempty_count | 6 |
| tier1_nonempty_rate | 0.30 |
| tier2_nonempty_count | 8 |
| tier2_nonempty_rate | 0.40 |
| tier1_empty_count | 14 |
| tier2_rescue_count_among_tier1_empty | 2 |
| tier2_rescue_rate_among_tier1_empty | 0.142857 |
| mean_tier1_pool_size | 4.05 |
| median_tier1_pool_size | **0.0** |
| mean_tier2_pool_size | 29.15 |
| median_tier2_pool_size | **0.0** |

Per-anchor rows and breakdowns by **ticker**, **zone**, and **vwap_side** are in `data/option_a_post_validate_last.json` under `issue19_coverage_at_scale`.

### 6.3 Labeled row context distribution (regime / session)

From `snapshots` where `outcome_1c IS NOT NULL` (top buckets):

- **session_bucket:** midday, morning, afternoon, close, open (counts in JSON).
- **regime_primary:** pinning, acceleration, breakout, reversal_prone, trend_continuation, …
- **vix_bucket:** vix_elevated, vix_high.
- **market_session:** rth, afterhours, premarket, closed.

These dimensions are **not** part of Issue 19 tier-1 SQL filters; they tie to **Tier 3** / adaptive shadow context, not tier-1 structural counts.

### 6.4 Root cause: sign mismatch **vs** sparsity

| Issue | Still present after backfill? |
|-------|------------------------------|
| Negative `nearest_below_dist` breaking `BETWEEN` with positive bucket bounds | **No** (for validated DB) |
| **Anchor zone `pin_neutral` has no matching `snapshots.zone`** (DB has `pin_bear`, `pin_bull`, `pin_chaos`, `breakout`, `breakdown` only) | **Yes** — **8 / 20** anchors use `pin_neutral` → tier-1 and tier-2 **COUNT = 0** independent of distance |
| **SPX** anchors (4) vs **zero** `snapshots` rows for ticker `SPX` | **Yes** — zero historical rows for that ticker in DB |
| Thin tier-1 for some **valid** zones (e.g. single-digit pools) | **Yes** — data volume / bucket choice, not sign |

**Explicit statement:** backfill **fixed** the **sign-mismatch** class of failures. **Sparsity** and **anchor↔DB taxonomy mismatches** remain and dominate empty tier-1 pools for this anchor file.

---

## 7. Contract validation verdict

| Check | Result |
|-------|--------|
| Historical rows (`snapshots`, `snapshots_1m_normalized`) non-negative or NULL | **PASS** |
| New writes (via `canonical_nearest_distances` + server path) Option A | **PASS** (see §3) |
| Read paths: no reliance on “negative below means below” for **stored** rows in similarity | **PASS** (`canonicalize_distance_read` + `dist_bucket(abs)` + backfill) |
| Schema flag present and `backfill_complete` | **PASS** |
| Invariants enforceable by SQL audit | **PASS** (§5) |

**Overall contract verdict:** **VALID** for the database and code paths inspected.

---

## 8. Calibration readiness verdict

| Check | Result |
|-------|--------|
| Enough tier-1 coverage across default anchors | **FAIL** — 30% nonempty; median pool 0 |
| Enough tier-2 “rescue” when tier-1 empty | **WEAK** — 14.3% of tier-1-empty anchors get tier-2 > 0 |
| Pool sizes stable / large enough for shadow scoring | **SUBOPTIMAL** — means skewed by a few large SPY pools |
| Blocking vs suboptimal | **Blocking:** anchor file **`pin_neutral`** + **SPX** mismatch; **suboptimal:** low labeled history for some zone/ticker combos |

**Overall calibration readiness verdict:** **NOT READY** until anchors align with persisted `zone` / `ticker` universe **or** coverage criteria are redefined (out of scope here).

---

## 9. Remaining risks

1. **Off-repo DB writers** could insert negatives — mitigated by periodic `tools/issue19_option_a_post_validate.py` or `distance_option_a_backfill_v1.py --report-only`.
2. **Documentation drift:** `SnapshotRow` comments still describe signed semantics for **wall** `dist_*` fields; readers may confuse with `nearest_*_dist`.
3. **`canonicalize_distance_read` masks data quality issues** by silently taking `abs()` — desirable for robustness, but can hide a reintroduced legacy writer until an audit query runs.
4. **Materialized `snapshots_1m_normalized`:** if repopulated from an **un-backfilled** backup file, negatives could return — operational process risk, not code.
5. **Interpretation of EMPTY tier-1:** default anchor JSON **does not match** DB zones for many rows — mis-attributing emptiness to “distance” would be incorrect.

---

## 10. Exact next actions

1. **Operational:** commit `data/option_a_post_validate_last.json` only if your policy allows machine-generated artifacts; otherwise regenerate in CI and attach to release notes.
2. **Anchors / diagnostics:** fix survivorship anchor **zones** (`pin_neutral` → values present in DB, or drop those anchors) and **tickers** (SPX vs index proxy actually logged in `snapshots`).
3. **Optional guard:** run `python distance_option_a_backfill_v1.py --report-only --db data/ed_console.db` on a schedule; fail CI if `nearest_below_dist_lt_0 > 0`.
4. **Calibration (when allowed):** after anchor/universe alignment, re-run `tools/issue19_option_a_post_validate.py` and Adaptive Shadow v2 calibration — **not** part of this validation pass.

---

## Final explicit answers

- **Is the system contract-clean?** **Yes** for Option A magnitudes on discovered stores and traced writers, with `canonicalize_distance_read` + `dist_bucket(abs)` as explicit compatibility layers.
- **Is it calibration-ready?** **No** — tier-1 coverage on the default 20-anchor set is insufficient; **anchor zone/ticker mismatch** (`pin_neutral`, SPX) is a **primary** driver unrelated to distance sign.
- **What remains:** align anchor definitions with **`snapshots.zone` / `ticker` truth**; grow or rebalance labeled history; optionally add automated negative-distance audits (no SQL/threshold changes required).
