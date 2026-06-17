> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S003_OHLCV_CONTRACT.md`.

# Schwab Remediation S003/S006 OHLCV Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S003 `DEFAULT_ZERO_OR` x `ohlcv`; S006 `GET_DEFAULT_ZERO` x `ohlcv`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): pricehistory.candles.*.open; pricehistory.candles.*.high; pricehistory.candles.*.low; pricehistory.candles.*.close; pricehistory.candles.*.volume
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Price-history candle OHLC fields are Schwab-native primitives. Runtime bar normalization and OHLC-dependent analytics must not turn missing `open`, `high`, `low`, or `close` into `0`.

Incomplete bars must be dropped before analytic use. Volume remains governed by S002/S007: missing volume is preserved as missing and volume-weighted calculations skip/fail closed.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `market_data_adapter.normalize_bar` | fixed-in-this-slice | `market_data_adapter.py::normalize_bar` | Generic normalized bars now require complete OHLC; missing OHLC returns `None`. |
| `market_data_adapter.schwab_candles_to_bars` | fixed-in-this-slice | `market_data_adapter.py::schwab_candles_to_bars` | Schwab price-history candles missing any OHLC field are dropped. |
| `liquidity_value_engine._bars_to_list` | fixed-in-this-slice | `liquidity_value_engine.py::_bars_to_list` | Normalized list/DataFrame bars skip incomplete OHLC rows. |
| `liquidity_value_engine.compute_session_vwap` | fixed-in-this-slice | `liquidity_value_engine.py::compute_session_vwap` | Receives only complete OHLC rows from `_bars_to_list`; no OHLC zero injection. |
| `liquidity_value_engine.compute_vwap_bands` | fixed-in-this-slice | `liquidity_value_engine.py::compute_vwap_bands` | Receives complete OHLC rows and uses missing-volume fail-closed behavior from S002. |
| `liquidity_value_engine._volume_profile_poc_vah_val` | fixed-in-this-slice | `liquidity_value_engine.py::_volume_profile_poc_vah_val` | Receives complete OHLC rows; no missing OHLC to zero conversion. |
| `liquidity_value_engine.compute_atr_from_bars` | fixed-in-this-slice | `liquidity_value_engine.py::compute_atr_from_bars` | Skips incomplete OHLC bars instead of computing true range from zero defaults. |
| `features.signal_layer_v1._aggregate_bars` | fixed-in-this-slice | `features/signal_layer_v1.py::_aggregate_bars` | 5m/15m synthetic bars require complete source OHLC; incomplete chunks are skipped. |
| `features.signal_layer_v1._tr` | fixed-in-this-slice | `features/signal_layer_v1.py::_tr` | True range no longer turns missing high/low into zero; falls back to close only when close exists. |
| `market_context._volume_profile_poc_vah_val` | fixed-in-this-slice | `market_context.py::_volume_profile_poc_vah_val` | Skips bars missing high/low/close/volume. |
| `market_context._vwap_bands` | fixed-in-this-slice | `market_context.py::_vwap_bands` | Skips bars missing high/low/close/volume. |
| `market_context.build_market_context` intraday VWAP/ORB loop | fixed-in-this-slice | `market_context.py::build_market_context` | VWAP uses only complete OHLCV bars; ORB updates only when high/low are present. |
| `liquidity_value_engine` zone classification thresholds | not-applicable | `liquidity_value_engine.py::cluster_price_levels_into_zones` | Broad regex match on prior-day level comparisons, not OHLCV normalization. |
| `server.py` exposure diagnostics | not-applicable | `server.py` gamma/OI diagnostic sums | Broad regex match for exposure bucket defaults, not price-history OHLCV. |
| `audit_snapshot_data.py` CLI formatting | not-applicable | `audit_snapshot_data.py` print formatting | Display-only formatting for audit output, not runtime OHLCV source construction. |
| `monte_carlo.py` simulation output logging | not-applicable | `monte_carlo.py` output/logging fallbacks | Simulation result handling, not Schwab candle OHLCV normalization. |

No `pending-follow-up` rows remain for S003/S006.

## Verification

```text
python -m pytest tests/test_liquidity_engine.py tests/test_signal_layer_v1.py tests/test_instrument_identity_and_repair_v1.py
```

Expected: focused OHLCV tests pass, including incomplete-bar fail-closed behavior.
