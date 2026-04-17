# Calibration edge validation (v1)

**Purpose:** Evaluate whether the calibration stack demonstrates a **real, statistically meaningful predictive edge** over naive baselines, using **same-sample** economics (not phase4’s cross-population snapshot baselines).

**Date:** 2026-04-11

---

## A. Dataset used

| Field | Value |
|-------|--------|
| **Primary run** | `data/calibration_accumulation_validation.db` from `python -m calibration.run_production_accumulation_validation` |
| **Population** | `N = 120` trusted, anchored, labeled rows (`outcome_5c` present); 4 tickers × 30 rows (SPY, QQQ, IWM, DIA) |
| **Production console DB** | `data/ed_console.db` — **0** trusted rows with `outcome_5c` at time of proof → **no live-market edge claim** on production data |
| **Outcome construction** | Harness seeds identical `snapshots` outcomes per row (synthetic accumulation — **not** a claim of live alpha) |

---

## B. Metrics computed

Implemented in `calibration/edge_validation.py` (`analyze_edge`):

| Metric | Definition |
|--------|------------|
| **EV (PnL proxy)** | Mean directional PnL on 5c horizon using **effective signal**: `final_signal` when `long`/`short`; else **dominant canonical class** → `long`/`short`/`wait` (same convention as phase3 dominance for calibration quality). |
| **Win rate vs baselines** | Reported indirectly via mean PnL vs random / always-long / always-short directional baselines on the **same rows**. |
| **PnL proxy vs baseline** | Same-sample means: actual vs random mix `0.5*(long+short)`, vs always-long, vs always-short. |
| **Brier score** | Mean Brier on canonical 3-class probabilities vs `outcome_5c` (lower is better). Reference: uninformative ~0.666667. |
| **Confidence vs outcome** | Dominant-class hit rate by canonical confidence bucket (`confidence_reliability`). |
| **Regime-specific** | `by_regime_primary` slice table (gated `n`). |

**Baselines included**

| Baseline | Definition |
|----------|------------|
| **Always-up / always-long** | Directional long PnL from `outcome_5c` / pts (same as phase4 long branch). |
| **Always-down / always-short** | Directional short PnL. |
| **Random** | Per-row `0.5*(pnl_long + pnl_short)` (fair coin between long and short policy). |
| **VWAP-side heuristic** | Covered in phase4 `vwap_side_mean_reversion_proxy` on **snapshots** population — **not** same-row as decision log; see phase4 caveat. Same-sample VWAP heuristic is **not** duplicated here (would require row-level vwap in `calibration_decision_log`). |

---

## C. Baseline comparisons (observed, last run)

Source: `data/calibration_edge_validation_report.json`.

| Comparison | Mean PnL proxy (5c) |
|------------|---------------------|
| Effective signal (aggregate) | 0.2 |
| Always-long directional | 0.2 |
| Always-short directional | −0.2 |
| Random long/short mix | 0.0 |
| Raw `outcome_5c_pts` mean | 0.2 |

**Bootstrap (paired, 2000 resamples, seed 42)**

| Contrast | Mean diff | 95% CI |
|----------|-----------|--------|
| Actual − random | 0.2 | [0.2, 0.2] |
| Actual − always-long | 0.0 | [0.0, 0.0] |

**Brier**

| Metric | Value |
|--------|------:|
| Mean Brier | 0.611798 |
| Uninformative reference | 0.666667 |

---

## D. Statistical validity checks

| Check | Result |
|-------|--------|
| Aggregate `n ≥ 30` | Yes (`n = 120`) |
| Per-ticker slices `n ≥ 30` | Yes (30 each × 4 tickers) |
| Time quartiles | Each quartile `< 30` rows → **not** used for standalone inference |
| EV vs random | Positive; CI excludes 0 |
| EV **strictly greater** than always-long | **No** — means are **equal** under stub (dominant class = long every row) |
| Brier vs uninformative reference | Better (lower) |
| “Not noise” | Bootstrap CI vs random is degenerate `[0.2,0.2]` because synthetic labels are **constant** per row outcome path — **not** a substitute for market noise |

**Leakage / bias (reconfirmation)**

| Topic | Status |
|-------|--------|
| Label lookahead | Outcomes attached at `snapshots.ts_utc` / join contract; same as `validate_outcome_join` + backfill resync closure |
| Survivorship | Not applicable to this harness (no universe selection) |
| Cherry-picking | **No** — full trusted+anchored labeled set for the harness DB |
| Dataset | Synthetic accumulation — **does not** prove live-market edge |

---

## E. Per-bucket / per-regime breakdowns

**By ticker** (each `n = 30`, gated): `edge_vs_random = 0.2` for SPY, QQQ, IWM, DIA (identical under constant-outcome seed).

**By regime:** single regime bucket `pinning`, `n = 120`.

**By time quartile:** insufficient `n` per quartile for `MIN_SAMPLES_STATISTICAL` gates.

---

## F. Final edge conclusion

- **Incremental directional alpha vs always-long:** **Not demonstrated** — effective policy **coincides** with always-long under the CI stub (dominant canonical probability always resolves to “up” → long).
- **Calibration signal (Brier):** Better than the uninformative 3-class reference on this sample — indicates **probability formatting** is not trivially worse than random, **not** a trading PnL edge claim.
- **Live production data:** **Insufficient** labeled trusted history in `ed_console.db` to assert any real-world edge.

---

## G. FINAL: **FAIL**

**Rationale (strict criteria from charter):**

| Criterion | Met? |
|-----------|--------|
| EV > **all** relevant baselines (including always-long) | **No** — equal to always-long |
| Performance “consistent” in a **statistically meaningful** sense vs trivial long policy | **No** — no strict superiority |
| Real-market, non-synthetic evidence | **No** |
| No bias/leakage in **methodology** | **Yes** (for harness + join contract) |

`calibration.edge_validation` **`binary_pass`: `false`** for the last recorded run (`pass_gates.ev_mean_actual_strictly_gt_always_long`: **false**, bootstrap vs always-long CI includes 0).

---

## Commands

```text
python -m calibration.run_production_accumulation_validation
python -m calibration.edge_validation --db data/calibration_accumulation_validation.db
python -m pytest tests/test_calibration_edge_validation.py tests/test_calibration_accumulation_validation.py -q --tb=short
```

---

## Remaining issues

**NONE** for closure honesty: the system **does not** meet the charter’s bar for **proven real predictive edge**; the repository now **records that failure** with reproducible metrics and strict gates.
