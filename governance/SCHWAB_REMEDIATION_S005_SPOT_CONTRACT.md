# Schwab Remediation S005 Spot Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slice:** S005 `DEFAULT_ZERO_OR` x `spot`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.quote.lastPrice; quotes.quote.mark; chains.underlying.last; chains.underlying.mark; chains.underlyingPrice
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Underlying spot is a Schwab-native market-data primitive. Runtime state, replay, model feature, MC adjustment, and trade-validation paths must not silently turn missing spot into `0`.

When no positive Schwab spot is available, consumers must return unavailable/skip/fail closed rather than compute derived percentages, distances, simulations, or validation decisions from synthetic zero.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `server._fetch_state` quote spot | fixed-in-this-slice | `server.py::_fetch_state` quote parse block | Uses positive `lastPrice`, else positive `mark`, else `None`; no `0.0` fallback. |
| `server._fetch_state` state computation | fixed-in-this-slice | `server.py::_fetch_state` exposure guard | Returns `missing_canonical_spot` before exposure and candle math when quote spot is unavailable. |
| `server` debug charm endpoint | fixed-in-this-slice | `server.py` chain `underlyingPrice` parse | Parses `underlyingPrice` as optional and returns an error on missing/invalid spot. |
| `features.replay_signal_input_v1.signal_input_from_snapshot_row_dict` | already-fixed | `features/replay_signal_input_v1.py::signal_input_from_snapshot_row_dict` | Replay requires positive snapshot `spot`; raises `ValueError` on missing/invalid. |
| `signals._spot_for_mc_fusion_adjustment` | fixed-in-this-slice | `signals.py::_spot_for_mc_fusion_adjustment` | Returns `None` when MC/fusion spot is missing instead of `0.0`. |
| `mc_fusion_adjustment.normalize_mc` | fixed-in-this-slice | `mc_fusion_adjustment.py::normalize_mc` | No longer scales expected move/volatility by synthetic spot `1.0`. |
| `lstm_data.compute_confluence_features` | fixed-in-this-slice | `lstm_data.py::compute_confluence_features` | Missing spot returns neutral/unavailable confluence features; group/trend spot comparisons skip missing endpoints. |
| `ml_train.engineer_single_snapshot` | fixed-in-this-slice | `ml_train.py::engineer_single_snapshot` | Missing or non-positive spot returns `None`; percentage features are not computed from zero. |
| `call_engine._validate_trade` | fixed-in-this-slice | `call_engine.py::_validate_trade` | Non-WAIT trade validation fails closed with `missing canonical spot`. |
| `verify_mc_directional._report_ticker` | fixed-in-this-slice | `verify_mc_directional.py::_report_ticker` | Verification helper no longer defaults display spot to `0`. |
| `live_market_plane.merge_into_state` | already-fixed | `live_market_plane.py::merge_into_state` | State merge fails when stream/quote spot is missing or non-positive. |
| `math_volatility` spot guards | not-applicable | `math_volatility.py` spot guard clauses | Existing fail-closed guards, not default-zero derivations. |
| `v2_decision.a2_option_expression._black_scholes_theta` | not-applicable | `v2_decision/a2_option_expression.py::_black_scholes_theta` | Existing invalid-input guard; BS fate is governed by S008, not S005. |
| Test guard fixtures | not-applicable | `tests/test_check_schwab_csv_first.py`; `tests/test_classify_schwab_csv_crosswalk.py` | Intentional risky-pattern fixtures for guard/classifier tests. |
| Static/example scripts | not-applicable | `print_liquidity_value_snapshot.py`; `compare_clustering_modes.py`; `reauth_schwab.py` | Text/examples or non-market-data operational helpers. |

No `pending-follow-up` rows remain for S005.

## Verification

```text
python -m pytest tests/test_spot_fail_closed_contract.py tests/test_mc_fusion_adjustment.py tests/test_replay_signal_input_v1.py tests/test_server_quote_source_contract.py tests/test_live_market_plane_streaming.py
```

Expected: focused spot tests pass and targeted residual search shows no remaining spot-to-zero runtime substitutions.
