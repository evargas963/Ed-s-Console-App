# Calibration outcome join validation (v1)

Institutional proof that `calibration.backfill_outcomes` attaches snapshot outcomes in a **deterministic**, **auditable** way, with **no silent nearest-neighbor** when `--tol` is 0 (default).

Sections **A–H** below follow the validation checklist.

---

## A. Exact files changed (this workstream)

| File | Role |
|------|------|
| `calibration/backfill_outcomes.py` | Exact-first join, optional tolerance, duplicate/tie rejection, **post-pass resync** of all rows that already have `outcome_5c` from the matched snapshot key |
| `calibration/schema.py` | `matched_snapshot_ts_utc`, `outcome_join_method` on `calibration_decision_log` (+ migration) |
| `calibration/validate_outcome_join.py` | Ambiguity scan, column-level verification vs `snapshots`, manual sample (up to 20 rows) with all label horizons, `binary_pass` |
| `docs/calibration_outcome_join_validation_v1.md` | This document |

---

## B. Exact join logic (`calibration.backfill_outcomes`)

### Keys

- **Calibration row:** `ticker`, `decision_ts_utc` (authoritative decision instant; aligned with Phase A snapshot alignment).
- **Snapshot row:** `snapshots.ticker`, `snapshots.timeframe = '1m'`, `snapshots.ts_utc`.

### Timestamp logic and tolerance

1. **Count** snapshot rows: `(ticker, timeframe='1m', ts_utc = decision_ts_utc)`.
2. **If count > 1:** do not attach. Reason: `ambiguous_duplicate_snapshots` (duplicate candidate rows at the exact key — **fail loud**).
3. **If count == 1:** load that row. If `outcome_5c` is NULL on the snapshot, skip: `snapshot_outcomes_not_filled`. Else attach with **`outcome_join_method = 'exact'`** and **`matched_snapshot_ts_utc = snapshots.ts_utc`** (equals `decision_ts_utc` in this branch).
4. **If count == 0:**
   - If **`tol_sec <= 0`** (default **`0.0`**): skip with **`no_exact_match`**. **No nearest-neighbor.**
   - If **`tol_sec > 0`:** candidates where `ABS(ts_utc - decision_ts_utc) <= tol_sec`. If none: `no_candidate_in_tol`. Else take the **unique** minimum distance; if **multiple rows** share that minimum distance: **`ambiguous_nearest_tie`** — **fail loud**. Else attach from that row with **`outcome_join_method = 'nearest_within_tol'`** and **`matched_snapshot_ts_utc =`** that snapshot’s `ts_utc`.

Floating-point comparison for the nearest tie-break uses `best + 1e-9` when filtering rows at the minimum distance.

### Horizon attachment rules

On successful attach, **all** of the following are copied from the **single** matched `snapshots` row:

- `outcome_1c`, `outcome_5c`, `outcome_15c`, `outcome_60c`
- `outcome_1c_pts`, `outcome_5c_pts`, `outcome_15c_pts`, `outcome_60c_pts`

Also set: `outcomes_attached_ts_utc` (wall time of attach), `matched_snapshot_ts_utc`, `outcome_join_method`.

### Post-pass resync (guardrail)

After processing **pending** rows (`outcome_5c IS NULL`), the job runs **`_resync_existing_outcomes_from_snapshots`**: for **every** row with `outcome_5c IS NOT NULL`, it reloads the snapshot at **`COALESCE(matched_snapshot_ts_utc, decision_ts_utc)`**, requires **exactly one** snapshot row with filled outcomes, and **rewrites** the same outcome columns + join metadata. This prevents **legacy partial attaches** (e.g. 1c/5c copied but 15c/60c left NULL while the snapshot row had labels) from failing verification.

---

## C. Match counts (run: `python -m calibration.validate_outcome_join`)

Recorded against `data/ed_console.db` at validation time:

| Metric | Value |
|--------|------:|
| Total `calibration_decision_log` rows | 34 |
| Rows with `outcome_5c` attached (matched + verified) | 3 |
| Rows pending (`outcome_5c` NULL) | 31 |

Backfill stats for the same DB (after resync): pending pass updated **0** new rows (all pending lack an exact snapshot at `decision_ts_utc`); **resynced: 3** existing attached rows to full snapshot copy.

---

## D. Ambiguous match counts

| Check | Count |
|--------|------:|
| Distinct `(ticker, decision_ts_utc)` where **more than one** `snapshots` row exists at `(ticker, '1m', decision_ts_utc)` | **0** |
| Nearest-neighbor ties (`ambiguous_nearest_tie`) with default `--tol 0` | **0** (nearest path not used) |

Validator field: `ambiguous_exact_ts_duplicate_snapshots = 0`.

---

## E. Unmatched counts and reasons

| Category | Count | Explanation |
|----------|------:|---------------|
| `no_exact_match` (tol = 0) | **31** | No `snapshots` row at **exact** `(ticker, '1m', ts_utc = decision_ts_utc)` — typical for **legacy** calibration rows logged **before** decision timestamps were aligned to snapshot bar times, or bars never written for that instant. |
| Hypothetical `tol = 5` preview | see JSON | `no_candidate_in_tol`: **28** — no snapshot within 5s; **`ok`: 3** — would attach via nearest-within-tol (not applied unless you run `backfill_outcomes --tol 5`). |

**Policy:** Production default remains **`--tol 0`** (exact only). Using `--tol 5` is explicit and still **refuses ties** (`ambiguous_nearest_tie`).

---

## F. Manual sample validation (≥20 rows requested)

The validator draws up to **20** random rows among those with `outcome_5c`. This database had **only 3** such rows — **the entire attachable set was sampled**.

For **each** of the 3 rows (IDs 32, 33, 34 — order randomized in output):

- **Ticker:** SPY — matches snapshot row.
- **`decision_ts_utc`:** equals **`matched_snapshot_ts_utc`** and snapshot **`ts_utc`** — **exact** join, not a nearby bar.
- **Labels:** `outcome_1c`, `outcome_5c`, `outcome_15c` match the snapshot row byte-for-byte; **`outcome_60c`** is NULL on **both** calibration and snapshot (not yet labeled / insufficient — **consistent**).
- **`all_horizons_match_snapshot_row`:** **true** for all three.

Command: `python -m calibration.validate_outcome_join`

Validator gates: `binary_pass` requires **zero** ambiguous duplicate keys, **zero** verification failures, and **every** row with outcomes passing the snapshot equality check.

---

## G. PASS / FAIL (binary)

**PASS**

---

## H. Exact fixes still required if FAIL

**None** — current gate is **PASS**.

If a future run reports **FAIL**, address in order:

1. **`verification_fail > 0`:** Re-run `python -m calibration.backfill_outcomes --tol 0` so resync can repair drift; investigate any row where `matched_snapshot_ts_utc` points at a missing or duplicate snapshot.
2. **`ambiguous_exact_ts_duplicate_snapshots > 0`:** Deduplicate or fix `snapshots` ingestion so `(ticker, timeframe, ts_utc)` is unique.
3. **Pending rows you need labeled:** Align `decision_ts_utc` to real 1m snapshot timestamps (Phase A) **or** run an **explicit** `--tol > 0` after accepting nearest-neighbor policy and monitoring `ambiguous_nearest_tie` / stats.

---

## Reproduce

```bash
python -m calibration.backfill_outcomes --tol 0
python -m calibration.validate_outcome_join
```

Exit code **0** when `binary_pass` is true; **2** when false.
