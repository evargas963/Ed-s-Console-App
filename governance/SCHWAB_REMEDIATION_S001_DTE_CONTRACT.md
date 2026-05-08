# Schwab Remediation S001 DTE Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slice:** S001 `DATE_DIFF_DTE` x `days_to_expiration`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.daysToExpiration; chains.putExpDateMap.*.daysToExpiration
Derived-field disposition: REPLACE_WITH_SCHWAB
All consumers checked: yes
```

## Contract

Runtime 0DTE/DTE decisions must use Schwab-native option-chain `daysToExpiration` from the selected contract row. Calendar subtraction, UI text parsing, or missing-field coercion may not certify a contract as 0DTE.

If `daysToExpiration` is absent where a DTE-gated runtime decision is required, the consumer must fail closed by omitting the DTE label, skipping the contract for DTE-filtered analytics, or emitting the existing A2 WAIT gate.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|
| `market_state._oe_chain_row_snapshot` | fixed-in-this-slice | `market_state.py::_oe_chain_row_snapshot` | Preserves Schwab `daysToExpiration` into A2 proof rows. |
| `market_state._build_contract_context_ms` | fixed-in-this-slice | `market_state.py::_build_contract_context_ms` | Contract context DTE label reads selected contract `daysToExpiration`; no calendar-date subtraction. |
| `market_state.build_market_state` | fixed-in-this-slice | `market_state.py::build_market_state` | DTE warning style is set after selected Schwab contract is known. |
| `server._selected_schwab_days_to_expiration` / DB snapshot writer | fixed-in-this-slice | `server.py::_selected_schwab_days_to_expiration`; `server.py` DB snapshot block | Persisted snapshot `dte` now reads Schwab `daysToExpiration`; missing value writes `None`. |
| `server._snapshot_expiry_hours_from_schwab_dte` / DB snapshot writer | fixed-in-this-slice | `server.py::_snapshot_expiry_hours_from_schwab_dte`; `server.py` DB snapshot block | `hours_to_expiry` is derived only after Schwab DTE is present; missing DTE writes `None`. |
| `v2_decision.a2_option_expression.build_a2_option_expression` | fixed-in-this-slice | `v2_decision/a2_option_expression.py::build_a2_option_expression` | A2 identity `dte` is sourced/labeled from Schwab `daysToExpiration`. |
| `v2_decision.a2_option_expression._hard_gates` | fixed-in-this-slice | `v2_decision/a2_option_expression.py::_hard_gates` | Strict 0DTE gate uses Schwab `daysToExpiration`; missing value does not pass. |
| `math_levels.parity_f_minus_spot_from_contracts` | fixed-in-this-slice | `math_levels.py::parity_f_minus_spot_from_contracts` | DTE filter no longer coerces missing `daysToExpiration` to `0`. |
| `math_exposure_core.compute_net_charm` | fixed-in-this-slice | `math_exposure_core.py::compute_net_charm` | DTE fallback filter no longer coerces missing `daysToExpiration` to `99`. |
| `chains.contract_fields` | canonical | `chains.py::contract_fields` | Passes through Schwab `daysToExpiration`; no derivation in this slice. |
| `backfill_flow_imbalance._contracts_from_chain_json` | canonical | `backfill_flow_imbalance.py::_contracts_from_chain_json` | Passes through archived Schwab `daysToExpiration`; no derivation in this slice. |
| `debug_flow_snapshot` | canonical | `debug_flow_snapshot.py` option snapshot row | Debug snapshot pass-through of Schwab `daysToExpiration`; not a runtime derivation. |
| `order_flow_engine._iter_option_exp_levels` | canonical | `order_flow_engine.py::_iter_option_exp_levels` | Converts Schwab `daysToExpiration` to int without deriving from dates. |
| `server._expiries_from_contracts` / chain filtering / debug endpoint | not-applicable | `server.py::_expiries_from_contracts`; `server.py` selected-exp filtering; `server.py` debug chain sample | Uses expiration identity or debug sampling, not DTE calculation. DB snapshot DTE is separately fixed above. |
| `live_vs_replay_validation._live_expiry_from_proof` | not-applicable | `live_vs_replay_validation.py::_live_expiry_from_proof` | Compares expiration identity, not DTE calculation. |
| `realized_contract_eval` | not-applicable | `realized_contract_eval.py` expiration matching | Uses expiration identity for replay contract matching, not DTE calculation. |
| `call_engine` comments and 0DTE prose | not-applicable | `call_engine.py` classifier-hit prose | Classifier hit is descriptive text, not market-data derivation. |

## Verification

```text
python -m pytest tests/test_v2_a2_option_expression.py tests/test_a2_market_state_proof_row_completeness.py tests/test_schwab_days_to_expiration_contract.py tests/test_server_schwab_dte_snapshot.py
```

Expected: targeted S001 tests pass, including fail-closed behavior when Schwab `daysToExpiration` is missing.
