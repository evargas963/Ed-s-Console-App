# Signal layer rebuild v1 — audit & discrimination report

This document records the canonical **1m signal_layer_v1** block (price-only + optional same-tick `SignalInput` VWAP), wiring into `calibration_decision_log`, leakage rules, univariate tests vs `outcome_5c_pts`, and discrimination of **fusion** vs **layer policy**.

---

## A. Exact files changed

| File | Role |
|------|------|
| `features/signal_layer_v1.py` | **New** — full A–F feature block, DB loaders, `layer_direction_policy`, `flatten_numeric_features` |
| `signals.py` | Passes `db` into `_maybe_append_calibration_log`; computes `signal_layer_v1` via `compute_signal_layer_v1_for_calibration` |
| `calibration/writer.py` | `append_calibration_decision(..., signal_layer_v1=...)` stored under `raw_bundle_json.signal_layer_v1` |
| `calibration/run_production_accumulation_validation.py` | Contiguous `price_bars_1m` seed per ticker + blended `outcome_5c_pts` from 20-bar momentum (harness-only) |
| `calibration/signal_layer_discrimination.py` | **New** — univariate Pearson/Spearman/MI vs `outcome_5c_pts`, fusion spread, long/short/wait splits |
| `tests/test_signal_layer_v1.py` | **New** — leakage window + SQLite bar filter + slope sanity |
| `data/signal_layer_discrimination.json` | Generated snapshot from `data/calibration_accumulation_validation.db` (re-run `python -m calibration.signal_layer_discrimination`) |

---

## B. Full feature inventory

| Key | Category | Description |
|-----|----------|-------------|
| `meta.decision_ts_utc` | meta | Decision clock (same as `refresh_ts_utc` in production path) |
| `meta.n_bars` | meta | Count of 1m bars used (`bar_end_ts_utc <= decision_ts_utc`) |
| `meta.bar_end_last` | meta | `bar_end_ts_utc` of last bar in window |
| `meta.bar_start_first` | meta | First bar start in window |
| `ps.rolling_trend_slope_log20` | A | OLS slope of `log(close)` over last 20 bars |
| `ps.rolling_trend_slope_log40` | A | Same over last 40 bars |
| `ps.hh_hl_lh_ll_state` | A | Encoded: +1 HH/HL, −1 LH/LL, fractional mixed, 0 unknown |
| `ps.break_of_structure_up` | A | 1 if `close >` last fractal swing high |
| `ps.break_of_structure_down` | A | 1 if `close <` last fractal swing low |
| `ps.dist_to_swing_high_atr` | A | `(swing_high − close) / ATR14` |
| `ps.dist_to_swing_low_atr` | A | `(close − swing_low) / ATR14` |
| `ps.range_position_n20` | A | `(close − min20) / (max20 − min20)` on last 20 bars |
| `vl.price_vs_vwap_pct` | B | `(close − vwap*) / close * 100` |
| `vl.vwap_distance_pts` | B | `close − vwap*` |
| `vl.vwap_zscore` | B | Last residual `(close − vwap*) / std(resid)` over 20 bars |
| `vl.dist_to_vwap_band_upper_pts` | B | Distance to `vwap* + 2σ` (σ from 20 residuals) |
| `vl.dist_to_vwap_band_lower_pts` | B | Distance to `vwap* − 2σ` |
| `vl.dist_to_poc_atr` | B | POC from 20-bar volume histogram; distance / ATR14 |
| `vl.dist_to_val_atr` | B | VA lower edge of ~70% volume window |
| `vl.dist_to_vah_atr` | B | VA upper edge |
| `vwap*` | B | `SignalInput.vwap` if present, else rolling VWAP from last 60 bars (typical × volume) |
| `vol.atr_percentile_60` | C | Percentile rank of current ATR14 in trailing ATR series |
| `vol.atr_expansion_ratio_5_20` | C | `ATR5 / ATR20` |
| `vol.range_compression_last` | C | `(last high − low) / ATR14` |
| `vol.realized_vol_pctile_last30` | C | Percentile of \|log ret\| over last 30 returns |
| `vol.realized_vol_annualized_proxy` | C | Annualized vol proxy from 1m log returns |
| `vol.breakout_from_compression_flag` | C | Tight prior window then last range > 1.2×ATR14 |
| `cnd.body_range_ratio` | D | `\|close−open\| / (high−low)` |
| `cnd.wick_asymmetry` | D | `(upper_wick − lower_wick) / range` |
| `cnd.close_location_in_bar` | D | `(close − low) / (high − low)` |
| `cnd.consecutive_impulse_count` | D | Count of consecutive bars in same direction (capped) |
| `cnd.gap_open_vs_prev_close_pts` | D | Open − prev close |
| `cnd.gap_flag` | D | Large gap vs 0.25×ATR14 |
| `cnd.drive_flag` | D | Strong body (>0.65 range) |
| `cnd.stall_flag` | D | Small body after extended impulse |
| `mtf.trend_1m_sign` | E | −1 / 0 / +1 from `ps.rolling_trend_slope_log20` |
| `mtf.trend_5m_from_1m_sign` | E | Log slope on aggregated 5×1m bars |
| `mtf.bias_15m_from_1m_sign` | E | Log slope on aggregated 15×1m bars |
| `mtf.alignment_state` | E | +1 aligned, −1 conflicting, 0 mixed |
| `part.relative_volume` | F | Last vol / mean vol over 20 |
| `part.volume_spike_pctile` | F | Percentile of last vol in 20-bar window |
| `part.move_efficiency_last_vs_tr5` | F | Last bar body / sum(TR) over last 5 bars |

