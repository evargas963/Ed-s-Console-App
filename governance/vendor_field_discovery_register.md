# Vendor Field Discovery Register (RC-388)

The 2026-08-15 live poll of all six Schwab market-data endpoints found vendor fields our
2026-05-05 catalogue lacked; they were merged into
`schwab_field_inventory/schwab_field_dictionary.csv` and then nothing consumed them.
This register holds the per-field disposition so a discovered field is either consumed,
delivered, or refused with a reason — never silently dropped.

The RC-388 ledger row lists 8 newly discovered leaf paths —
`chains.callExpDateMap.*.breakEven`, `chains.putExpDateMap.*.breakEven`,
`chains.callExpDateMap.*.ssid`, `chains.putExpDateMap.*.ssid`, `chains.hasBinaryOptions`,
`chains.ethOptionEligible`, `quotes.reference.ethOptionEligible`, `pricehistory.symbol` —
and additionally names `bidSize`/`askSize`/`bidAskSize` and `quoteTimeInLong` as
catalogued-but-uningested. All are dispositioned here.

| field | endpoint / leaf | disposition | where / why |
|---|---|---|---|
| `bidSize` | chains per-contract; quotes | CONSUMED | `math_exposure_core.py:239` (per-leg option flow imbalance); `order_flow_engine.py:282,788` (L1 size pressure; chain flatten); preserved on the A2 proof row (`market_state._oe_chain_row_snapshot`) and served on `selected_contract_snapshot`. |
| `askSize` | chains per-contract; quotes | CONSUMED | Same consumers as `bidSize` (`math_exposure_core.py:240`, `order_flow_engine.py:283,789`, A2 proof row). |
| `bidAskSize` | chains per-contract | CONSUMED (passthrough) | Preserved on the A2 proof row and served verbatim on `selected_contract_snapshot`. No parser: it is the vendor's preformatted `"51X43"` display string, redundant with the numeric `bidSize`/`askSize` pair that all computation uses. |
| `quoteTimeInLong` | chains per-contract | CONSUMED | A2 quote-staleness hard gate: `v2_decision/a2_option_expression.py` `_quote_staleness_ms` reads `chain_row.quoteTimeInLong` (threshold per OPERATOR_DECISION_REGISTER O-20). |
| `breakEven` | `chains.callExpDateMap.*.breakEven` / `chains.putExpDateMap.*.breakEven` | DELIVERED-THIS-CHANGE | Vendor breakeven now authoritative for `option_expression.breakeven` (`v2_compliant`, detail `schwab_chain_breakEven`); the strike +/- mid derivation is retained as the explicitly-labeled fallback (`breakeven_source = "v1_approximation"`) when the leaf is absent/None/non-finite. Preserved through `market_state._oe_chain_row_snapshot`. Values measured 2026-08-15 to agree with our derivation to $0.01. |
| `ssid` | `chains.*ExpDateMap.*.ssid` | REFUSED | No streaming subsystem exists to key contracts by ssid; contract identity on the decision path is `chains.*.symbol` (OSI), already consumed. Redundant until a streamer lands — re-disposition then. |
| `ethOptionEligible` | `chains.ethOptionEligible`; `quotes.reference.ethOptionEligible` | REFUSED | No extended-hours option path in production today, so a consumer would be dead code. Becomes load-bearing when NYSE Arca's overnight session begins (announced 2026-12-06) — re-disposition before that date. |
| `hasBinaryOptions` | chains | REFUSED | Binary options are out of scope: no consumer on the decision path, no operator request. |
| `pricehistory.symbol` | pricehistory | REFUSED | Echo of the requested ticker; the request path already pins the symbol, so it is redundant with the request parameter. Revisit only if a series-mismatch defect is ever observed. |
