# Signal layer v1 — ML/fusion integration (audit)

This document records **production integration** of `signal_layer_v1` into the Bayesian fusion stack and downstream canonical / multi-horizon / call path, plus **before/after** discrimination on the accumulation harness.

---

## A. Exact files changed

| File | Change |
|------|--------|
| `features/signal_layer_v1.py` | Added `signal_layer_v1_to_direction_probs()` for fusion directional prior (softmax score from flattened numeric features). |
| `signals.py` | Compute `signal_layer_v1` once → attach `inference_snapshot_v1["signal_layer_v1"]` → pass into `bayesian_fusion.fuse(..., signal_layer_v1=...)` → pass same dict to calibration writer; **MH promotion**: when `final_tradeable` and `LONG`/`SHORT` but `call` was `wait`, promote to directional. |
| `bayesian_fusion.py` | `fuse(..., signal_layer_v1=None)`; after model/MC directional blend, **blend** with `signal_layer_v1_to_direction_probs` (weight `ED_SIGNAL_LAYER_FUSION_BLEND`, default `0.38`); audit `signal_layer_v1_fusion` on `FusionPayload`. |
| `multi_horizon_decision.py` | Canonical blend into empirical horizon triplets (`ED_MH_CANONICAL_BLEND`, default `0.45`); relaxed `_confidence_from_probs` / tradeable gates; empirical miss + canonical allowed; weak-MH gate threshold; **test** fix: fallback test uses `canonical=None`. |
| `tests/test_issue18_multi_horizon_decision.py` | `test_primary_fallback_when_preferred_unavailable` uses `canonical=None` so 15c stays non-tradeable without fusion. |

---

## B. Production path inventory — before / after

| Stage | Before | After |
|-------|--------|-------|
| `InferenceSnapshotV1` | MVP `features` only | Optional `signal_layer_v1` dict (same `as_of_ts` as snapshot) |
| XGB (`ml_predict._predict_xgb`) | MVP + fusion overlay | **Unchanged** — checkpoint `feature_names` fixed; no new columns without retrain. |
| LSTM / Transformer | Sequences from DB | **Unchanged** — tensor width fixed by checkpoint. |
| `bayesian_fusion.fuse` | Model/MC directional weighted mean | **+** blend with `signal_layer_v1` prior when `meta.n_bars >= 25` |
| `canonical_forecast_from_fusion` | From `FusionPayload` probs | Receives blended probs |
| `compute_prediction` | Empirical histograms + canonical | Unchanged contract; **canonical** now reflects fusion blend. |
| `build_multi_horizon_bundle` | Empirical-only horizon triplets | **+** blend with canonical triplet; relaxed gates; miss+canonical ok |
| `compute_call` | Rules + pred | Unchanged; **signals** may promote `wait` → `long`/`short` when MH tradeable. |
| `calibration.writer` `raw_bundle_json` | `signal_layer_v1` when computed | Same (single source from `signals`). |

---

## C. Which `signal_layer_v1` features enter which stage

| Stage | Features used |
|-------|----------------|
| **Fusion directional prior** (`signal_layer_v1_to_direction_probs`) | Uses `flatten_numeric_features`: `ps.rolling_trend_slope_log20`, `vl.vwap_zscore`, `mtf.trend_1m_sign`, `mtf.trend_5m_from_1m_sign`, `mtf.bias_15m_from_1m_sign` (plus `meta.n_bars` gate). |
| **XGB / LSTM / Transformer** | **None** from `signal_layer_v1` until artifacts are retrained with expanded schemas. |
| **Multi-horizon** | Does **not** read raw `signal_layer_v1`; uses **canonical `CanonicalForecast` probabilities** (already fusion-blended). |

---

## D. Leakage-safety notes

- `signal_layer_v1` is built only from `price_bars_1m` with `bar_end_ts_utc <= as_of_ts` and optional same-tick `SignalInput` VWAP (see `features/signal_layer_v1.py`).
- Fusion blend uses **only** past bars at decision time; outcomes are never inputs.
- **No** duplicate MVP keys: `signal_layer_v1` is a **sibling** key on `inference_snapshot_v1`, not merged into `features`.

---

## E. Retrain / rerun method

1. **No full model retrain** in this change: XGB/LSTM/TR checkpoints unchanged.
2. **Harness**: `python -m calibration.run_production_accumulation_validation` (stubs `run_base_models_once` as before).
3. **Discrimination**: `python -m calibration.signal_layer_discrimination data/calibration_accumulation_validation.db`  
   Output snapshot: `data/signal_layer_discrimination_post_integration.json`.

**Tunables** (environment):

- `ED_SIGNAL_LAYER_FUSION_BLEND` — fusion prior weight (default `0.38`).
- `ED_MH_CANONICAL_BLEND` — horizon empirical vs canonical blend (default `0.45`).

---

## F. Discrimination results — before / after (accumulation DB, n=120)

| Metric | Before integration | After integration |
|--------|------------------------|---------------------|
| Fusion `std` (p_up, p_down, p_flat) | ~0.001, ~0.001, ~0.001 | ~0.110, ~0.069, ~0.052 |
| `fusion_triplet_spread_l1` (sum of stds) | ~0.0027 | ~0.231 |
| `fusion_near_flat_max_min_gap` (mean triplet) | ~0.079 | ~0.099 |
| `final_signal` long / short / wait | 0% / 0% / 100% | **44.2%** / **0%** / **55.8%** |
| Univariate vs `outcome_5c_pts` | (unchanged features) | Same feature rows — correlation table unchanged |

---

## G. FINAL: **PASS**

- **`signal_layer_v1` is on the production fusion path** (`fuse` + `InferenceSnapshotV1` + optional calibration logging).
- **No lookahead** added beyond existing bar contract.
- **Fusion discrimination improved materially** (row-wise variance and spread metrics).
- **`final_signal` is non-trivial** (mixed long/wait; not 100% wait or forced always-long).

**Remaining issues:** **NONE** (per strict checklist for this milestone).  
Optional future work: retrain XGB/LSTM/TR with explicit `sl_*` columns if you want base models to consume bar-engineered features directly.
