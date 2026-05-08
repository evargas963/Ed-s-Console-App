# Schwab Remediation S014/S015 REST Cum Delta Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S014 `DEFAULT_ZERO_OR` aggregate; S015 `GET_DEFAULT_ZERO` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.quote.lastPrice; quotes.quote.lastSize; quotes.quote.bidPrice; quotes.quote.askPrice
Derived-field disposition: REPLACE_WITH_SCHWAB_OR_GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

REST cumulative delta is a fallback proxy that may only update from Schwab REST quote fields. `lastSize` is required for a trade-size contribution.

Missing Schwab `lastSize` must not be treated as zero-size flow. If no valid REST trade size has contributed for a ticker, the fallback accumulator remains unavailable and must not inject `0.0` as if it were a measured flow value.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `server._update_rest_cum_delta` | fixed-in-this-slice | `server.py::_update_rest_cum_delta` | Missing `lastSize` returns existing accumulator or `None`; no zero-size contribution. |
| `server._fetch_state` REST cum-delta injection | covered-by-contract | `server.py::_fetch_state` | Injects REST fallback only when `_rest_cum_delta` has a real ticker entry. |

No `pending-follow-up` rows remain for this REST cum-delta sub-slice.

## Verification

```text
python -m pytest tests/test_server_rest_cum_delta_contract.py tests/test_server_quote_source_contract.py
```

Expected: missing Schwab `lastSize` keeps REST cum delta unavailable, present `lastSize` updates the accumulator, and targeted residual search for REST `lastSize` zeroing returns no matches.
