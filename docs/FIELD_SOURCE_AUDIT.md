> **Classification:** Historical Record | **Scope:** Point-in-time audit artifact `docs/FIELD_SOURCE_AUDIT.md`.

# Field Source Audit

**Status:** Initial audit from live Schwab inventory  
**Created:** 2026-05-05  
**Primary reference:** `docs/SCHWAB_FIELD_REFERENCE.md`  
**Observed catalog:** `schwab_field_inventory/schwab_field_dictionary.csv`

---

## Purpose

This audit identifies fields that EdWebConsole currently derives, approximates, normalizes, or passes through from Schwab. The goal is to prevent app-derived values from replacing Schwab-native observations when Schwab already provides the field.

Runtime priority rule:

```text
schwab_native_normalized > schwab_native_raw_fallback > derived_fallback_because_schwab_unavailable > unavailable gate
```

Internal analytics still remain internal. Schwab does not replace dealer exposure, gamma walls, option-expression scoring, VWAP side, ML outputs, Kelly sizing, or replay PnL policy. Schwab should replace app-side derivation only for primitive market-data observations that it already sends. Legitimate app analytics are governed in `docs/DERIVED_ANALYTICS_REGISTRY.md`.

---

## Audit Categories

| Category | Meaning | Action |
| --- | --- | --- |
| `schwab_native_normalized` | Schwab provides the primitive and the app consumes it through canonical normalization. | Use directly downstream. |
| `schwab_native_raw_fallback` | Schwab provides the primitive but the app reads it from preserved `raw`. | Transitional only; promote at ingest boundary. |
| `derived_because_schwab_does_not_provide` | Schwab does not provide the analytic; the app derives it from declared inputs. | Keep only if registered/governed. |
| `derived_fallback_because_schwab_unavailable` | Schwab normally provides or may provide the primitive, but it was unavailable in the selected payload. | Allow with explicit source/provenance; monitor disagreement. |
| `presentation_only` | Labels, colors, UI strings, display formatting. | Keep out of trading contracts unless explicitly needed. |

Source classification is separate from the v2 leaf `source` indicator. The v2 source indicator answers whether the field satisfies the v2 contract (`v2_compliant`, `v1_approximation`, etc.); source classification answers where the field came from (`schwab_native_normalized`, `derived_because_schwab_does_not_provide`, etc.).

---

## Source Boundary

```text
Schwab API payload
  -> chains.py / market_data_adapter.py normalization
  -> canonical observations
  -> math_* / market_state derived trader state
  -> v2_decision adapters and Tier C/UI payload
```

Boundary rule:

```text
Schwab field promotion belongs at the ingest/normalization boundary.
Trading math belongs in math_* and market_state.
v2_decision should adapt stable fields, not rediscover Schwab parsing rules.
```

---

## Inventory Snapshot

Live Schwab inventory after re-authentication:

```text
Requests made: 50
Successful: 50
Failed: 0
Raw Schwab field paths: 468,039
Canonical Schwab fields: 2,393
Greek-category canonical fields: 10
Option-chain canonical fields: 74
```

Observed option-chain Greek fields:

```text
chains.callExpDateMap.*.delta
chains.callExpDateMap.*.gamma
chains.callExpDateMap.*.rho
chains.callExpDateMap.*.theta
chains.callExpDateMap.*.vega
chains.putExpDateMap.*.delta
chains.putExpDateMap.*.gamma
chains.putExpDateMap.*.rho
chains.putExpDateMap.*.theta
chains.putExpDateMap.*.vega
```

Conclusion:

```text
theta and rho are Schwab-native option-chain fields.
```

---

## Option-Chain Field Matrix

### Already Normalized By `chains.contract_fields()`

These Schwab-native contract fields are already promoted into the app's normalized option contract:

