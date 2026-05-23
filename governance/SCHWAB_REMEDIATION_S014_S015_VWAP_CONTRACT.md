> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S014_S015_VWAP_CONTRACT.md`.

# Schwab Remediation S014/S015 VWAP Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S014 `DEFAULT_ZERO_OR` aggregate; S015 `GET_DEFAULT_ZERO` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): NO_DIRECT_SCHWAB_EQUIVALENT_FOR_SESSION_VWAP_BANDS; pricehistory.candles.*.open; pricehistory.candles.*.high; pricehistory.candles.*.low; pricehistory.candles.*.close; pricehistory.candles.*.volume
Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE_AND_GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Session VWAP and VWAP bands are derived analytics from Schwab price-history OHLCV bars. They may be computed only when source bars provide complete price and volume data.

If VWAP is missing, VWAP bands must remain unavailable. Snapshot builders must not call `compute_vwap_bands(..., vwap or 0, ...)` or create levels around synthetic zero.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `liquidity_value_engine.build_opening_snapshot` | fixed-in-this-slice | `liquidity_value_engine.py::build_opening_snapshot` | Computes VWAP bands only when `vwap is not None`. |
| `liquidity_value_engine.build_midday_snapshot` | fixed-in-this-slice | `liquidity_value_engine.py::build_midday_snapshot` | Does not create `VWAP_P1`/bands when VWAP is unavailable. |
| `liquidity_value_engine.build_afternoon_snapshot` | fixed-in-this-slice | `liquidity_value_engine.py::build_afternoon_snapshot` | Computes VWAP bands only when `vwap is not None`. |
| `liquidity_value_engine.build_live_snapshot` | fixed-in-this-slice | `liquidity_value_engine.py::build_live_snapshot` | Computes VWAP bands only when `vwap is not None`. |
| `liquidity_value_engine.compute_session_vwap` | already-fixed | `liquidity_value_engine.py::compute_session_vwap` | S002/S003 ensure incomplete OHLCV bars are skipped and missing volume returns `None`. |
| `liquidity_value_engine.compute_vwap_bands` | already-canonical | `liquidity_value_engine.py::compute_vwap_bands` | Derived analytic; caller now gates missing VWAP before invoking. |

No `pending-follow-up` rows remain for this S014/S015 VWAP sub-slice.

## Verification

```text
python -m pytest tests/test_liquidity_engine.py
```

Expected: missing VWAP produces no VWAP bands, and targeted residual search for `vwap or 0` returns no matches.
