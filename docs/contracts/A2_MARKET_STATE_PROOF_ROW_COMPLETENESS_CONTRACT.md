# A2 Market-State Proof Row Completeness Contract

**Status:** Draft implementation contract  
**Date:** 2026-05-07  
**Module:** `market_state` option-expression proof handoff to A2  
**Scope:** Preserve Schwab-native selected contract fields from normalized chain rows into `option_chain_selection_proof.winner.chain_row` and related proof rows.

This contract fixes a data-flow defect: A2 can only use Schwab-native fields if the selected option proof row carries them. The current proof snapshot trims the selected chain row to a small audit subset and drops fields A2 needs for theta, implied volatility (**Schwab wire `volatility`**), quote freshness, and source labeling.

---

## Schwab canonical binding (normative)

Authoritative leaf list: `schwab_field_inventory/schwab_field_dictionary.csv` (`canonical_field`). Normalized option contract rows in this repo use the same leaf names as **`chains.callExpDateMap.*.<leaf>`** and **`chains.putExpDateMap.*.<leaf>`**. Proof rows and this contract MUST use those wire names — not aliases such as non-canonical **`volume`** (use **`totalVolume`**), **`expiration`** (use **`expirationDate`**), or **`iv`** as a persisted key (use **`volatility`**).

| Topic | Wire / rule |
|---|---|
| Contract identity | `symbol`, `putCall`, `strikePrice`, `expirationDate`, `daysToExpiration`, … |
| Quotes | `bid`, `ask`, `mark`, `last`, sizes, `totalVolume`, `openInterest` |
| Implied vol | **`volatility`** (+ optional `theoreticalVolatility`, `theoreticalOptionValue`) |
| Greeks | `delta`, `gamma`, `theta`, `vega`, `rho` |
| Clock | `quoteTimeInLong`, `tradeTimeInLong` |
| Derived (not Schwab leaves) | Mid `(bid+ask)/2`, spread width `ask-bid`, DTE from calendar vs `daysToExpiration` — label source accordingly |

Black-Scholes fallback inputs, when used elsewhere, must take underlying price from an equity quote canonical such as **`quotes.regular.regularMarketLastPrice`**, not an unlabeled internal `spot` key as stand-in for Schwab truth.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract changes data preservation across an advisory proof handoff. It does not place orders, promote A2 to trade authority, change Module A/A1 authority, change model predictions, or authorize new option execution behavior.

---

## Scope

In scope:

- expand `market_state._oe_chain_row_snapshot()` to preserve A2-required Schwab-native fields from the normalized selected contract row;
- preserve these fields in `option_chain_selection_proof.chain_rows_scored[*].chain_row`;
- preserve these fields in `option_chain_selection_proof.ranked_candidates_top5[*].chain_row`;
- ensure `option_chain_selection_proof.winner.chain_row` is present for the winning contract, or add it if missing;
- add tests proving `theta`, `rho`, **`volatility`**, and quote/trade timestamps survive from normalized contract input into the proof row consumed by A2;
- add an integration test that builds a proof through `market_state.recommend_option_expression()` and then feeds it to `build_a2_option_expression()`;
- re-measure theta availability after the fix lands.

Out of scope:

- changing A2 authority or lifecycle authority;
- binding Black-Scholes theta as a primary path;
- changing Schwab API request parameters;
- changing DB schema;
- backfilling historical `option_chain_json`;
- changing model training features;
- solving repo-wide source-labeling outside this handoff.

---

## Root Cause

Current implementation:

```text
market_state._oe_chain_row_snapshot()
  -> emits narrow subset:
     symbol, expirationDate, strikePrice, putCall,
     bid, ask, totalVolume, openInterest, gamma, delta
```

This was acceptable as a lightweight audit proof when the proof row was display/debug context. It is no longer sufficient because A2 consumes `winner.chain_row` for hard inputs and readiness gates.

Observed omitted fields include:

```text
theta
rho
vega
volatility
theoreticalVolatility
theoreticalOptionValue
quoteTimeInLong
tradeTimeInLong
mark
last
bidSize
askSize
bidAskSize
lastSize
openPrice
highPrice
lowPrice
closePrice
expirationType
settlementType
exerciseType
lastTradingDay
multiplier
extrinsicValue
timeValue
intrinsicValue
inTheMoney
nonStandard
mini
pennyPilot
deliverableNote
```

Consequences:

- A2 may compute Black-Scholes theta even when Schwab theta was present upstream.
- A2 may emit `missing_quote_timestamp` or stale quote gates even when Schwab quote timestamps were present upstream.
- A2 source labels can degrade to `v1_approximation` or `not_implemented` because the proof row lost the original normalized field.
- Historical archive theta missingness was misread as Schwab behavior when it was an internal data-flow issue.

---

## Required Field Contract

`_oe_chain_row_snapshot()` MUST preserve the following groups when present on the normalized contract row:

