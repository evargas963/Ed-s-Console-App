> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/SCHWAB_FIELD_REFERENCE.md`.

# Schwab Field Reference

**Status:** OBSERVED FROM LIVE SCHWAB MARKET-DATA API  
**Created:** 2026-05-05  
**Last refreshed:** 2026-05-05 after Schwab re-authentication  
**Purpose:** Preserve a durable reference for Schwab market-data fields used by EdWebConsole and prevent derived values from silently replacing fields Schwab already provides.

**See also:** `docs/SCHWAB_FIELD_NORMALIZATION_AUDIT.md` (option-chain normalization vs `chains.contract_fields()`).

**SUPERSEDED, retired (reality-reconciliation audit, 2026-09-18):** `schwab_field_inventory/README.md` marks this document retired under ED CONSOLE SLIMMING alongside `docs/SCHWAB_FIELD_NORMALIZATION_AUDIT.md`. Same root cause: `chains.py` (and its `contract_fields()`) was deleted by commit `fb1e84c3`, 2026-05-12, one week after this document's own creation date — zero references remain anywhere in the current codebase. The gap this document's "Required Next Steps" flags (theta/rho missing from normalization) is empirically closed today, through a different mechanism than the one this doc names: `server.py::flatten_chain_contracts` does an unrestricted `dict(ct)` passthrough of every raw Schwab field including `theta`/`rho`, and `market_state.py::_oe_chain_row_snapshot()` explicitly carries `theta`/`rho`/`quoteTimeInLong`/`theoreticalOptionValue` and the full field list this doc asks to be promoted, verbatim. `realized_contract_eval.serialize_option_chain_for_eval()` (line 178's flagged omission) now also does a generic passthrough (`dict(ct)` minus `raw`), so it no longer drops `theta` either. The "Live Inventory" section below (what Schwab actually sends) is unaffected by this correction and remains a useful reference; only the `chains.contract_fields()`-based normalization gap and "Required Next Steps" are stale.

---

## Live Inventory

Command run:

```text
python schwab_full_field_inventory.py
```

Result:

```text
Requests made: 50
Successful: 50
Failed: 0
Raw/field files: 50
Total unique raw field paths discovered: 468,039
```

Canonical dictionary command:

```text
python schwab_field_dictionary_builder.py
```

Canonical result:

```text
Raw field count: 468,039
Canonical field count: 2,393
Greek-category canonical fields: 10
Option-chain canonical fields: 74
```

Reference files saved in the repo:

```text
schwab_field_inventory/schwab_all_fields_master.txt
schwab_field_inventory/schwab_field_inventory_summary.csv
schwab_field_inventory/schwab_canonical_fields.txt
schwab_field_inventory/schwab_field_dictionary.csv
schwab_field_inventory/schwab_field_dictionary_grouped.csv
```

Note: the inventory script emitted a websocket shutdown warning after successful completion. REST probes succeeded and the field files were written.

---

## Observed Schwab Option Greeks

Schwab option-chain payloads **do provide theta**.

Observed canonical Greek fields:

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

Example raw observed field paths include:

```text
callExpDateMap.2026-05-05:0.675.0.0.theta
putExpDateMap.2028-12-15:955.760.0.0.theta
```

Conclusion:

```text
theta must be treated as a Schwab-provided field, not primarily as a derived field.
```

---

## Current Normalized Option Contract Fields

`chains.contract_fields()` currently preserves these normalized option-chain fields:

```text
putCall
strikePrice
openInterest
delta
gamma
vega
theoreticalVolatility
volatility
daysToExpiration
expirationDate
multiplier
mark
bid
ask
last
totalVolume
bidSize
askSize
extrinsicValue
timeValue
intrinsicValue
symbol
raw
```

Important gap:

```text
theta is not currently normalized by chains.contract_fields()
```

Because `raw` is preserved, Schwab-provided theta may still exist at:

```text
contract["raw"]["theta"]
```

Consumers should not have to depend on raw fallback for core Greeks. Live inventory confirms Schwab sends `theta`, so `theta` must be promoted into the normalized contract fields.

---

## Fields Expected By Existing Code

Existing code already expects or recognizes these Schwab option-chain fields:

```text
theta
rho
delta
gamma
vega
volatility
theoreticalVolatility
daysToExpiration
bid
ask
bidSize
askSize
mark
last
totalVolume
volume
openInterest
tradeTimeInLong
quoteTimeInLong
expirationDate
expiration
strikePrice
putCall
symbol
underlyingSymbol
multiplier
```

Evidence:

- `order_flow_engine.py` reads `theta` and `daysToExpiration`.
- `schwab_field_dictionary_builder.py` classifies `theta` and `rho` as Greeks.
- `realized_contract_eval.serialize_option_chain_for_eval()` persists several option fields but currently omits `theta`.
- `chains.contract_fields()` preserves `raw` but does not normalize `theta`.

---

## Consistency Rule

For all A2 / 0DTE work:

1. Prefer Schwab-provided normalized fields.
2. If a field is sent by Schwab but not normalized, fix normalization before deriving it.
3. Use `raw` only as a temporary bridge while normalization is being corrected.
4. Derive only when Schwab did not provide the field in the selected endpoint/parameter set.
5. Derived fields must carry `source: "v1_approximation"` or stricter provenance, never `v2_compliant`.

For theta specifically:

```text
normalized theta > raw theta > Black-Scholes fallback > theta_unavailable gate
```

---

## Required Next Steps

Update code so normalized contracts preserve Schwab-provided Greeks and timestamps before any A2 derivation:

```text
chains.contract_fields()
realized_contract_eval.serialize_option_chain_for_eval()
v2_decision/a2_option_expression.py
```

Minimum immediate fix:

```text
Add theta and rho to chains.contract_fields().
Consider promoting quoteTimeInLong, tradeTimeInLong, theoreticalOptionValue, closePrice, openPrice, highPrice, lowPrice, lastSize, bidAskSize, expirationType, settlementType, exerciseType, inTheMoney, and nonStandard.
```