| Field | Category | Status |
| --- | --- | --- |
| `putCall` | contract identity | `schwab_native_normalized` |
| `strikePrice` | contract identity | `schwab_native_normalized` |
| `symbol` | contract identity | `schwab_native_normalized` |
| `expirationDate` | contract identity/time | `schwab_native_normalized` |
| `multiplier` | contract metadata | `schwab_native_normalized`, default fallback is `100` |
| `bid` | bid/ask | `schwab_native_normalized` |
| `ask` | bid/ask | `schwab_native_normalized` |
| `bidSize` | bid/ask size | `schwab_native_normalized` |
| `askSize` | bid/ask size | `schwab_native_normalized` |
| `mark` | price | `schwab_native_normalized` |
| `last` | price | `schwab_native_normalized` |
| `totalVolume` | volume | `schwab_native_normalized` |
| `openInterest` | open interest | `schwab_native_normalized` |
| `delta` | Greek | `schwab_native_normalized` |
| `gamma` | Greek | `schwab_native_normalized` |
| `vega` | Greek | `schwab_native_normalized` |
| `volatility` | implied volatility | `schwab_native_normalized` |
| `theoreticalVolatility` | model/volatility | `schwab_native_normalized` |
| `daysToExpiration` | time | `schwab_native_normalized` |
| `extrinsicValue` | option value decomposition | `schwab_native_normalized` |
| `timeValue` | option value decomposition | `schwab_native_normalized` |
| `intrinsicValue` | option value decomposition | `schwab_native_normalized` |
| `raw` | full original contract | audit fallback |

### Schwab-Native But Currently Raw-Only

These fields are observed in Schwab option-chain payloads but are not promoted by `chains.contract_fields()` today:

| Field | Category | Risk | Recommended action |
| --- | --- | --- | --- |
| `theta` | Greek | High | Promote immediately. A2 must prefer Schwab theta before Black-Scholes. |
| `rho` | Greek | Medium | Promote with the Greek set for completeness and audit consistency. |
| `quoteTimeInLong` | timestamp | High | Promote for quote freshness and replay ordering. |
| `tradeTimeInLong` | timestamp | High | Promote for trade freshness and replay ordering. |
| `theoreticalOptionValue` | model price | Medium | Promote for model-vs-market comparisons. |
| `bidAskSize` | liquidity | Medium | Promote if used for UI or liquidity diagnostics. |
| `lastSize` | tape/size | Medium | Promote for order-flow/replay context. |
| `openPrice` | option OHLC | Medium | Promote for replay and intraday context. |
| `highPrice` | option OHLC | Medium | Promote for replay and intraday context. |
| `lowPrice` | option OHLC | Medium | Promote for replay and intraday context. |
| `closePrice` | option OHLC | Medium | Promote for replay and mark/close diagnostics. |
| `expirationType` | contract metadata | Medium | Promote for 0DTE/weekly/monthly filtering. |
| `settlementType` | contract metadata | Medium | Promote for exercise/settlement risk. |
| `exerciseType` | contract metadata | Medium | Promote for options contract governance. |
| `inTheMoney` | contract state | Low/Medium | Promote for selection proof and diagnostics. |
| `nonStandard` | contract metadata | Medium | Promote to exclude/flag non-standard contracts. |
| `mini` | contract metadata | Medium | Promote to avoid multiplier/contract-size ambiguity. |
| `pennyPilot` | market structure | Low | Promote if spread/tick diagnostics need it. |
| `lastTradingDay` | time/contract metadata | Medium | Promote for expiry/replay context. |
| `deliverableNote` | contract metadata | Low/Medium | Promote or preserve in audit for non-standard deliverables. |

### Chain-Level Schwab Fields To Preserve Separately

These are not per-contract fields, so they should not necessarily live inside `contract_fields()`, but they should be available as canonical chain context:

| Field | Category | Recommended action |
| --- | --- | --- |
| `underlyingPrice` | underlying reference price | Prefer over inferring spot from option rows. |
| `underlying.*` | embedded underlying quote | Normalize as chain-level context when requested. |
| `volatility` | chain-level volatility | Preserve separately from per-contract IV. |
| `interestRate` | option model input | Preserve for Greeks/model audit. |
| `dividendYield` | option model input | Preserve for Greeks/model audit. |
| `isDelayed` | data quality | Carry into provenance/readiness gates. |
| `isChainTruncated` | data completeness | Carry into selection/readiness gates. |
| `numberOfContracts` | data completeness | Carry into diagnostics. |
| `strategy` | request context | Carry into provenance. |
| `status` | response status | Carry into diagnostics. |

---

## Consumer Audit

### `v2_decision/a2_option_expression.py`

Current behavior:

