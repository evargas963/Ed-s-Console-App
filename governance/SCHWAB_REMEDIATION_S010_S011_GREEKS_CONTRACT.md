# Schwab Remediation S010/S011 Greeks Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S010 `DEFAULT_ZERO_OR` x `greeks`; S011 `GET_DEFAULT_ZERO` x `greeks`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.delta; chains.putExpDateMap.*.delta; chains.callExpDateMap.*.gamma; chains.putExpDateMap.*.gamma; chains.callExpDateMap.*.theta; chains.putExpDateMap.*.theta; chains.callExpDateMap.*.vega; chains.putExpDateMap.*.vega; chains.callExpDateMap.*.rho; chains.putExpDateMap.*.rho
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Option Greeks are Schwab-native option-chain primitives. Runtime flow and tradeability calculations must not convert missing chain-row Greeks into zero exposure or neutral signal.

For S010/S011, the actionable HIGH residual is option-flow delta weighting. Option volume may still produce call/put flow if volume is present, but `delta_weighted` must remain unavailable unless at least one Schwab delta value contributes.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `order_flow_engine._compute_options_flow` call delta weighting | fixed-in-this-slice | `order_flow_engine.py::_compute_options_flow` | Missing call delta no longer leaves `delta_weighted` as synthetic `0.0`; result is `None` if no delta contributed. |
| `order_flow_engine._compute_options_flow` put delta weighting | fixed-in-this-slice | `order_flow_engine.py::_compute_options_flow` | Missing put delta no longer leaves `delta_weighted` as synthetic `0.0`; result is `None` if no delta contributed. |
| `server._fetch_state` gamma pin score | not-applicable | `server.py::_fetch_state` Section 8 | Consumes exposure-bucket aggregate `call_gamma`/`put_gamma`, not raw Schwab chain-row Greek fields. Exposure construction is separately governed by `math_exposure_core` multiplier/OI/Greek validity gates. |
| `server._fetch_state` gamma-void diagnostics | not-applicable | `server.py::_fetch_state` gamma-void diagnostic block | Diagnostic over aggregate exposure buckets, not raw Schwab chain-row Greek defaulting. |
| `math_levels._pin_strength` / summary totals / gamma voids | not-applicable | `math_levels.py` aggregate helpers | Operate on aggregate exposure fields where zero is an analytic aggregate value after upstream validation, not a replacement for missing raw Schwab Greeks. |
| `math_probabilities.compute_breakout_score` / `compute_vol_expansion_signal` | not-applicable | `math_probabilities.py` score combiners | Use optional aggregate gamma-gradient inputs; `or 0` is component-neutral scoring behavior, not chain-row Greek source substitution. |
| `call_engine.py` net-delta directional bias | not-applicable | `call_engine.py::_validate_trade` / call assembly | Uses aggregate `SignalInput.net_delta`, not raw option-chain delta. |
| `market_state.derive_zone` | not-applicable | `market_state.py::derive_zone` | Zone selection from aggregate net delta, not raw chain-row delta. |
| `transformer_model.py` static context zeros | not-applicable-to-S010 | `transformer_model.py` feature tensor construction | Model imputation/defaulting belongs to MT/model residual slices, not raw chain-row Greek source replacement. |
| Classifier/test/tool `delta` names | not-applicable | calibration/tools/test residual matches | Generic mathematical delta/edge variables, not Schwab option Greeks. |

No `pending-follow-up` rows remain for S010/S011.

## Verification

```text
python -m pytest tests/test_order_flow_volume_contract.py tests/test_open_interest_contract.py tests/test_multiplier_no_default.py
```

Expected: option-flow delta weighting returns `None` when Schwab delta is missing, while volume-only call/put flow remains available when Schwab totalVolume is present.
