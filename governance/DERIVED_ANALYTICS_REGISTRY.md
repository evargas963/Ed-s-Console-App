> **Classification:** Policy Specification | **Scope:** Governance documentation `DERIVED_ANALYTICS_REGISTRY.md`.

# Derived Analytics Registry

**Status:** Initial v2 data-plane governance registry  
**Created:** 2026-05-05  
**Framework reference:** the ED Decision Engine framework (superseded under the ED CONSOLE SLIMMING directive).
**Source classification:** `derived_because_schwab_does_not_provide`

---

## Purpose

This registry distinguishes legitimate app-derived analytics from fields that should instead be consumed directly from Schwab. Any new derivation path that influences a decision, replay label, model feature, or v2 output must be registered here or separately governed before it is treated as durable.

Required registry fields:

```text
analytic_name
schwab_inputs_consumed
why_derivation_is_legitimate
source_classification
provenance_contract
```

---

## Registered Analytics

| Analytic | Schwab inputs consumed | Why derivation is legitimate | Provenance contract |
| --- | --- | --- | --- |
| `GEX` / `DEX` / dollarized exposure | `delta`, `gamma`, `openInterest`, `multiplier`; underlying price from governed quote (e.g. **`quotes.regular.regularMarketLastPrice`**) | Schwab provides per-contract Greeks and OI, not dealer exposure aggregates. | `math_exposure_core.compute_exposures_by_strike` |
| `gamma_wall`, `delta_wall`, `pin_rail` | Exposure buckets derived from option chain Greeks, **`openInterest`**, and governed underlying quote | Schwab provides contracts, not structural wall selection. | `math_levels.py` wall builders; see the institutional standard (superseded under ED CONSOLE SLIMMING) §8.2 |
| `gamma_pin` / `HVL` / `max_pain` / `gamma_flip` / `net_gex` | Same as GEX/DEX inputs | Structural levels not provided by Schwab; must use dollar GEX when spot is known. | `math_exposure_core` pickers + `math_levels.compute_*`; see the institutional standard (superseded under ED CONSOLE SLIMMING) §8.2 |
| `vanna_proxy` | `vega`, `volatility`, `openInterest`, `multiplier`; underlying price from governed quote | Schwab provides primitive Greeks and **`volatility`**, not app-specific aggregate vanna proxy. | `math_exposure_core.compute_exposures_by_strike` |
| `net_charm_daily` | `gamma`, `delta`, `volatility`, `openInterest`, strike, expiry; underlying price from governed quote | Schwab does not provide dealer net charm exposure. | `math_exposure_core.compute_net_charm` |
| `expected_move` | underlying quote price, `volatility`, ATM option marks, time remaining | Schwab provides prices and **`volatility`**, not this strategy-specific expected-move transform. | `math_volatility.compute_expected_move_*` |
| `iv_skew` | per-contract `volatility`, strike, `putCall` | Schwab provides **`volatility`** per contract, not the app's ATM skew interpretation. | `math_volatility.compute_iv_skew` |
| `realized_volatility` | price-history `close` series | Schwab provides OHLCV candles, not the chosen realized-vol estimator. | `math_volatility.compute_realized_vol` |
| `ATR` / volatility envelope | price-history OHLC series, current underlying quote | Schwab provides OHLC, not the app's ATR envelope state. | `math_volatility.compute_atr`, volatility envelope helpers |
| `book_imbalance` | bid/ask book levels or top-of-book sizes | Schwab provides book/quote inputs, not the normalized imbalance score. | `order_flow_engine._compute_book_imbalance` |
| `cum_delta_proxy` | tape / quote changes / polling fallback inputs | Schwab does not provide the app's cumulative-delta proxy as a canonical field. | `order_flow_engine._compute_cum_delta_proxy`, server REST accumulator |
| `options_flow_score` | option-chain **`totalVolume`**, `bid`/`ask`, `delta`, call/put side | Schwab provides primitives, not the composite flow score. | `order_flow_engine._compute_options_flow` |
| `RVOL` | `pricehistory.candles.*.volume` (and related candle fields), fundamentals where available | Schwab provides candle **`volume`** on price history, not the app's current-vs-baseline RVOL transform. | `order_flow_engine._compute_rvol` |
| `institutional_flow_proxy` | large trades, options activity, book imbalance, RVOL | Schwab does not provide this composite institutional proxy. | `order_flow_engine._compute_institutional_flow_proxy` |
| `option_expression_score` | `bid`/`ask`, derived spread width, Greeks, **`openInterest`**, **`totalVolume`** (not non-canonical contract `volume`), walls, side | Schwab provides option-chain primitives, not the app's A2 scoring policy. | `market_state.score_option_expression` / `recommend_option_expression` |
| `breakeven` | strike, option right, bid/ask midpoint or mark | Schwab provides prices/strike, not this selected-expression breakeven calculation. | `v2_decision.a2_option_expression._breakeven` |
| `liquidity_gate` / spread quality | bid, ask, size fields, policy thresholds | Schwab provides primitives, not app policy pass/fail state. | `market_state` and `v2_decision.a2_option_expression` |
| `VWAP_side` | underlying price vs VWAP | Schwab or app may provide VWAP input; above/below classification is app presentation/strategy state. | `math_snapshot_derive.derive_vwap_side` |
| Synthetic 1m snapshot OHLC | sub-minute snapshot rows, governed underlying quote (e.g. **`quotes.regular.regularMarketLastPrice`**), candle fields | Schwab price-history candles exist, but normalized snapshot aggregation is an app data product. | `snapshot_normalizer.resample_to_1m` |
| Replay PnL | archived option bid/ask, forward bars, stop/target policy | Schwab provides prices; replay fill convention and stop-first policy are app governance choices. | `realized_contract_eval` replay functions |
| Kelly sizing / risk budget | probabilities, EV estimates, policy inputs | Schwab does not provide strategy sizing. | v2 policy object pending |
| ML predictions and calibration outputs | features built from market data and historical outcomes | Schwab provides data inputs, not trained model outputs. | model artifact manifests and v2 validation contracts |
| `execution_adjusted_ev` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `quoteTimeInLong`, `tradeTimeInLong`, `symbol`, `putCall`, `strikePrice`, `daysToExpiration`, `multiplier`; upstream calibrated/conformal/EV artifacts | Schwab provides quote and contract primitives, not strategy execution-adjusted expected value after fill/slippage/impact/capacity costs. | `calibration.v2_a1_execution_ev` scaffold; must consume Schwab `chain_row` fields directly per the Precedence Principle in `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`, not raw ad-hoc chain paths |
| `fill_probability_estimate` | Normalized option contract `bid`, `ask`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `quoteTimeInLong`, `tradeTimeInLong`, `symbol`; future observed fill outcomes | Schwab provides quotes/sizes and trade timestamps, not strategy-specific probability of fill for the app's order convention. | `calibration.v2_a1_execution_ev` scaffold; future estimator requires governed fill-history validation before use |
| `slippage_estimate` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `totalVolume`, `quoteTimeInLong`, `tradeTimeInLong`; future observed entry/exit fills | Schwab provides prices and quote state, not realized slippage distribution for the app's execution policy. | `calibration.v2_a1_execution_ev` scaffold; no synthetic slippage may be emitted without validated fill/slippage history |
| `market_impact_estimate` | Normalized option contract `bid`, `ask`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `multiplier`, `symbol`; proposed order size/capacity inputs | Schwab provides top-of-book and activity primitives, not app-specific impact of a proposed order size. | `calibration.v2_a1_execution_ev` scaffold; capacity/participation assumptions must be explicit and validated before use |
| `adverse_selection_score` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `quoteTimeInLong`, `tradeTimeInLong`; future quote/fill outcome history | Schwab provides current quote state, not a model of unfavorable post-fill selection for the app's entries. | `calibration.v2_a1_execution_ev` scaffold; unavailable until representative post-fill/quote-path data exists |
| `capacity_participation_cap` | Normalized option contract `totalVolume`, `openInterest`, `bidSize`, `askSize`, `bidAskSize`, `multiplier`, `symbol`; proposed order size | Schwab provides **`totalVolume`**/**`openInterest`**/size primitives, not the app's participation cap or capacity policy. | `calibration.v2_a1_execution_ev` scaffold; policy thresholds require future operator decision before promotion |
| `contract_profit_label` | Replay trade-log `entry_price`, `exit_price`, `pnl_percent`, `pnl_dollars`, `exit_reason`, `skipped_reason`, `snapshot_id_entry`, `snapshot_id_exit`; those price inputs must originate from normalized Schwab option-chain fields before durable label use | Schwab provides option quote primitives, not the app's replay payoff label under its entry/exit and skip policy. | `v2_decision.a2_replay_labels` sidecar; consumes realized-contract trade-log rows only and flags `realized_contract_eval_raw_chain_reads_pending_normalization` until upstream raw chain reads are normalized |

