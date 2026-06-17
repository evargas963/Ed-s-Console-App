# Schwab Field Coverage Register V1

**Status:** Active coverage control - implementation closure OPEN  
**Date:** 2026-05-07  
**Scope:** Field-first consumer disposition for Schwab-native primitives and derived fallbacks

This register complements `SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`. The derived-field register is site-first. This file is field-first: when a remediation slice touches a market-data primitive, every known consumer must be dispositioned as canonical, fixed in the slice, explicitly deferred with reason, or not applicable.

No slice may claim field closure while a known consumer silently substitutes, defaults, or carries forward the same field.

---

## Required Slice Discipline

Every field remediation commit must include an all-consumers disposition:

```text
Field: <fieldname>
Consumers:
  path/file.py  STATUS  register_ref  note
```

Allowed statuses:

| Status | Meaning |
|---|---|
| `canonical` | Already consumes Schwab-native/normalized field without silent substitution. |
| `fixed-in-this-slice` | Changed by the current slice. |
| `derived-with-provenance` | Field is intentionally derived and emits source/age/provenance. |
| `pending-follow-up` | Known temporary inconsistency with register reference and follow-up slice. |
| `not-applicable` | Not a Schwab-native primitive consumer or only uses test/static fixture data. |

`pending-follow-up` is not closure.

---

## Field Coverage Snapshot

Field-first reverse audit summary:

```text
CANONICAL                       78 sites
DERIVED_WITH_PROVENANCE          8 sites
SILENT_SUBSTITUTION              5 sites
DEFAULTS_ON_ABSENCE              4 sites
```

Every problem site from the field-first pass maps to an existing finding in `SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`; no new problem finding was introduced by this register.

---

## Multi-Consumer Hotspots

| Field / primitive | Register refs | Current disposition | Closure status |
|---|---|---|---|
| `spot` / underlying price | DFR-002, DFR-003, MT-001 | Producer paths and replay consumer fixed in current Remediation #2 working tree; commit pending. | OPEN |
| option multiplier | DFR-017 | Normalization, archive backfill normalization, and exposure consumer fixed in current working tree; commit pending. | OPEN |
| OHLCV bars | DFR-009, DFR-011, MT-006, MT-007, DFR-018 | Zero injection and synthetic-bar labeling remain pending. | OPEN |
| size / open interest | OP-003, OP-017 | Default semantics remain mixed across exposure/probability/order-flow consumers. | OPEN |
| option expiry identity | DFR-005, OP-018, OP-019 | Full-chain fallback and replay identity fallback remain pending. | OPEN |

---

## Current Slice Consumer Disposition

### Field: `spot`, `bid`, `ask`, `spread`

| Consumer | Status | Register refs | Note |
|---|---|---|---|
| `live_market_plane.py::record_from_level_one_equity()` | fixed-in-this-slice | DFR-002, PQ-004, PQ-005 | Uses Schwab `LAST_PRICE` then `MARK` for spot; stops prior spot/bid/ask carry-forward and midpoint spot fabrication; emits `quote_source_detail`. |
| `server.py::_build_rest_fast_quote_payload()` | fixed-in-this-slice | DFR-003, PQ-001, PQ-002 | Uses Schwab `lastPrice` then `mark`; emits source metadata and `spread_pts`; no `spot=0.0` silent fallback. |
| `server.py::_tier_a_live_state_dict()` | fixed-in-this-slice | DFR-003, PQ-001, PQ-002 | REST bootstrap emits the same source metadata and spread provenance as fast quote. |
| `server.py::_fetch_state()` | fixed-in-this-slice | DFR-004, PQ-003 | Cached spread is labeled `cached_last_valid_not_tradeable` and not passed into `MarketState.spread` as current quote spread. |
| `features/replay_signal_input_v1.py::signal_input_from_snapshot_row_dict()` | fixed-in-this-slice | MT-001 | Missing, blank, non-numeric, zero, or negative spot fails closed instead of becoming `0.0`. |

### Field: option `multiplier`

| Consumer | Status | Register refs | Note |
|---|---|---|---|
| Inline `chain_row.get("multiplier")` reads at consumer sites (formerly `chains.py::contract_fields()` — removed in the Schwab-direct redesign) | fixed-in-this-slice | DFR-017 / N1 / R9 | Schwab-native `multiplier` is preserved at each consumer; missing, blank, invalid, zero, or negative multiplier becomes unavailable instead of default `100`. |
| `backfill_flow_imbalance.py::_contracts_from_chain_json()` | fixed-in-this-slice | DFR-017 / N1 / R9 | Archive/backfill normalizer follows the same no-default rule as the inline `chain_row` consumers. |
| `math_exposure_core.py::compute_exposures_by_strike()` | fixed-in-this-slice | DFR-017 / N1 / R9 | Dollarized exposure math skips contracts with missing/non-positive multiplier instead of treating them as standard `100` multiplier contracts. |
| `server.py::_fetch_state()` exposure path | fixed-in-this-slice | DFR-017 / N1 / R9 | Consumes `compute_exposures_by_strike()` result; inherits fail-closed multiplier behavior for live exposure surfaces. |
| `db_health_audit.py`, `debug_flow_snapshot.py`, `backfill_flow_imbalance.py` exposure callers | fixed-in-this-slice | DFR-017 / N1 / R9 | Consume the shared exposure engine; no separate multiplier default remains in these paths except the fixed backfill normalizer. |

---

## Non-Closure Statement

```text
field_coverage_register_status = OPEN
current_slice_spot_consumer_disposition = DRAFTED
repo_wide_field_remediation_status = OPEN
```
