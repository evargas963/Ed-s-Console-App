# Schwab Remediation S014/S015 Tape Size Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slices:** S014 `DEFAULT_ZERO_OR` aggregate; S015 `GET_DEFAULT_ZERO` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): streaming.content.*.LAST_SIZE; streaming.content.*.TICK_AMOUNT; streaming.content.*.LAST_PRICE; streaming.content.*.TRADE_TIME_MILLIS; streaming.content.*.TICK
Derived-field disposition: REPLACE_WITH_SCHWAB_OR_GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Tape-print size must come from Schwab streaming tape fields (`LAST_SIZE`, with `TICK_AMOUNT` only as a same-message Schwab fallback). Missing size is not zero size.

Consumers that aggregate tape prints must skip missing or non-positive size. They must not use `p.get("size") or 0` or equivalent silent zeroing to make missing tape size participate in pressure, delta, slope, absorption, or display calculations.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `order_flow_live_state.push_level_one` | fixed-in-this-slice | `order_flow_live_state.py::push_level_one` | Preserves missing Schwab `LAST_SIZE` as `None` before the engine consumes the live tape. |
| `order_flow_engine._iter_tape_prints` | fixed-in-this-slice | `order_flow_engine.py::_iter_tape_prints` | Preserves missing Schwab size as `None`; falls back only to same-message `TICK_AMOUNT`. |
| `order_flow_engine._compute_tape_pressure` | fixed-in-this-slice | `order_flow_engine.py::_compute_tape_pressure` | Skips missing/non-positive size; no zero participation. |
| `order_flow_engine._compute_cum_delta_proxy` | fixed-in-this-slice | `order_flow_engine.py::_compute_cum_delta_proxy` | Skips missing/non-positive size and returns `None` if no valid Schwab size contributes. |
| `order_flow_engine._compute_cum_delta_slope` | fixed-in-this-slice | `order_flow_engine.py::_compute_cum_delta_slope` | Skips missing/non-positive size before slope point creation. |
| `order_flow_engine._compute_absorption` | fixed-in-this-slice | `order_flow_engine.py::_compute_absorption` | Sums only present positive tape sizes. |

No `pending-follow-up` rows remain for this tape-size sub-slice.

## Verification

```text
python -m pytest tests/test_order_flow_live_state_tape_contract.py tests/test_order_flow_tape_contract.py tests/test_order_flow_volume_contract.py
```

Expected: missing tape size is preserved as `None`, skipped by consumers, and targeted residual search for tape-size zero defaults in `order_flow_engine.py` returns no matches.
