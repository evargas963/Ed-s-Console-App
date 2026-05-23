> **Classification:** Historical Record | **Scope:** Root point-in-time audit `FUSION_MC_AUDIT.md`; not binding unless ACTIVE_PROGRAM cites.

# Fusion & Monte Carlo Audit

## 1. Fusion Agreement Calculation

### Where it is computed
- **File:** `bayesian_fusion.py`, lines 312–344
- **Logic:** Collects `dominant_class` from XGBoost, LSTM, and Monte Carlo. Computes `agreement = most_common_count / len(model_dirs)`.

### What it measures
**Outcome-family agreement on `dominant_class` among XGB, LSTM, and MC.**

- `model_dirs` = `[xgb_out.dominant_class, lstm_out.dominant_class, mc_dom]`
- MC dominant = `"up"` if sim_prob_up > sim_prob_down, else `"down"` if sim_prob_down > sim_prob_up, else `"flat"`
- Agreement = fraction of models that share the modal value (1/3, 2/3, or 1.0).

### Critical finding: not model-direction agreement

1. **Transformer is excluded** — Fusion uses `regime, xgb_out, lstm_out, mc_out, rules`. Transformer is never passed to `fuse()`. The displayed XGB/LSTM/Transformer outputs come from `ml_predict.get_model_outputs()`, which is a separate path. `fusion_model_agreement` does **not** reflect Transformer.

2. **Different model execution paths** — Fusion uses:
   - `xgboost_model.predict(snap)` → `ml_predict.predict_direction(snapshot)` (no ticker passed)
   - `signals._predict_lstm(inp, db)` (LSTM from signals.py)
   - `monte_carlo.simulate(...)` (MC)
   
   Display uses `ml_predict.get_model_outputs(_snap_dict, ticker, db)`, which runs XGB/LSTM/Transformer separately. So the models feeding fusion and the models shown to the user are not the same.

3. **XGB likely not in fusion agreement** — The fusion snapshot (`snap`) built in `_run_model_stack` does not include `"ticker"`. When `xgboost_model.predict(snap)` calls `predict_direction(snapshot)` without ticker, `tkr = snapshot.get("ticker", "")` is empty, and `predict_direction` returns `None`, so XGB falls back to unavailable. As a result, fusion usually computes agreement over **LSTM + MC only**. When both agree, `model_agreement = 1.0`.

**Conclusion:** `model_agreement` is not model-direction agreement for the displayed stack (XGB/LSTM/Transformer). It is agreement on `dominant_class` among the subset of models that actually feed fusion (typically LSTM + MC only), in a different execution path from what the UI shows.

---

## 2. Fusion Directional Output

### What fusion produces
- **Dominant outcome:** One of 6 outcome families: `breakout`, `pinning`, `continuation`, `reversal`, `vol_expansion`, `mean_reversion`
- **Dominant probability:** Posterior probability for that outcome family
- **Posteriors:** Six posterior probabilities, one per family

### What fusion does NOT produce
- Bullish, bearish, and neutral probabilities
- Clean directional fusion: P(up), P(down), P(flat)

### Where to add directional fusion
- **Source:** `bayesian_fusion.py` — `FusionPayload` and `_fuse_impl`
- **Use:** Map posteriors and model outputs into directional probs, e.g.:
  - Bullish: up-weight `breakout`, `continuation` (if rules lean long)
  - Bearish: up-weight `breakout`, `reversal` (if rules lean short)
  - Or: weighted average of `xgb_out.prob_up/down/flat`, `lstm_out.prob_up/down/flat`, and MC `sim_prob_up/down/flat` using the fusion trust weights
- **Recommended:** Add `prob_up`, `prob_down`, `prob_flat`, and `dominant_direction` to `FusionPayload` by combining existing model directional outputs with fusion weights. That gives both outcome-family posteriors and a clean directional read for the UI.

---

## 3. Monte Carlo Calibration