---

## Lane Classification — greeks exposure analytics are DISPLAY/EXPLAINS ONLY (2026-07-24)

**Rule:** every greeks-derived exposure analytic in the table above — `GEX`/`DEX`, `net_gex`, `gamma_wall`/`delta_wall`/`pin_rail`, `gamma_pin`/`HVL`/`max_pain`/`gamma_flip`, `vanna_proxy`, `net_charm_daily` — is classified **display/explains lane**. It may render on the console UI and chart overlays and may be cited to explain tape behavior. It may NOT enter a model training matrix, feature store, or candidate-selection rule as a predictive input unless the consuming study's frozen preregistration explicitly binds the certified greeks channel (era floor `F1_GREEKS_ERA_FLOOR_TS_UTC` = 1784502281 + `recomputed_greeks_ready()` read gate on `greeks_recomputed_v1`).

**Evidence (kill-by-measurement, commit `9bfea2d5`):** the founding GEX-R1 association fails replication on certified greeks (Spearman −0.02, permutation p = 0.88, 65 sessions; the original −0.22 was measured on the pre-certification store). §8.6 day-level rule-selection: KILL (conditioned −40.9 bp/session vs best unconditional −33.1). Gamma-conditioned candidate study and Rule-A VWAP-fade: CLEAN NULL. Re-test doors per the no-terminal-null law: a genuine vol-regime change, QQQ replication, external multi-year chain data.

