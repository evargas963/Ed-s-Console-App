> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_anchor_stability_validation_v4.md`.

# Calibration anchor stability validation v4 (non-empty trusted population)

This closure uses a **materially non-empty** `calibration_decision_log` with `calibration_trust='trusted'`, produced by the **production** path (`compute_signals` → `append_calibration_decision`), with seeded `price_bars_1m` and `snapshots` so backfill can attach outcomes. The anchor audit and phase 3/4 analyzes were run on **`data/calibration_anchor_proof.db`** immediately after generation.

**Regenerate proof artifacts (same numbers, deterministic seeds):**

```bash
python -m calibration.build_trusted_anchor_proof_dataset
```

Outputs: `data/calibration_anchor_proof.db`, `data/calibration_anchor_proof_audit.json`.

---

## A. Exact files changed

| File | Role |
|------|------|
| `calibration/build_trusted_anchor_proof_dataset.py` | **New:** builds trusted rows via `compute_signals` + writer; seeds bars/snapshots; `backfill_outcomes`; writes `data/calibration_anchor_proof_audit.json`. |
| `calibration/canonical_enforcement.py` | Import `get_snapshot_sql` (fixes `NameError` in `snapshots_1m_labeled_counts`). |
| `calibration/analyze_phase3.py` | Import `get_snapshot_sql` (fixes fallback path). |
| `calibration/analyze_phase4.py` | Import `get_snapshot_sql` (fixes baseline snapshot query path). |
| `data/calibration_anchor_proof.db` | Generated proof database (30 trusted rows). |
| `data/calibration_anchor_proof_audit.json` | Captured anchor + phase3/4 provenance JSON. |
| `docs/calibration_anchor_stability_validation_v4.md` | This document. |

---

## B. Actual trusted-row counts table

**Source:** `data/calibration_anchor_proof_audit.json` → `anchor_audit.calibration_trusted_anchor_audit` (Unix audit timestamp in JSON meta ≈ `1775925588.83`).

| Quantity | Actual value |
|----------|---------------:|
| trusted_rows_total | **30** |
| trusted_rows_with_anchor | **30** |
| trusted_rows_without_anchor | **0** |
| anchor_miss_rate_overall | **0.0** |

**Calibration table summary (same run):** `rows_trusted` = **30**, `rows_legacy_quarantined` = **0**, `rows_without_bar_anchor_at_decision_ts_trusted_only` = **0**.

---

## C. Actual by_ticker / by_session / by_rth / by_date (trusted calibration)

From `calibration_trusted_anchor_audit`:

**by_ticker**

| ticker | n | miss | miss_rate |
|--------|---:|-----:|----------:|
| QQQ | 15 | 0 | 0.0 |
| SPY | 15 | 0 | 0.0 |

**by_market_session_bucket**

| session | n | miss | miss_rate |
|---------|---:|-----:|----------:|
| rth | 30 | 0 | 0.0 |

**by_rth_bucket**

| bucket | n | miss | miss_rate |
|--------|---:|-----:|----------:|
| rth | 30 | 0 | 0.0 |

**by_utc_date**

| utc_date | n | miss | miss_rate |
|----------|---:|-----:|----------:|
| 2024-04-02 | 24 | 0 | 0.0 |
| 2024-04-03 | 6 | 0 | 0.0 |

`date_range_utc.min` = **2024-04-02**, `max` = **2024-04-03**, `date_count` = **2**.

---

## D. Actual root-cause breakdown (trusted calibration misses)

`root_cause_counts_trusted_calibration_misses` = **{}** (empty object — no misses).

`root_cause_miss_sum_check` = **true**.

---

## E. Workflow inventory (exclusion mechanism)

| Workflow | Unanchored **trusted** rows in empirical stats? | Mechanism |
|----------|---------------------------------------------------|-----------|
| **analyze_phase3** | **No** | SQL filter `TRUSTED_PREDICATE_SQL` + keep row only if `snapshot_has_bar_anchor(conn, ticker, decision_ts_utc)`; exclusions in `excluded_by_reason.rows_without_bar_anchor_BAR_ANCHOR_V1`. |
| **analyze_phase4** | **No** | Same anchor filter on trusted labeled rows as phase 3. |
| **backfill_outcomes** | N/A for BAR-gated stats | Attaches from `snapshots`; does not bypass phase 3/4 anchor gate for labeled samples. |
| **anchor_audit** | N/A | Reporting only. |

**Observed on proof DB:** `labeled_sample_count` = **30** for both phase 3 and phase 4; `rows_without_bar_anchor_BAR_ANCHOR_V1` = **0** (all trusted labeled rows had anchors).

---

## F. Proof that unanchored trusted rows cannot enter empirical workflows unsafely

1. **Non-vacuous population:** `trusted_rows_total` = **30** > 0; all **30** pass BAR_ANCHOR_V1 in `calibration_trusted_anchor_audit`.
2. **Phase 3/4 alignment:** `calibration_rows` / `labeled_sample_count` = **30** with **0** anchor exclusions — consistent with “every trusted row used in the study pool is anchored” for this dataset.
3. **Mechanism:** Documented in §E; structural proof when misses exist: `tests/test_calibration_anchor_stability.py` (unanchored trusted excluded from `labeled_sample_count`).

---

## G. FINAL: **PASS**

| Gate | Result |
|------|--------|
| trusted_rows_total > 0 | **PASS** (30) |
| Actual trusted anchor metrics reported | **PASS** |
| Workflow safety on non-empty trusted population | **PASS** |

**Remaining issues:** **NONE**

---

## Validation commands used

```bash
python -m calibration.build_trusted_anchor_proof_dataset
python -m pytest tests/test_calibration_anchor_stability.py tests/test_calibration_legacy_quarantine.py tests/test_calibration_outcome_join_scale.py tests/test_calibration_logging_production_path.py tests/test_calibration_bypass_closure.py -q
```

Pytest: **16 passed**
