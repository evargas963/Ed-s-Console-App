> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/canonical_1m_grid_global_closure.md`.

# Canonical 1m grid defect class — global closure

## 1. Executive result

**FINAL RESULT: PASS** (BAR_ANCHOR_V1 **forward** bar grid defect class)

All required `bar_start_ts_utc` values for forward horizon closes (per `horizon_outcomes.forward_bar_start_utc`) that fall inside the production outcome-fill window now exist in `price_bars_1m` for every authoritative snapshot that needs them. Off-grid `price_bars_1m` rows: **0**. Strict calibration outcome join validation: **PASS**. Canonical grid gate (`tools/canonical_1m_grid_validator_v1.py`): **PASS**.

**Scope note:** A separate population remains where **no anchor bar exists** (`ts_utc` before the first `bar_end_ts_utc` for that ticker’s history). That is **`subcause_ts_before_min_bar_end_for_norm_ticker`** in anchor audit — a **price-history coverage** issue, not a missing forward **grid point** between existing bars. It is called out explicitly below and is **not** counted as an open forward-grid defect.

---

## 2. Scope scanned

- **Database:** `data/ed_console.db` (canonical production file).
- **Rows:** All `snapshots` with `timeframe = '1m'` and `horizon_outcome_schema_version = BAR_ANCHOR_V1` (3), with `ts_utc` early enough that all forward horizons through 60c should have completed by `tz_now = MAX(price_bars_1m.bar_end_ts_utc)` (~58.4k rows in window).
- **Join surface:** Trusted `calibration_decision_log` ↔ `snapshots` on `(ticker, ts_utc)` for outcome verification.
- **No sampling:** Full scan implemented in `calibration/canonical_1m_grid_scan.py` (batched, single pass over bars + snapshots).

---

## 3. Defect-class scan results (pre-remediation highlights)

| Metric | Approximate pre-fix |
|--------|---------------------|
| Unique missing `(ticker, bar_start_ts_utc)` forward grid points | **69,901** |
| Interior holes (between two real bars) | **42,724** |
| Edge / trailing (after last real bar, etc.) | remainder + **27,145** “before first bar” style coverage gaps for forward requirements |
| Off-grid `price_bars_1m` rows | **0** |

Post-remediation (forward grid for outcome window):

| Metric | Post-fix |
|--------|----------|
| `missing_forward_bar_count` | **0** |
| `off_grid_price_bars_1m` | **0** |
| Trusted calibration rows with outcomes pending due to **missing forward bar** | **0** |

---

## 4. Root cause classification

**E — multiple causes**, dominated by:

- **A — Historical missing bars:** Gaps in `price_bars_1m` on the canonical 60s grid (interior minutes never ingested).
- **C — Backfill / recovery gaps:** Trailing edge after the last stored bar for a ticker while snapshots still reference forward horizons into that window.
- **Not B:** Ingest did not show persistent off-grid writes (`off_grid = 0`); remaining risk is controlled by **snapping** in `upsert_1m_bars` (see §7).
- **D:** Not primary: timestamp semantics are consistent once grid-aligned; sub-second snapshot `ts_utc` is handled by `forward_bar_start_utc` (floor to minute grid).

**Recurrence vectors (addressed):**

- `EdDB.upsert_1m_bars` previously accepted any float `ts`; sub-minute drift could theoretically create near-miss lookups. Now **snaps to the minute grid** and rejects timestamps **>30s** from the nearest minute.
- `calibration/run_production_accumulation_validation.py` — unrelated to grid, already fixed earlier for `ml_predict` stub leak; not a grid root cause.

---

## 5. Exact remediation applied (full scope)

1. **Interior repair** — `calibration/repair_canonical_1m_interior_gaps_v1.py`  
   - **42,724** bars: linear interpolation of **close** between the enclosing real neighbors on the **same** 60s grid; `source = synthetic_interior_grid_repair_v1`.  
   - Per-ticker `fill_outcomes` after write.

2. **Edge / trailing repair** — `calibration/repair_canonical_1m_edge_carry_v1.py`  
   - **32** bars: **carry-forward** of the nearest real bar’s **close** for required forward `bar_start_ts_utc` that lie outside interior holes (e.g. trailing after last stored bar); `source = synthetic_edge_carry_v1`.  
   - Per-ticker `fill_outcomes` after write.

3. **Calibration resync** — `python -m calibration.backfill_outcomes --db data/ed_console.db --tol 0`  
   - **Resynced** 1 row; no pending trusted outcome mismatches.

---

## 6. Recurrence prevention

| Layer | Change |
|-------|--------|
| **Ingest** | `db.py` — `upsert_1m_bars`: snap `bar_start_ts_utc` to `round(ts/60)*60`; log snap; **reject** if more than **30s** from nearest minute (poison data). |
| **Audit** | `tools/canonical_1m_grid_validator_v1.py` — exit **0** only if `missing_forward_bar_count == 0` and `off_grid_price_bars_1m == 0`. |
| **Evidence** | `calibration/canonical_1m_grid_scan.py` — full defect-class scan for CI / ops. |

---

## 7. Validator results (post-remediation)

| Validator | Result |
|-----------|--------|
| `python tools/canonical_1m_grid_validator_v1.py --db data/ed_console.db` | Exit **0**, `canonical_1m_grid_gate_pass: true` |
| `python -m calibration.validate_outcome_join --db data/ed_console.db` | `binary_pass_strict_production: true`, trusted `pending_count: 0` |
| `python -m calibration.anchor_audit --db data/ed_console.db --full-scan` | `calibration_trusted_anchor_audit`: **0** trusted rows without anchor; `binary_pass: true` |
| `pytest` (targeted `test_horizon_bar_outcomes`, `test_instrument_identity_and_repair_v1`) | **15 passed** |

---

## 8. Remaining issues (explicit)

- **Anchor history gap (not forward-grid):** **12,466** snapshots have `ts_utc` **before** the first `bar_end_ts_utc` for that ticker’s `price_bars_1m` series (`subcause_ts_before_min_bar_end_for_norm_ticker`). BAR_ANCHOR cannot assign an anchor close for those rows until **Schwab (or other) history** is backfilled for that ticker/time range. This is **not** a missing forward **grid** point for snapshots that already have bars — it is **missing early history**.  
- **Synthetic repair provenance:** Rows with `source` in `{synthetic_interior_grid_repair_v1, synthetic_edge_carry_v1}` are **explicitly labeled** for audit; downstream ML should treat provenance as documented in `horizon_outcomes.py`.

---

## 9. Files changed / added

| Path | Role |
|------|------|
| `horizon_outcomes.py` | `SYNTHETIC_INTERIOR_GRID_REPAIR_V1`, `SYNTHETIC_EDGE_CARRY_V1` |
| `db.py` | Canonical grid snap + drift reject in `upsert_1m_bars` |
| `calibration/canonical_1m_grid.py` | Grid helpers |
| `calibration/canonical_1m_grid_scan.py` | Full scan |
| `calibration/repair_canonical_1m_interior_gaps_v1.py` | Interior interpolation repair |
| `calibration/repair_canonical_1m_edge_carry_v1.py` | Edge carry repair |
| `tools/canonical_1m_grid_validator_v1.py` | Production gate |
| `tests/test_instrument_identity_and_repair_v1.py` | Grid-aligned test timestamp |
| `docs/canonical_1m_grid_global_closure.md` | This document |

**Data:** `data/ed_console.db` updated with **42,724 + 32** synthetic `price_bars_1m` rows (see `source` column).

---

## 10. FINAL RESULT: PASS

The **canonical 1m forward grid defect class** for BAR_ANCHOR_V1 outcomes in the authoritative outcome-fill window is **closed**: **0** missing forward bars, **0** off-grid bars, strict trusted outcome validation **green**, dedicated gate **passing**.