- Reads selected `winner.chain_row` from `option_chain_selection_proof`.
- Computes `mid` from `bid` and `ask`.
- Computes `spread` from `bid` and `ask` if no `ms_dict["spread"]`.
- Reads `delta`, `gamma`, `vega`, `theta`, and `volatility` from the chain row.
- Falls back to Black-Scholes theta when `chain_row["theta"]` is absent.

Classification:

| Field/output | Current source | Classification | Action |
| --- | --- | --- | --- |
| `bid`, `ask` | normalized Schwab | `schwab_native_normalized` | Keep. |
| `mid` | `(bid + ask) / 2` | `derived_because_schwab_does_not_provide` | Keep as derived NBBO midpoint; prefer Schwab `mark` when the contract wants broker mark. |
| `spread` | `ask - bid` or upstream spread | `derived_because_schwab_does_not_provide` | Keep, but attach source/provenance where possible. |
| `delta`, `gamma`, `vega` | normalized Schwab | `schwab_native_normalized` | Keep. |
| `theta` | normalized, raw, or Black-Scholes fallback | `schwab_native_normalized` or fallback classification | Normalized theta is primary; BS only when Schwab theta is unavailable. |
| `iv` | Schwab `volatility` | `schwab_native_normalized` | Keep, clarify field name as Schwab IV/volatility. |
| `breakeven` | strike plus/minus mid | `derived_because_schwab_does_not_provide` | Keep as option-expression math. |
| `gamma_x_oi` | `gamma * openInterest` | `derived_because_schwab_does_not_provide` | Keep as exposure proxy. |
| `vol_oi_ratio` | upstream market state | `derived_because_schwab_does_not_provide` | Keep, document inputs. |

Risk:

```text
A2 currently source-labels Schwab-native option fields as v1_approximation.
Once normalization is corrected, v2 source indicators should separate Schwab-native observations from true approximations.
```

### `realized_contract_eval.py`

Current behavior:

- `serialize_option_chain_for_eval()` persists minimal option rows for replay.
- It includes `bid`, `ask`, `bidSize`, `askSize`, `last`, `mark`, `totalVolume`, `volume`, `openInterest`, `delta`, `gamma`, `vega`, `volatility`, `daysToExpiration`, `multiplier`, and expiration fields.
- It omits Schwab-native `theta`, `rho`, quote/trade timestamps, option OHLC, and theoretical option value.

Classification:

| Field group | Current status | Action |
| --- | --- | --- |
| Replay entry/exit prices from bid/ask | `schwab_native_normalized` plus replay policy | Keep policy; add timestamps for audit. |
| Missing Greeks `theta`, `rho` | `schwab_native_raw_fallback` until normalized | Persist once normalized. |
| Missing `quoteTimeInLong`, `tradeTimeInLong` | `schwab_native_raw_fallback` until normalized | Persist for replay freshness/order checks. |
| Missing option OHLC and `theoreticalOptionValue` | `schwab_native_raw_fallback` until normalized | Persist if replay/backtest diagnostics need them. |
| PnL using entry ask and exit bid | `derived_because_schwab_does_not_provide` policy | Keep. Not a Schwab replacement candidate. |

### `order_flow_engine.py`

Current behavior:

- Directly flattens Schwab `callExpDateMap`/`putExpDateMap` for order-flow inputs.
- Already reads `theta` and `tradeTimeInLong` from raw option rows.
- Computes book imbalance, spread, top-of-book pressure, cumulative delta proxy, options-flow score, RVOL, institutional flow proxy, and readiness.

Classification:

| Field/output | Classification | Action |
| --- | --- | --- |
| `theta`, `tradeTimeInLong`, `lastSize`, sizes, bid/ask, Greeks | `schwab_native_normalized` target | Align normalized contract output so order flow and A2 consume the same canonical fields. |
| Book imbalance | `derived_because_schwab_does_not_provide` | Keep derived; Schwab provides inputs, not the composite. |
| Spread | `derived_because_schwab_does_not_provide` | Keep derived from bid/ask. |
| Cumulative delta proxy | `derived_because_schwab_does_not_provide` proxy | Keep, but document as proxy. |
| RVOL | `derived_because_schwab_does_not_provide` | Keep; Schwab supplies volume/fundamental inputs. |
| Institutional flow proxy | `derived_because_schwab_does_not_provide` model | Keep. |