| Group | Required fields |
|---|---|
| Contract identity | `symbol`, `putCall`, `strikePrice`, `expirationDate`, `expirationType`, `settlementType`, `exerciseType`, `lastTradingDay` |
| Prices and liquidity | `bid`, `ask`, `mark`, `last`, `openPrice`, `highPrice`, `lowPrice`, `closePrice`, `breakEven`, `bidSize`, `askSize`, `bidAskSize`, `lastSize`, `totalVolume`, `openInterest` |
| Greeks and implied vol (`volatility`) | `delta`, `gamma`, `theta`, `vega`, `rho`, `volatility`, `theoreticalVolatility`, `theoreticalOptionValue` |
| Timestamps | `quoteTimeInLong`, `tradeTimeInLong` |
| Contract metadata | `multiplier`, `extrinsicValue`, `timeValue`, `intrinsicValue`, `inTheMoney`, `nonStandard`, `mini`, `pennyPilot`, `deliverableNote` |

**Schwab CSV alignment (2026-05-10):** The proof row intentionally omits non-canonical aliases **`expiration`** and **`volume`** — only **`expirationDate`** and **`totalVolume`** have `chains.callExpDateMap.*` dictionary rows. Raw Schwab payloads may still carry aliases; normalization for proof uses canonical leaves only.

**RC-388 addendum (2026-08-24):** `breakEven` (dictionary rows `chains.callExpDateMap.*.breakEven` / `chains.putExpDateMap.*.breakEven`, first seen 2026-08-15) is preserved so A2 serves the vendor breakeven as authoritative; the A2 strike +/- mid derivation remains only as the explicitly-labeled fallback (`breakeven_source = "v1_approximation"`).

The snapshot SHOULD continue to omit the full `raw` payload unless a future contract explicitly authorizes raw passthrough into the proof object. The intended boundary remains normalized Schwab fields first.

---

## Winner Proof Requirement

`recommend_option_expression()` MUST ensure:

```text
option_chain_selection_proof.winner.chain_row
```

contains the full normalized selected contract snapshot for the winning strike/side.

The same preservation rule applies to:

```text
option_chain_selection_proof.chain_rows_scored[*].chain_row
option_chain_selection_proof.ranked_candidates_top5[*].chain_row
```

If no selected contract row exists, the proof MUST fail closed with an explicit reason already compatible with A2's `missing_option_chain_selection_proof` / no-contract behavior. It must not fabricate Schwab-native fields.

---

## A2 Source Discipline

After this fix:

```text
chain_row.theta present -> A2 theta source may be v2_compliant / Schwab chain theta
chain_row.quoteTimeInLong present -> A2 quote staleness gate has real Schwab timestamp input
chain_row.volatility present -> A2 implied-vol source may be Schwab-native normalized (wire key `volatility`, not `iv`)
```

Black-Scholes theta remains only a fallback permitted by the current A2 contract until post-fix measurement and governance decide whether to retain or remove it.

This contract does not authorize treating Black-Scholes theta as structurally primary.

---

## Required Tests

The implementation slice MUST add or update tests that prove:

1. `_oe_chain_row_snapshot()` preserves all A2-required Schwab-native fields listed in this contract.
2. `recommend_option_expression()` attaches `winner.chain_row` with `theta`, `volatility`, `quoteTimeInLong`, and `tradeTimeInLong` when the selected normalized contract has them.
3. `build_a2_option_expression()` receives the proof row from `market_state.recommend_option_expression()` and uses Schwab theta rather than Black-Scholes when theta is present.
4. A2 quote staleness calculation uses `quoteTimeInLong` from the preserved proof row when present.
5. The no-contract / missing-row path still fails closed and does not fabricate missing Schwab fields.

Optional but recommended:

```text
Regression test using SPY/QQQ-like 0DTE fixture rows with theta/rho/timestamps populated.
```

---

## Post-Fix Measurement

After implementation and before further A2 slice work, run a fresh measurement over post-fix archive rows:

```text
theta_key_missing_rate
theta_present_null_rate
theta_present_numeric_rate
quoteTimeInLong_present_rate
tradeTimeInLong_present_rate
```

Minimum reporting dimensions:

```text
ticker
UTC date
snapshot count
contract count
selected-expiry rows vs all archived rows
```

Decision rule:

- If post-fix live/archive theta missingness is approximately zero for SPY/QQQ 0DTE, revise A2 theta contract language toward Schwab-theta-only with `WAIT` on absent theta, and remove or quarantine Black-Scholes.
- If post-fix missingness remains material and is verified as Schwab/API behavior rather than internal truncation, draft a narrow operator decision for residual Black-Scholes fallback.
- If missingness is mixed by endpoint/session/request shape, document the condition and gate fallback to those conditions only.

---

## Non-Goals

This contract intentionally does not solve:

- source labeling consistency across all non-v2 consumers;
- index symbol canonicalization for NDX;
- DB backup convention unification;
- stale quote carry-forward in `live_market_plane`;
- mark-vs-**derived**-mid global price precedence (`mid` is not a Schwab dictionary leaf).


