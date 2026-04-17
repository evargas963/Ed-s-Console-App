# Calibration anchor validation (v1)

This document records **BAR_ANCHOR_V1** anchor-feasibility versus `price_bars_1m`, explains the previously observed **~22.6%** “anchor miss” rate in Phase 1 sampling, and proves **calibration workflows** are safe.

Checklist: **A** files · **B** anchor rule · **C** miss tables · **D** root cause · **E** fixes / exclusions · **F** residual risks · **G** PASS/FAIL.

---

## B. Exact anchor rule tested

**BAR_ANCHOR_V1** (same contract as `horizon_outcomes.py` and `db.fill_outcomes`):

- **Anchor bar** for evaluation time **T** (`snapshots.ts_utc` or `calibration_decision_log.decision_ts_utc`):  
  **last** `price_bars_1m` row (per symbol key) with **`bar_end_ts_utc ≤ T`**.
- **Ticker key:** `instrument_identity.ticker_storage_key(ticker)` — must match how bars are stored (e.g. **`SPX` → `$SPX`**).
- **Hit:** `MAX(bar_end_ts_utc)` exists for that key and **T** (equivalently: `∃` row with `bar_end_ts_utc ≤ T`).
- **Miss:** no such row (then outcome labeling / bar-based similarity that depends on anchor **cannot** apply under this contract).

**Implementation note:** Fast path uses sorted `bar_end_ts_utc` lists + `bisect` (`calibration/anchor_audit.py`); equivalence checked against SQL `MAX(bar_end_ts_utc) WHERE … ≤ ts`.

---

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/anchor_audit.py` | **New:** Reproducible audit — overall / by ticker / session / UTC date / RTH vs non-RTH; root-cause buckets; `calibration_decision_log` anchor check; `snapshot_has_bar_anchor()`; `binary_pass` = all calibration rows have anchor; CLI `--workflow-safe` |
| `calibration/audit_phase1.py` | Snapshot↔bar alignment now uses **`ticker_storage_key(snapshots.ticker)`** for the anchor query (matches `fill_outcomes`); reports rows that would have **failed** with raw ticker only |
| `calibration/analyze_phase3.py` | Drops `calibration_decision_log` rows **without** bar anchor at `decision_ts_utc` (provenance counter) |
| `calibration/analyze_phase4.py` | Same exclusion + provenance |
| `calibration/__init__.py` | Documents `python -m calibration.anchor_audit` |
| `docs/calibration_anchor_validation_v1.md` | This document |

---

## C. Miss-rate tables (representative run)

Command: `python -m calibration.anchor_audit --db data/ed_console.db --sample 5000`

| Metric | Value |
|--------|------:|
| Sample size | 5000 random `snapshots` rows (`timeframe='1m'`) |
| **Miss rate (authoritative)** | **0.2252** (1126 / 5000) |
| Hits where **raw** ticker would miss but **norm** hits | 0 (this DB / sample) |
| **Calibration log:** rows without anchor at `decision_ts_utc` | **0 / 34** |

**By market_session (sample):**

| Session | n | miss | miss_rate |
|---------|---:|---:|----------:|
| rth | 3802 | 990 | 0.260 |
| premarket | 371 | 65 | 0.175 |
| afterhours | 528 | 71 | 0.135 |
| closed | 299 | 0 | 0.000 |

**By RTH bucket:**

| Bucket | n | miss_rate |
|--------|---:|----------:|
| rth | 3802 | 0.260 |
| non_rth_or_unknown | 1198 | 0.114 |

**By UTC date (recent days in sample):** Misses cluster in **late March 2026**; **April 2026 onward** in this sample **0%** miss rate — consistent with **`price_bars_1m` history** starting after snapshots for some symbols.

**By ticker (sample):** **SPY**, **$SPX**, core names show **0%** miss rate; several other symbols show **~40–55%** miss in the random sample — **not** because the rule is wrong, but because many sampled rows fall **before** the retained bar series for that symbol (see §D).

---

## D. Root-cause breakdown

For the **5000-row** sample, **100%** of authoritative misses were classified as:

- **`subcause_ts_before_min_bar_end_for_norm_ticker`:**  
  `snapshots.ts_utc` is **strictly before** the **minimum** `bar_end_ts_utc` stored in `price_bars_1m` for `ticker_storage_key(ticker)`.

That is **not** a timestamp convention bug between `bar_end_ts_utc` and `ts_utc` for rows that have bars; it means the **snapshot row exists in a time window where no bar has completed yet** in the persisted series for that symbol (see `docs/issue19_bar_history_recovery_audit.md` — **temporal gap** between snapshot history and `price_bars_1m` retention).

**Ruled out in this sample:**

- **No rows** for norm ticker in `price_bars_1m` (`subcause_no_rows` = 0).
- **Sparse intra-series gaps** with `subcause_sparse_gap_or_anomaly` = 0 (would be rare edge cases).

**Ticker key mismatch:** 0 rows in this sample fixed only by norm key (still important to **always** use `ticker_storage_key` in SQL; Phase 1 audit was updated accordingly).

---

## E. What was fixed vs excluded

| Item | Action |
|------|--------|
| **Phase 1 audit** used raw `snapshots.ticker` for `price_bars_1m` | **Fixed:** use **`ticker_storage_key(ticker)`** so the audit matches **`fill_outcomes`**. |
| **Population “miss rate” ~22%** | **Explained:** mostly **historical snapshots predating** retained `price_bars_1m` series per symbol — **harmless** for current calibration if decisions/outcomes sit in the bar-covered window. |
| **Calibration analysis bias** from unanchored rows | **Excluded:** **`analyze_phase3`** / **`analyze_phase4`** skip rows where **`snapshot_has_bar_anchor`** is false; counts in **`provenance.excluded_by_reason.rows_without_bar_anchor_BAR_ANCHOR_V1`**. |
| **Calibration log anchor safety** | **Measured:** `anchor_audit` reports **`rows_without_bar_anchor_at_decision_ts`**; gate **`binary_pass`** requires **0**. |

---

## F. Remaining risks

1. **Large `snapshots` history** vs **partial `price_bars_1m` backfill** — population-level miss rates can stay high until bars are rehydrated for all symbols/intervals; this does **not** invalidate calibration rows that pass the anchor check.
2. **Similarity / ML** code paths that read `snapshots` without enforcing BAR_ANCHOR_V1 — outside this calibration-only change; operators should reuse **`snapshot_has_bar_anchor`** where bar-based logic applies.
3. **`--workflow-safe`** on `anchor_audit` exits **0** even when some calibration rows lack anchor — use only when **analyze_phase3/4** quarantine is acceptable.

---

## Reproduce

```bash
python -m calibration.anchor_audit --db data/ed_console.db --sample 5000
# Strict exit: 0 if every calibration row has anchor; 2 otherwise.
python -m calibration.anchor_audit --db data/ed_console.db --workflow-safe
```

---

## G. PASS / FAIL (binary)

**PASS** — Anchor miss **causes** are explained; **dangerous** calibration impact is **prevented** by log-level gate (**0** unanchored calibration rows in audit) and **analysis quarantine** in phase 3/4; Phase 1 measurement **matches** production anchor keying.