### `math_exposure_core.py`

Current behavior:

- Computes delta/gamma exposures from Schwab `delta`, `gamma`, `openInterest`, and multiplier.
- Computes dollarized DEX/GEX when spot is available.
- Computes vanna proxy from `vega`, `volatility`, spot, OI, and multiplier.
- Computes net charm from Greeks/model inputs.

Classification:

| Output | Classification | Action |
| --- | --- | --- |
| `call_delta`, `put_delta`, `net_delta` | `derived_because_schwab_does_not_provide` | Keep; Schwab provides per-contract delta, not aggregate dealer exposure. |
| `call_gamma`, `put_gamma`, `net_gamma` | `derived_because_schwab_does_not_provide` | Keep. |
| `call_gex_1pct`, `put_gex_1pct` | `derived_because_schwab_does_not_provide` | Keep. |
| `call_vanna`, `put_vanna` | `derived_because_schwab_does_not_provide` proxy | Keep, document formula. |
| `net_charm_daily` | `derived_because_schwab_does_not_provide` model | Keep, but should use Schwab-native Greeks/IV when available. |

### `math_volatility.py`

Current behavior:

- Extracts ATM IV from contract `volatility`.
- Computes expected move from straddle mark or IV/time.
- Computes IV skew, realized volatility, ATR, IV rank/percentile, and volatility envelopes.

Classification:

| Output | Classification | Action |
| --- | --- | --- |
| ATM IV from `volatility` | `schwab_native_normalized` input aggregation | Keep. |
| Expected move | `derived_because_schwab_does_not_provide` | Keep. |
| IV skew | `derived_because_schwab_does_not_provide` | Keep; uses Schwab IV as input. |
| Realized volatility / ATR | `derived_because_schwab_does_not_provide` | Keep; derived from Schwab price history. |
| IV rank/percentile | `derived_because_schwab_does_not_provide` | Keep; historical transform. |

### `market_data_adapter.py` and `snapshot_normalizer.py`

Current behavior:

- Schwab price-history candles provide `datetime`, `open`, `high`, `low`, `close`, and `volume`.
- `market_data_adapter.py` normalizes these bars and adds `_ts`.
- `snapshot_normalizer.py` creates synthetic 1m rows from sub-minute snapshots and recomputes candle body/range/direction and VWAP side.

Classification:

| Field/output | Classification | Action |
| --- | --- | --- |
| Price-history `open/high/low/close/volume/datetime` | `schwab_native_normalized` | Keep normalized. |
| `_ts` epoch seconds | `schwab_native_normalized` transform | Keep. |
| Synthetic 1m snapshot OHLC | `derived_because_schwab_does_not_provide` aggregation | Keep, labeled normalized-from-subminute. |
| `candle_body_pts`, `candle_range_pts`, `candle_direction` | `derived_because_schwab_does_not_provide` | Keep. |
| `vwap_side` | `derived_because_schwab_does_not_provide` | Keep; Schwab supplies inputs, not the label. |

### `market_state.py` and `server.py`

Current behavior:

- `market_state.py` is the intended derived trader-state layer.
- `server.py` fetches Schwab data, normalizes contracts, computes many intermediate values, builds `MarketState`, then augments `ms_dict` for payload/UI/v2.
- `server.py` also computes or falls back for spreads, VWAP, session/state context, REST cumulative delta proxy, expected move, IV model spread, and UI fields.

Classification:

| Output group | Classification | Action |
| --- | --- | --- |
| Regime, zone, pin strength, signal labels | `derived_because_schwab_does_not_provide` | Keep in `market_state.py`/math layer. |
| Option-chain selection proof | `derived_because_schwab_does_not_provide` | Keep, but ensure `chain_row` contains normalized Schwab-native fields. |
| UI strings and color labels | `presentation_only` | Keep out of source-of-truth contracts. |
| REST quote spread fallback | `derived_fallback_because_schwab_unavailable` | Use Schwab bid/ask/mark/timestamps first; retain fallback with provenance. |
| VWAP fallback from bars | `derived_fallback_because_schwab_unavailable` | Use Schwab/API VWAP when available; otherwise label bar-derived fallback. |
| `v2_decision` attachment | adapter output | Should consume canonical fields, not raw-only gaps. |

