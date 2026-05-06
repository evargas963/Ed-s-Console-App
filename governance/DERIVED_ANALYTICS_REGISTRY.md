# Derived Analytics Registry

**Status:** Initial v2 data-plane governance registry  
**Created:** 2026-05-05  
**Framework reference:** `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md` §2.22 and §4  
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
| `GEX` / `DEX` / dollarized exposure | `delta`, `gamma`, `openInterest`, `multiplier`, spot / `underlyingPrice` | Schwab provides per-contract Greeks and OI, not dealer exposure aggregates. | `math_exposure_core.compute_exposures_by_strike` |
| `gamma_wall`, `delta_wall`, `pin_rail` | Exposure buckets derived from option chain Greeks/OI and spot | Schwab provides contracts, not structural wall selection. | `math_levels.py` wall builders |
| `vanna_proxy` | `vega`, `volatility`, `openInterest`, `multiplier`, spot | Schwab provides primitive Greeks/IV, not app-specific aggregate vanna proxy. | `math_exposure_core.compute_exposures_by_strike` |
| `net_charm_daily` | `gamma`, `delta`, `volatility`, `openInterest`, strike, expiry, spot | Schwab does not provide dealer net charm exposure. | `math_exposure_core.compute_net_charm` |
| `expected_move` | spot, `volatility`, ATM option marks, time remaining | Schwab provides prices and IV, not this strategy-specific expected-move transform. | `math_volatility.compute_expected_move_*` |
| `iv_skew` | per-contract `volatility`, strike, `putCall` | Schwab provides IV per contract, not the app's ATM skew interpretation. | `math_volatility.compute_iv_skew` |
| `realized_volatility` | price-history `close` series | Schwab provides OHLCV candles, not the chosen realized-vol estimator. | `math_volatility.compute_realized_vol` |
| `ATR` / volatility envelope | price-history OHLC series, current spot | Schwab provides OHLC, not the app's ATR envelope state. | `math_volatility.compute_atr`, volatility envelope helpers |
| `book_imbalance` | bid/ask book levels or top-of-book sizes | Schwab provides book/quote inputs, not the normalized imbalance score. | `order_flow_engine._compute_book_imbalance` |
| `cum_delta_proxy` | tape / quote changes / polling fallback inputs | Schwab does not provide the app's cumulative-delta proxy as a canonical field. | `order_flow_engine._compute_cum_delta_proxy`, server REST accumulator |
| `options_flow_score` | option-chain volume, bid/ask, delta, call/put side | Schwab provides primitives, not the composite flow score. | `order_flow_engine._compute_options_flow` |
| `RVOL` | volume, candles, fundamentals where available | Schwab provides volume inputs, not the app's current-vs-baseline RVOL transform. | `order_flow_engine._compute_rvol` |
| `institutional_flow_proxy` | large trades, options activity, book imbalance, RVOL | Schwab does not provide this composite institutional proxy. | `order_flow_engine._compute_institutional_flow_proxy` |
| `option_expression_score` | bid/ask, spread, Greeks, OI, volume, walls, side | Schwab provides option-chain primitives, not the app's A2 scoring policy. | `market_state.score_option_expression` / `recommend_option_expression` |
| `breakeven` | strike, option right, bid/ask midpoint or mark | Schwab provides prices/strike, not this selected-expression breakeven calculation. | `v2_decision.a2_option_expression._breakeven` |
| `liquidity_gate` / spread quality | bid, ask, size fields, policy thresholds | Schwab provides primitives, not app policy pass/fail state. | `market_state` and `v2_decision.a2_option_expression` |
| `VWAP_side` | spot, VWAP | Schwab or app may provide VWAP input; above/below classification is app presentation/strategy state. | `math_snapshot_derive.derive_vwap_side` |
| Synthetic 1m snapshot OHLC | sub-minute snapshot rows, spot, candle fields | Schwab price-history candles exist, but normalized snapshot aggregation is an app data product. | `snapshot_normalizer.resample_to_1m` |
| Replay PnL | archived option bid/ask, forward bars, stop/target policy | Schwab provides prices; replay fill convention and stop-first policy are app governance choices. | `realized_contract_eval` replay functions |
| Kelly sizing / risk budget | probabilities, EV estimates, policy inputs | Schwab does not provide strategy sizing. | v2 policy object pending |
| ML predictions and calibration outputs | features built from market data and historical outcomes | Schwab provides data inputs, not trained model outputs. | model artifact manifests and v2 validation contracts |
| `execution_adjusted_ev` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `quoteTimeInLong`, `tradeTimeInLong`, `symbol`, `putCall`, `strikePrice`, `daysToExpiration`, `multiplier`; upstream calibrated/conformal/EV artifacts | Schwab provides quote and contract primitives, not strategy execution-adjusted expected value after fill/slippage/impact/capacity costs. | `calibration.v2_a1_execution_ev` scaffold; must consume `chains.contract_fields()` normalized values, not raw ad-hoc chain paths |
| `fill_probability_estimate` | Normalized option contract `bid`, `ask`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `quoteTimeInLong`, `tradeTimeInLong`, `symbol`; future observed fill outcomes | Schwab provides quotes/sizes and trade timestamps, not strategy-specific probability of fill for the app's order convention. | `calibration.v2_a1_execution_ev` scaffold; future estimator requires governed fill-history validation before use |
| `slippage_estimate` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `totalVolume`, `quoteTimeInLong`, `tradeTimeInLong`; future observed entry/exit fills | Schwab provides prices and quote state, not realized slippage distribution for the app's execution policy. | `calibration.v2_a1_execution_ev` scaffold; no synthetic slippage may be emitted without validated fill/slippage history |
| `market_impact_estimate` | Normalized option contract `bid`, `ask`, `bidSize`, `askSize`, `bidAskSize`, `totalVolume`, `openInterest`, `multiplier`, `symbol`; proposed order size/capacity inputs | Schwab provides top-of-book and activity primitives, not app-specific impact of a proposed order size. | `calibration.v2_a1_execution_ev` scaffold; capacity/participation assumptions must be explicit and validated before use |
| `adverse_selection_score` | Normalized option contract `bid`, `ask`, `mark`, `bidSize`, `askSize`, `quoteTimeInLong`, `tradeTimeInLong`; future quote/fill outcome history | Schwab provides current quote state, not a model of unfavorable post-fill selection for the app's entries. | `calibration.v2_a1_execution_ev` scaffold; unavailable until representative post-fill/quote-path data exists |
| `capacity_participation_cap` | Normalized option contract `totalVolume`, `openInterest`, `bidSize`, `askSize`, `bidAskSize`, `multiplier`, `symbol`; proposed order size | Schwab provides volume/OI/size primitives, not the app's participation cap or capacity policy. | `calibration.v2_a1_execution_ev` scaffold; policy thresholds require future operator decision before promotion |

---

## Review Rule

Any code review that introduces a new derived market-data field must answer:

```text
Does Schwab provide this primitive directly?
If yes, normalize and consume Schwab first.
If no, add or update a registry entry before relying on the derivation.
```

When Schwab and a derived fallback both produce a value, disagreement monitoring should compare residuals under a governed threshold and emit `FIELD_SOURCE_DISAGREEMENT` when exceeded.