---

## C. Formula / definition (windows)

- **Decision time \(T\)**: `decision_ts_utc` / `SignalInput.refresh_ts_utc`.
- **Bar inclusion**: all rows `price_bars_1m` with `ticker = ticker_storage_key(ticker)` and `bar_end_ts_utc <= T`, ordered oldest → newest, capped at 256 bars.
- **ATR14**: mean of Wilder TR over last 14 completed bars (requires ≥15 bars).
- **Fractal swing**: local max high / min low with lower neighbors on both sides in last 50 bars.
- **5m / 15m**: synthetic OHLC by stacking 5 or 15 consecutive 1m bars from the **same** canonical series (no separate 5m feed).

---

## D. Leakage-safety notes

- **No future bars**: any bar with `bar_end_ts_utc > T` is excluded; `meta.bar_end_last ≤ T`.
- **Outcomes** (`outcome_5c_pts`, labels) are **not** inputs to `compute_signal_layer_v1`; they are used only in offline `calibration/signal_layer_discrimination.py` and backfill joins.
- **VWAP from `SignalInput`**: same-tick market state; not a future outcome. If absent, VWAP is reconstructed from **past** bars only (rolling typical-price VWAP).
- **Source timestamps**: each feature is derived only from `bar_start_ts_utc`, `bar_end_ts_utc`, OHLCV, and optional `inp` fields at \(T\).

---

## E. Univariate predictive table (vs `outcome_5c_pts`)

Dataset: `data/calibration_accumulation_validation.db`, `n=120` trusted rows with outcomes. Features recomputed from `price_bars_1m` (not from `raw_bundle_json`) to match the live formula path.

See `data/signal_layer_discrimination.json` for the full table. Top **Pearson |r|** (absolute):

| Rank | Feature | Pearson r | Spearman r | MI (discrete) |
|------|---------|-----------|------------|
| 1 | `vol.realized_vol_annualized_proxy` | −0.193 | −0.230 | 0.272 |
| 2 | `ps.break_of_structure_up` | −0.142 | −0.136 | 0.162 |
| 3 | `vl.vwap_zscore` | 0.121 | 0.147 | 0.168 |
| 4 | `cnd.consecutive_impulse_count` | −0.104 | −0.129 | 0.195 |
| 5 | `vl.dist_to_vwap_band_upper_pts` | −0.102 | −0.121 | 0.179 |
| 6 | `vl.price_vs_vwap_pct` | 0.101 | 0.126 | 0.199 |
| 7 | `cnd.gap_open_vs_prev_close_pts` | 0.101 | 0.040 | 0.175 |
| 8 | `vl.vwap_distance_pts` | 0.101 | 0.126 | 0.199 |
| 9 | `mtf.trend_5m_from_1m_sign` | 0.093 | 0.115 | 0.130 |
| 10 | `vl.dist_to_poc_atr` | 0.085 | 0.082 | 0.199 |

---

## F. Model output discrimination results

**Fusion (from logged `fusion_json`, stubbed stack in harness)**  
- Mean `p_up, p_down, p_flat` ≈ **0.362, 0.354, 0.284** (means differ).  
- Per-row **std** across the triplet ≈ **0.001** each — **low variance row-to-row** (still “flat” posteriors in practice).  
- `fusion_triplet_spread_l1` (sum of stds) ≈ **0.0027**.

**Final call (`final_signal` in `calibration_decision_log`)**  
- **long 0% / short 0% / wait 100%** (multi-horizon / gates in harness).

**Signal layer policy (`layer_direction_policy` on recomputed features)**  
- **long ~53.3% / short ~46.7% / wait ~0%** — **non-trivial directional spread** (interpretable rule on v1 features only; **not** the production fusion model).

---

## G. FINAL: **FAIL**

**Why not PASS (strict criteria)**  

1. **Fusion / model outputs**: The Bayesian fusion layer in the accumulation run still shows **near-constant per-row probabilities** (std ~0.001). The new **signal_layer_v1** is **not** yet fed into `bayesian_fusion` / `ml_predict` as a feature source, so **model-level discrimination does not materially improve** over the prior “flat probabilities” failure mode.  
2. **Final trade policy**: `final_signal` remains **100% wait** in this harness — expected from existing gates, but it means the **end-to-end** stack does not yet demonstrate improved directional decisions from the new layer alone.

**What *did* succeed (necessary but not sufficient)**  

- Feature block is **implemented and wired** into `raw_bundle_json.signal_layer_v1` when `ED_CALIBRATION_LOG=1` and `db` is available.  
- **No lookahead** in feature construction (bar-end filter).  
- **Univariate correlations** vs `outcome_5c_pts` are **non-zero** for multiple features (see §E).  
- **Layer-only policy** shows **strong long/short mix**, unlike fusion/call collapse in this dataset.

**Remaining issues (must be NONE for PASS)**  

1. **Integrate** `signal_layer_v1` (or `flatten_numeric_features`) into the **fusion / ML stack** inputs and retrain or recalibrate fusion weights.  
2. **Re-run discrimination** on the same calibration DB and require **fusion row-wise std** or **entropy** above thresholds vs baseline.  
3. **Optional**: expose selected v1 features in `InferenceSnapshotV1` / `fusion_model_input` under explicit MVP policy to avoid duplicate-key violations.

---

*Generated as part of signal layer rebuild v1. Reproduce: `python -m calibration.run_production_accumulation_validation` then `python -m calibration.signal_layer_discrimination data/calibration_accumulation_validation.db`.*