---

## Priority Fix List

### Tier 1 - Trading/A2 Readiness

1. Promote Schwab-native `theta` in `chains.contract_fields()`.
2. Promote Schwab-native `rho` with the rest of the Greek set.
3. Promote `quoteTimeInLong` and `tradeTimeInLong` for option-chain freshness and replay.
4. Update A2 tests/source expectations so Schwab `theta` is the primary path and Black-Scholes is last-resort only.
5. Update `realized_contract_eval.serialize_option_chain_for_eval()` to persist `theta`, `rho`, `quoteTimeInLong`, and `tradeTimeInLong`.

### Tier 2 - Replay, Model Audit, and Liquidity Diagnostics

1. Promote `theoreticalOptionValue`.
2. Promote option OHLC fields: `openPrice`, `highPrice`, `lowPrice`, `closePrice`.
3. Promote `lastSize` and `bidAskSize`.
4. Promote contract safety metadata: `expirationType`, `settlementType`, `exerciseType`, `inTheMoney`, `nonStandard`, `mini`, and `lastTradingDay`.
5. Preserve chain-level `underlyingPrice`, `interestRate`, `dividendYield`, `isDelayed`, and `isChainTruncated` as canonical chain context.

### Tier 3 - Presentation and Completeness

1. Promote low-risk metadata when useful for UI/audit: `description`, `exchangeName`, `optionRoot`, `pennyPilot`, `deliverableNote`.
2. Separate UI display fields from source-of-truth fields in payload docs.
3. Keep derived labels clearly labeled as `presentation_only`.

---

## Disagreement Detection

Runtime priority does not mean derived paths become invisible. For every field where Schwab and a derived fallback can both produce a value, the system should periodically compare them off-path.

Governance event:

```text
FIELD_SOURCE_DISAGREEMENT
```

Trigger:

```text
abs(normalized_schwab_value - derived_value) exceeds a governed threshold
```

Purpose:

```text
Detect unit mismatches, stale payloads, broken derivation math, or Schwab semantic changes without changing runtime source priority.
```

Example:

```text
Schwab theta remains authoritative at runtime. Black-Scholes theta can still be computed for audit. If residual exceeds the approved tolerance, emit FIELD_SOURCE_DISAGREEMENT rather than silently trusting the fallback formula.
```

Thresholds are policy-object pending and must be set per field family.

---

## Regression-Test Pattern

Every promoted Schwab primitive used by a decision consumer should have a test following this pattern:

```python
def test_<field>_prefers_schwab_over_derivation():
    """When Schwab provides <field>, consumer reads schwab_native_normalized,
    not the derived fallback path."""
```

Prototype already implemented:

```text
test_a2_prefers_schwab_theta_over_bs_approximation
```

Tier B timestamp coverage is also present:

```text
chains.contract_fields() promotes quoteTimeInLong and tradeTimeInLong
realized_contract_eval.serialize_option_chain_for_eval() preserves quoteTimeInLong and tradeTimeInLong
tests/test_schwab_option_normalization.py verifies both paths
```

---

## Non-Replacement List

These should not be replaced by Schwab fields because they are app analytics, strategy state, or policy outputs:

```text
GEX / DEX / dollarized exposure
gamma walls / delta walls / pin rails
vanna and charm aggregates
expected move
IV skew
realized volatility
ATR and volatility envelopes
book imbalance
cumulative delta proxy
options-flow score
RVOL
institutional flow proxy
option-expression score
liquidity gates
breakeven
stop/target policy
Kelly sizing
ML predictions and calibration outputs
replay PnL assumptions
UI labels, arrows, colors, and display strings
```

---

## Recommended Implementation Sequence

1. Add the Tier 1 normalized fields to `chains.contract_fields()`.
2. Add focused tests proving normalized contracts include `theta`, `rho`, `quoteTimeInLong`, and `tradeTimeInLong` when Schwab sends them.
3. Update A2 tests so direct Schwab theta wins over Black-Scholes fallback.
4. Update replay serialization to persist the Tier 1 fields.
5. Add Tier 2 fields in a second pass, with tests around replay and option selection proof snapshots.
6. Revisit `v2_decision` source labels after the normalized fields are stable.

