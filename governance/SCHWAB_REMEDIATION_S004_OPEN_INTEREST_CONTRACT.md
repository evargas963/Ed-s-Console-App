# Schwab Remediation S004 Open Interest Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slice:** S004 `DEFAULT_ZERO_OR` x `oi`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.openInterest; chains.putExpDateMap.*.openInterest
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Option-chain `openInterest` is a Schwab-native primitive. Runtime exposure, level, probability, and server summary calculations must not silently convert missing `openInterest` into `0`.

If OI is absent, OI-dependent outputs must remain unavailable, skip that contract, or return an explicit missing-OI label. Real Schwab `0` OI may remain zero when the field is present.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `math_exposure_core.compute_exposures_by_strike` | fixed-in-this-slice | `math_exposure_core.py::compute_exposures_by_strike` | Exposure buckets preserve missing `openInterest` as `None`; OI-scaled greeks/dollars are computed only when OI exists. |
| `math_exposure_core.compute_net_charm` | fixed-in-this-slice | `math_exposure_core.py::compute_net_charm` | Charm and gamma-pin weighting skip contracts missing OI or multiplier. |
| `math_probabilities.compute_volume_oi_ratio` | fixed-in-this-slice | `math_probabilities.py::compute_volume_oi_ratio` | Reports `missing_oi` instead of `no_oi` or dormant zero when OI is absent. |
| `math_probabilities.compute_pin_score` | fixed-in-this-slice | `math_probabilities.py::compute_pin_score` | Missing OI concentration returns explicit `missing_oi`. |
| `math_probabilities.compute_smart_money_signal` | fixed-in-this-slice | `math_probabilities.py::compute_smart_money_signal` | Volume/OI component sums only present OI. |
| `math_levels._pick_oi_center` | fixed-in-this-slice | `math_levels.py::_pick_oi_center` | OI center skips buckets with missing call/put OI. |
| `math_levels.build_walls_rows` totals | fixed-in-this-slice | `math_levels.py::build_walls_rows` | Totals sum only present OI. |
| `math_levels.compute_gamma_void_zones` | fixed-in-this-slice | `math_levels.py::compute_gamma_void_zones` | Missing OI is not classified as low-OI. |
| `server._fetch_state` predictive positioning summaries | fixed-in-this-slice | `server.py::_fetch_state` Section 8 | DPI and pin concentration receive `None` when total/pin OI is missing. |
| `server._fetch_state` gamma-void diagnostics | fixed-in-this-slice | `server.py::_fetch_state` gamma-void diagnostic block | Diagnostic max/low OI calculations ignore missing OI instead of counting it as zero. |

No `pending-follow-up` rows remain for S004.

## Verification

```text
python -m pytest tests/test_multiplier_no_default.py tests/test_math_probabilities_volume_contract.py tests/test_open_interest_contract.py tests/test_order_flow_volume_contract.py tests/test_liquidity_engine.py tests/test_signal_layer_v1.py
```

Expected: focused OI tests pass and targeted residual search for `openInterest`/bucket-OI zero substitution returns no matches.
