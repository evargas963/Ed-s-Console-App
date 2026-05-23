> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S002_VOLUME_CONTRACT.md`.

# Schwab Remediation S002 Volume Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S002 `DEFAULT_ZERO_OR` x `volume`; S007 `GET_DEFAULT_ZERO` x `volume`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.quote.totalVolume; chains.callExpDateMap.*.totalVolume; chains.putExpDateMap.*.totalVolume; pricehistory.candles.*.volume; streaming.content.*.VOLUME
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Volume-dependent runtime analytics must not silently convert missing Schwab volume into `0`.

Valid Schwab `0` volume may remain `0` when the field is present. Missing volume must remain missing or cause the specific volume-weighted calculation to skip/fail closed.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `order_flow_engine._compute_options_flow` | fixed-in-this-slice | `order_flow_engine.py::_compute_options_flow` | Uses Schwab `totalVolume`; no `lastSize` or `0` fallback. Missing volume returns unavailable option-flow fields. |
| `liquidity_value_engine._bars_to_list` | fixed-in-this-slice | `liquidity_value_engine.py::_bars_to_list` | Normalized bars preserve missing volume as `None`. |
| `liquidity_value_engine.compute_session_vwap` | fixed-in-this-slice | `liquidity_value_engine.py::compute_session_vwap` | VWAP skips missing-volume bars and returns `None` when no volume exists. |
| `liquidity_value_engine.compute_vwap_bands` | fixed-in-this-slice | `liquidity_value_engine.py::compute_vwap_bands` | Volume-weighted variance skips missing-volume bars. |
| `liquidity_value_engine._volume_profile_poc_vah_val` | fixed-in-this-slice | `liquidity_value_engine.py::_volume_profile_poc_vah_val` | Volume profile skips missing-volume bars. |
| `features.signal_layer_v1._aggregate_bars` | fixed-in-this-slice | `features/signal_layer_v1.py::_aggregate_bars` | Aggregated 5m/15m bars do not manufacture volume when any source bar is missing volume. |
| `features.signal_layer_v1._volume_profile_proxy` | fixed-in-this-slice | `features/signal_layer_v1.py::_volume_profile_proxy` | Value-area proxy no longer uses fake unit volume. |
| `features.signal_layer_v1.compute_signal_layer_v1` | fixed-in-this-slice | `features/signal_layer_v1.py::compute_signal_layer_v1` | Rolling VWAP and participation features fail closed when volume is missing. |
| `backfill_flow_imbalance._contracts_from_chain_json` | fixed-in-this-slice | `backfill_flow_imbalance.py::_contracts_from_chain_json` | Archived option rows preserve missing `totalVolume`; no synthetic zero. |
| `debug_flow_snapshot._contracts_from_chain_json` | fixed-in-this-slice | `debug_flow_snapshot.py` option row normalization | Debug rows preserve missing `totalVolume`; no synthetic zero. |
| `db.EdDB.upsert_1m_bars` | fixed-in-this-slice | `db.py::EdDB.upsert_1m_bars` | Missing bar volume persists as `NULL`; real non-negative Schwab volume is preserved. |
| `tools.ingest_1m_to_staging.rows_from_candles` | fixed-in-this-slice | `tools/ingest_1m_to_staging.py::rows_from_candles` | Missing staging candle volume remains `NULL`. |
| `server._CandleAccumulator.seed` | fixed-in-this-slice | `server.py::_CandleAccumulator.seed` | Seeded price-history bars require explicit Schwab volume. |
| `server._fetch_state` snapshot candle volume | fixed-in-this-slice | `server.py::_fetch_state` candle-volume block | Snapshot `candle_volume` no longer falls back to tertiary `0.0`. |
| `math_exposure_core.compute_exposures_by_strike` | fixed-in-this-slice | `math_exposure_core.py::compute_exposures_by_strike` | Exposure buckets preserve missing `totalVolume` as `None`; real volumes accumulate only when present. |
| `math_probabilities.compute_volume_oi_ratio` | fixed-in-this-slice | `math_probabilities.py::compute_volume_oi_ratio` | Reports `missing_volume` instead of dormant zero-volume when OI exists but volume is absent. |
| `math_probabilities.atm_flow_window_totals` | fixed-in-this-slice | `math_probabilities.py::atm_flow_window_totals` | Sums only present bucket volume and preserves no-volume fallback behavior. |
| `math_probabilities.compute_smart_money_signal` | fixed-in-this-slice | `math_probabilities.py::compute_smart_money_signal` | Volume/OI component no longer receives synthetic zero volume from missing exposure buckets. |
| `market_context._volume_profile_poc_vah_val` | fixed-in-this-slice | `market_context.py::_volume_profile_poc_vah_val` | Volume profile skips missing-volume bars. |
| `market_context._vwap_bands` | fixed-in-this-slice | `market_context.py::_vwap_bands` | Volume-weighted variance skips missing-volume bars. |
| `market_context.build_market_context` | fixed-in-this-slice | `market_context.py::build_market_context` | Intraday VWAP accumulation only uses bars with present volume. |
| `market_data_adapter.schwab_candles_to_bars` | fixed-in-this-slice | `market_data_adapter.py::schwab_candles_to_bars` | Schwab candle volume stays `None` when absent. |
| `market_data_adapter.normalize_bar` | fixed-in-this-slice | `market_data_adapter.py::normalize_bar` | Generic normalized bars preserve missing volume rather than defaulting to `0.0`. |
| `backfill_flow_imbalance.flow_source_volume` | not-applicable | `backfill_flow_imbalance.py::backfill` result counters | Operational count of fallback source labels, not market-data volume. |
| `audit_snapshot_data` display formatting | not-applicable | `audit_snapshot_data.py` CLI output formatting | Display-only formatting for audit text output, not a runtime market-data source. |
| `server._CandleAccumulator.tick` | fixed-in-this-slice | `server.py::_CandleAccumulator.tick` | Accumulator keeps current bar volume missing until a Schwab `totalVolume` delta exists. |
| `server._liquidity_live_1m_overlay_bars` | fixed-in-this-slice | `server.py::_liquidity_live_1m_overlay_bars` | Overlay serializes missing accumulator volume as `None`, not `0`. |

No `pending-follow-up` rows remain for S002/S007.

## Verification

```text
python -m pytest tests/test_order_flow_volume_contract.py tests/test_liquidity_engine.py tests/test_signal_layer_v1.py tests/test_pilot_step3_data_loader.py
```

Expected: focused volume tests pass, including missing-volume fail-closed behavior.