### Where expansion/containment are computed
- **File:** `monte_carlo.py`, lines 281–288
- **Logic:**
  - `exceed_up = np.any(paths >= em_upper, axis=1)`
  - `exceed_down = np.any(paths <= em_lower, axis=1)`
  - `containment = mean(~(exceed_up | exceed_down))`
  - `expansion = 1.0 - containment`

So expansion = proportion of paths that leave the EM band at some point over the horizon.

### Where upper_50 / lower_50 come from
- **File:** `monte_carlo.py`, lines 262–264
- **Logic:** `pcts = np.percentile(terminals, [6.25, 12.5, 25, 50, 75, 87.5, 93.75])`
- **Mapping:** `lower_50` = 12.5th percentile of terminal prices, `upper_50` = 87.5th percentile

### Why expansion is often 1.00
1. **Horizon mismatch** — MC uses 13 bars (≈65 minutes). EM is from `compute_expected_move_iv` with `hours_remaining` (full session). Even with correct EM, many paths can exit the band over 65 minutes.
2. **EM band interpretation** — Containment = P(path never exits [em_lower, em_upper]). Over a 13-bar horizon with normal volatility, a large share of paths will touch or exceed the band at least once.
3. **Sigma scaling** — If GARCH/blend sigma is high, or IV/RV are large, paths disperse quickly and containment drops, pushing expansion toward 1.0.

### MC trustworthiness
- **Expansion pegged at 1.00:** Likely miscalibrated; either EM band is too narrow for the MC horizon, or volatility input is too high.
- **Very wide upper_50 / lower_50:** Live ranges (e.g. upper_50 ≈ 769, lower_50 ≈ 586 for SPY ≈ 678) suggest either very high effective sigma or a unit/ scaling bug (e.g. IV in wrong units, incorrect annualization).
- **Recommendation:** Treat MC as exploratory until: (a) EM horizon is aligned with MC (e.g. EM for 65 minutes), (b) sigma/IV/RV units and scaling are verified, and (c) output ranges are sanity-checked vs historical moves.

---

## 4. Summary & Recommended Fixes

| Area | Current behavior | Issue |
|------|------------------|-------|
| **model_agreement** | Fraction of agreeing voters among XGB/LSTM/MC | Uses different models than the UI; XGB often excluded (no ticker); Transformer never included. Not model-direction agreement for the shown stack. |
| **fusion_dominant** | Highest posterior among 6 outcome families | Produces setup families (pinning, breakout, etc.), not a directional signal. No clean P(up), P(down), P(flat). |
| **mc_expansion** | 1 - containment over EM band | Frequently 1.00; likely due to horizon mismatch and/or volatility inputs. |
| **mc_upper_50 / lower_50** | 87.5th / 12.5th percentile of terminal prices | Ranges appear unrealistically wide; sigma/units need checking. |

### Recommended next engineering steps (in order)

1. **Fusion agreement:**  
   - Add `ticker` to the fusion snapshot so XGB participates.  
   - Optionally include Transformer in fusion or clearly document that agreement is over (XGB, LSTM, MC) only.  
   - Ensure the same model runs feed both fusion and the UI if possible.

2. **Fusion directional output:**  
   - Add `prob_up`, `prob_down`, `prob_flat`, `dominant_direction` to `FusionPayload` by combining XGB, LSTM, and MC directional outputs with fusion trust weights.  
   - Expose these in the UI and use them for directional fusion.

3. **Monte Carlo calibration:**  
   - Align EM horizon with MC horizon (e.g. EM for 65 minutes).  
   - Audit IV/RV/ATR units and sigma scaling in `_blend_sigma` and GARCH blend.  
   - Sanity-check `upper_50`/`lower_50` vs typical 65-minute moves.  
   - Consider softer interpretation of containment/expansion for live use until calibrated.

---

*Audit completed. No logic changes made except as noted for instrumentation.*
