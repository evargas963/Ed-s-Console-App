> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_phase4_decision_engine_validation.md`.

# Phase 4 — Decision engine validation

## Script

```text
python -m calibration.analyze_phase4 --db data/ed_console.db
```

Output: `models/calibration_runs/phase4_analysis_<unix_ts>.json`

## Analyses

### 1. Final decision performance (from calibration log)

For each `final_signal` (`long` / `short` / `wait`), computes a **directional PnL proxy** using `outcome_5c` and `outcome_5c_pts` (long wins on `up`, short wins on `down`, flat → 0).

**Current status:** With an empty `calibration_decision_log`, **`decision_performance_from_log` is empty** — no proven edge yet from this path.

### 2. MHAP / multi-horizon alignment

Parses `multi_horizon_json.alignment_state` and compares mean `outcome_5c_pts` for rows tagged as aligned vs other non-unknown states.

**Note:** Enum strings must match the runtime `multi_horizon` bundle; verify against `test_issue18_multi_horizon_decision.py` / production logs if counts stay at zero.

### 3. Baselines (snapshots)

On all `1m` snapshots with `outcome_5c` populated:

| Baseline | Definition (intentionally crude) |
|----------|-----------------------------------|
| Always-up | Mean of raw `outcome_5c_pts` |
| Always-down | Mean of **negative** absolute move |
| VWAP mean-reversion proxy | Sign from `vwap_side` vs outcome direction |

**Example run** (`phase4_analysis_1775870864.json`), **n = 21,703**:

- `always_up_mean_5c_pts`: **0.053378**
- `always_down_mean_5c_pts`: **-0.497630**
- `vwap_side_mean_reversion_proxy_mean`: **0.403631** (n = 20,867)

These numbers describe **the underlying 5c point distribution** under naive rules — **not** a claim that MR is tradable after costs. They are **baselines** against which the decision log must compete once populated.

### 4. False confidence

Flags `long`/`short` with `medium`/`high` conviction and negative directional PnL proxy. **Current count: 0** with an empty log; re-run after logging.

---

## Verdict (honest)

**Edge of the full decision layer is not yet proven from the calibration log** because no rows exist. Baselines on snapshots are **only** for context. Populate Phase 2, backfill outcomes, then re-run Phase 4 for a defensible statement on **decision usefulness**.
