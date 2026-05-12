# Schwab Field Normalization Audit

**Status:** Initial option-chain normalization audit  
**Created:** 2026-05-05  
**Observed inventory:** `schwab_field_inventory/schwab_field_dictionary.csv`  
**Runtime boundary:** `chains.contract_fields()`

**See also:** `docs/SCHWAB_FIELD_REFERENCE.md` (live inventory counts and canonical dictionary layout).

---

## Purpose

This audit compares Schwab option-chain fields observed in the live inventory against the fields currently promoted by the app normalization layer. It exists to prevent A2/v2 and replay logic from deriving values that Schwab already provides.

Source priority:

```text
schwab_native_normalized > schwab_native_raw_fallback > derived_fallback_because_schwab_unavailable > unavailable
```

Source classification is the data-origin axis. It is separate from the v2 source indicator axis (`v2_compliant`, `v1_approximation`, `not_implemented`, `policy_object_pending`).

---

## Confirmed Greek Gap

Schwab provides all five core option Greeks on call and put contracts:

```text
delta
gamma
rho
theta
vega
```

Before this audit, `chains.contract_fields()` normalized only:

```text
delta
gamma
vega
```

Gap:

```text
theta
rho
```

Impact:

```text
A2 theta was falling through to Black-Scholes whenever the selected row came from normalized contracts, even though Schwab provided raw theta.
```

---

## Per-Contract Normalization Checklist

| Schwab field | Current concern | Priority |
| --- | --- | --- |
| `theta` | Required for A2 theta gate/source labeling. | Tier 1 |
| `rho` | Greek completeness and replay parity. | Tier 1 |
| `quoteTimeInLong` | Required for quote-staleness gates. | Tier 1 |
| `tradeTimeInLong` | Required for replay/live freshness checks. | Tier 1 |
| `theoreticalOptionValue` | Useful for market-vs-model diagnostics. | Tier 2 |
| `openPrice` | Option OHLC replay context. | Tier 2 |
| `highPrice` | Option OHLC replay context. | Tier 2 |
| `lowPrice` | Option OHLC replay context. | Tier 2 |
| `closePrice` | Option OHLC replay context. | Tier 2 |
| `lastSize` | Tape/size context. | Tier 2 |
| `bidAskSize` | Liquidity display/diagnostics. | Tier 2 |
| `expirationType` | 0DTE/weekly/monthly filtering. | Tier 2 |
| `settlementType` | Settlement/exercise risk. | Tier 2 |
| `exerciseType` | Contract governance. | Tier 2 |
| `inTheMoney` | Selection proof/debug context. | Tier 2 |
| `nonStandard` | Contract safety filter. | Tier 2 |
| `mini` | Multiplier/contract-size ambiguity. | Tier 2 |
| `lastTradingDay` | Expiry/replay context. | Tier 2 |
| `pennyPilot` | Spread/tick context. | Tier 3 |
| `deliverableNote` | Non-standard deliverable context. | Tier 3 |

---

## Bound Fix Sequence

1. Add Tier 1 fields to `chains.contract_fields()`.
2. Preserve Tier 1 fields in `realized_contract_eval.serialize_option_chain_for_eval()`.
3. Make A2 theta source priority explicit:

```text
chain_row.theta -> v2_compliant / schwab_chain_theta
chain_row.raw.theta -> v2_compliant / schwab_raw_theta
Black-Scholes -> v1_approximation / black_scholes_approximation
```

4. Add tests for the data-plane and A2 regression path.

---

## Tier Status

| Tier | Fields | Status |
| --- | --- | --- |
| A | Greeks, bid/ask, sizes, direct A2 inputs | Greeks and size/context promotion implemented in the current working tree. |
| B | `quoteTimeInLong`, `tradeTimeInLong` | Implemented in `chains.contract_fields()` and `realized_contract_eval.serialize_option_chain_for_eval()`, with tests. |
| C | `theoreticalOptionValue`, `theoreticalVolatility` | Promoted/preserved in current working tree; broader consumer usage remains audit-only. |
| D | option OHLC, OI, totalVolume, metadata | Promoted/preserved in current working tree where per-contract fields are available. |

---

## Disagreement Audit

When both Schwab and a derived fallback exist, runtime must prefer Schwab. The derived value may still be computed off-path for monitoring. If the residual exceeds a governed threshold, emit:

```text
FIELD_SOURCE_DISAGREEMENT
```

Initial monitored candidate:

```text
Schwab theta vs Black-Scholes theta
```

Thresholds are policy-object pending.

