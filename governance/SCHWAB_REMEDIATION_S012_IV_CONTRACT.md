> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S012_IV_CONTRACT.md`.

# Schwab Remediation S012 — chain `volatility` contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slice:** S012 `DEFAULT_ZERO_OR` x `iv`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): chains.callExpDateMap.*.volatility; chains.putExpDateMap.*.volatility; chains.volatility
Derived-field disposition: GATE_FAIL_CLOSED
All consumers checked: yes
```

## Contract

Per `schwab_field_dictionary.csv`, the option-chain implied-vol primitive is the **`volatility`** leaf (`chains.callExpDateMap.*.volatility` / `chains.putExpDateMap.*.volatility`). Runtime expected-move, charm, and Monte Carlo paths must not fabricate a numeric substitute when Schwab **`volatility`** is missing.

Missing **`volatility`** must leave **`volatility`**-dependent outputs unavailable or blocked. In particular, no path may default to 20% **`volatility`** for production calculations.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `math_exposure_core.compute_net_charm` | fixed-in-this-slice | `math_exposure_core.py::compute_net_charm` | Contracts missing Schwab `volatility` are skipped; no synthetic 20% **`volatility`**. |
| `server._fetch_state` **`volatility`**-based expected move fallback | fixed-in-this-slice | `server.py::_fetch_state` expected-move block | Fallback EM still uses `_atm_iv`; no 20% substitute when `_atm_iv` is missing. |
| `server._fetch_state` `SignalInput.iv_level` | fixed-in-this-slice | `server.py::_fetch_state` SignalInput construction | Missing ATM **`volatility`** remains `None` instead of `0`. |
| `signals._run_model_stack` Monte Carlo `iv` argument | fixed-in-this-slice | `signals.py::_run_model_stack` Monte Carlo call | Passes `iv` through as `None` when missing; no `0.20` fallback. |
| `math_volatility.compute_expected_move_iv` | already-canonical | `math_volatility.py::compute_expected_move_iv` | Already returns unavailable output when spot or **`volatility`** is missing/non-positive. |
| `math_volatility._extract_iv_for_strike` | already-canonical | `math_volatility.py::_extract_iv_for_strike` | Reads chain `volatility` and skips missing sentinel values. |
| `market_state` **`volatility`** level propagation | already-canonical | `market_state.py::build_market_state` **`volatility`** fields | Uses totals ATM **`volatility`** as optional; no synthetic **`volatility`** construction. |
| `monte_carlo.simulate` | already-canonical | `monte_carlo.py::simulate` | Returns unavailable for invalid **`volatility`**; S012 removed caller fallback that bypassed this gate. |
| `mc_fusion_adjustment.normalize_mc` volatility output | not-applicable | `mc_fusion_adjustment.py::normalize_mc` | Normalizes Monte Carlo model output volatility, not Schwab chain **`volatility`** input. |
| `math_probabilities.compute_vol_expansion_signal` | not-applicable | `math_probabilities.py::compute_vol_expansion_signal` | Combines already-derived **`volatility`**-change component; no chain **`volatility`** source substitution. |
| Test fixtures using `volatility: 20.0` | not-applicable | `tests/test_open_interest_contract.py`; `tests/test_multiplier_no_default.py` | Positive Schwab **`volatility`** fixture values, not missing-**`volatility`** defaults. |

No `pending-follow-up` rows remain for S012.

## Verification

```text
python -m pytest tests/test_open_interest_contract.py tests/test_server_iv_fail_closed.py tests/test_spot_fail_closed_contract.py
```

Expected: missing Schwab **`volatility`** skips/blocks **`volatility`**-dependent paths and no runtime path injects synthetic 20% **`volatility`**.