**Enforcement:** `research.pilot_step3.f1_input_gates.assert_features_off_display_lane` — invoked at the meta-ingest matrix boundary (`meta_xgb_tb_runner.mask_and_drop`); any `DISPLAY_ONLY_GREEKS_FEATURES` name in a feature set without a `certified_prereg_id` raises before any fit.

**Known bounded exception (legacy stack, disposition attached):** the legacy snapshot trainer still consumes greeks columns as features (`ml_data_common.py` — `M5_ADDITIVE_SOURCE_COLS` on the deprecated m5 path; `net_gamma_prev` ΔGEX train/serve parity helpers; `net_gamma`/`charm_net` among `snapshots_1m_normalized` feature columns). Disposition: this dies with the Round-2 KILL→DEMOTE of the legacy stack at the parked UI provenance migration. It must NOT be modified while the F3 shuffled-label control is in flight — that control certifies the trainer at SHA `9bfea2d5` exactly, and touching the feature path mid-run voids the control. At demotion, this lane rule applies with no exception.

---

## Terrain: single source of truth + full-chain basis (RC-33, 2026-07-24)

Terrain regime/posture/headline/lines have exactly ONE producer: `/api/terrain` (`terrain_engine.compute_terrain`), computed on the **wide-capture multi-expiry chain**. Operator decision 2026-07-24: the intraday terrain verdict uses the full chain, not the near-spot 0DTE slice — dealers hedge the entire delta book across weekly/monthly expiries, and gamma walls just outside the 0DTE window still magnetize intraday price. A duplicate terrain read on `/api/analytics/state` (computed on the selected-0DTE slice, ±1.3%) was removed: it was read by nothing (whole-repo consumer audit) and emitted a contradictory `UNAVAILABLE/STAND_ASIDE` against the card's `SHORT_GAMMA_TREND` for the same ticker at the same instant. The narrow-chain confidence gate (`compute_gamma_flip_v2`, ±5% span floor) is **RETAINED** as the fail-closed backstop for when wide capture is unavailable — locking the full-chain basis does not disable the alarm. See RC-33.

---

## Review Rule

Any code review that introduces a new derived market-data field must answer:

```text
Does Schwab provide this primitive directly?
If yes, normalize and consume Schwab first.
If no, add or update a registry entry before relying on the derivation.
```

When Schwab and a derived fallback both produce a value, disagreement monitoring should compare residuals under a governed threshold and emit `FIELD_SOURCE_DISAGREEMENT` when exceeded.

