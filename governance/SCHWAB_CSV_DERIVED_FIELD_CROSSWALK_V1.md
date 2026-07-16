> **Classification:** Policy Specification | **Scope:** Governance documentation `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_V1.md`.

# Schwab CSV Derived Field Crosswalk V1

**Status:** CSV-authoritative inventory synthesized - remediation OPEN  
**Date:** 2026-05-07  
**Schwab authority:** `schwab_field_inventory/schwab_field_dictionary.csv`  
**Canonical Schwab field count:** 2,393  
**Mechanical seed:** `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv`
**Classified output:** `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_CLASSIFIED.csv`  
**Disposition output:** `governance/SCHWAB_CSV_DERIVED_FIELD_DISPOSITION_REGISTER.csv`  
**Residual output:** `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv`
**Remediation roadmap:** retired under the ED CONSOLE SLIMMING directive; this file's live value is the field crosswalk below (read by the v2_decision A2 modules).

This document answers the repo-wide question:

```text
For every derived/defaulted/recomputed market-data field we found, does the Schwab CSV contain a native field that should be used instead?
```

The source of truth for Schwab availability is the tracked CSV file, not memory, prior assumptions, or the existing register.

---

## Precedence Principle (binding for every row in this crosswalk)

For any value where this CSV (`schwab_field_inventory/schwab_field_dictionary.csv`) contains a `canonical_field`:

```text
Schwab canonical_field = primary read.
App-side aliases (ms_dict keys, internal names, alternate keys) = legacy
fallbacks ONLY when the Schwab field is absent.
```

The `v1_approximation`, `not_implemented`, and `policy_object_pending` source labels do **not** apply to values whose source traces to a Schwab `canonical_field`. Such leaves must be labeled `v2_compliant` and cite the Schwab leaf in the `detail` field.

Disposition language for every `REPLACE_WITH_SCHWAB` row in this document follows the same pattern: *"Schwab `<canonical_field>` is the primary source; app-side aliases are legacy fallbacks only when the Schwab field is absent."* No row may use "fallback to Schwab," "add Schwab as a final fallback," or any wording that inverts precedence.

CI gate enforcing this principle for the A2 output surface: `tests/test_v2_a2_option_expression.py::test_a2_no_v1_approximation_leaf_traces_to_a_schwab_canonical_field`.

---

## Method

1. Loaded `schwab_field_inventory/schwab_field_dictionary.csv` and indexed `canonical_field` leaves.
2. Ran a mechanical repo scan for defaulting, zero-fill, `bid/ask` math, time fallbacks, DTE/date logic, Black-Scholes, and market-data field names.
3. Preserved the raw mechanical candidate output in `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv`.
4. Ran four scoped read-only CSV-backed audits:
   - price/quote/runtime paths;
   - options/math/A2 paths;
   - ML/training/calibration paths;
   - UI/API/payload paths.
5. Synthesized findings into action classes:
   - `REPLACE_WITH_SCHWAB`
   - `KEEP_DERIVED_WITH_PROVENANCE`
   - `GATE_FAIL_CLOSED`
   - `REDESIGN`

The mechanical scan produced 21,973 candidate rows. That file is intentionally over-inclusive and includes non-market defaults, tests, audit scripts, and governance code. The tables below are the curated market-data crosswalk.

Classification pass:

```text
input_rows = 21973
CSV_FIELD_REFERENCE_REVIEW = 5
CSV_PRIMITIVE_CANONICAL_REVIEW = 554
CSV_PRIMITIVE_RISK_REVIEW = 41
DEFAULT_OR_DERIVATION_REVIEW = 432
DERIVED_WITH_PROVENANCE_REVIEW = 9
NOT_MARKET_DATA = 1948
NOT_MARKET_RUNTIME = 18841
REVIEW_NONREGISTERED_RUNTIME = 92
TIME_AUTHORITY_REVIEW = 0
TRUE_ANALYTIC_REVIEW = 51
DISPOSITION_CANONICAL_OR_PASS_THROUGH_REVIEWED = 554
DISPOSITION_GATE_FAIL_CLOSED_OR_PROVENANCE = 0
DISPOSITION_KEEP_DERIVED_WITH_PROVENANCE = 60
DISPOSITION_NON_PRIMITIVE_DEFAULT_REVIEWED = 432
DISPOSITION_NOT_MARKET_DATA = 20789
DISPOSITION_OFFLINE_TOOL_OR_MODEL_REVIEWED = 92
DISPOSITION_REFERENCE_ONLY_REVIEWED = 5
DISPOSITION_REPLACE_WITH_SCHWAB_OR_GATE = 41
DISPOSITION_REPLACE_WITH_SCHWAB_OR_SPLIT_CLOCKS = 0
manual_residual_rows = 50
```

The disposition register assigns an automated first-pass disposition to every mechanical candidate row. The residual file is the remaining human-review queue. This document is evidence, not final proof, until `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv` is dispositioned to zero or each remaining row is explicitly registered/governed.

**Status vocabulary:** GOVERNANCE vs SYSTEM axes — canonical definitions: the gatekeeping policy (now in AGENTS.md) § Status Language; do not read this document’s **remediation OPEN** header as SYSTEM PASS.

The Schwab remediation program was retired under the ED CONSOLE SLIMMING directive.

---

## Direct Schwab Replacement Candidates

These sites derive/default a primitive that the CSV says Schwab provides.

| ID | Site | Current behavior | Schwab CSV field(s) | Action | Severity |
|---|---|---|---|---|---|
| CSV-R1 | `market_context.py::_extract_quote()` | `% change` fallback from `netChange / (last - netChange)` | `quotes.quote.netPercentChange`, `quotes.quote.netChange` | `REPLACE_WITH_SCHWAB`: `quotes.quote.netPercentChange` is the Schwab-primary source; derive `netChange / (last - netChange)` only when the Schwab field is absent and label the result as a derived fallback. | Medium |
| CSV-R2 | `market_state.py` DTE / `dte_style` paths | Calendar/string DTE computation | `chains.callExpDateMap.*.daysToExpiration`, `chains.putExpDateMap.*.daysToExpiration` | `REPLACE_WITH_SCHWAB`: `chains.*.daysToExpiration` is the Schwab-primary source; calendar/string DTE computation is a legacy app-side fallback only when Schwab `daysToExpiration` is absent. | High |
| CSV-R3 | `market_state.py::_oe_chain_row_snapshot()` | Proof row omits `daysToExpiration` | `chains.*.daysToExpiration` | `REPLACE_WITH_SCHWAB`: preserve Schwab `chains.*.daysToExpiration` in the proof row as the Schwab-primary source for downstream A2/lifecycle consumers. | High |
| CSV-R4 | `v2_decision/a2_option_expression.py` mid/premium paths | `mid = (bid + ask) / 2` | `chains.*.mark`, plus `bid`/`ask` when mark unavailable under policy | `REPLACE_WITH_SCHWAB` / `REDESIGN` price precedence: Schwab `chains.*.mark` is the primary source; Schwab `chains.*.last` is the next Schwab fallback; the derived `(bid+ask)/2` mid is an app-side fallback only when neither Schwab field is present. | High |
| CSV-R5 | `math_levels.py::parity_f_minus_spot_from_contracts()` | Accepts non-CSV synthetic `mid` key | `chains.*.mark`, `chains.*.last`, `chains.*.bid`, `chains.*.ask` | `REPLACE_WITH_SCHWAB`: Schwab `chains.*.mark` / `last` / `bid` / `ask` are the primary sources; the synthetic `mid` key is a legacy app-side fallback only when no Schwab price leaf is present. | Medium |
| CSV-R6 | `v2_decision/a2_option_expression.py::_theta()` | Black-Scholes residual when theta absent | `chains.*.theta` | `GATE_FAIL_CLOSED` or narrow residual fallback after post-fix measurement | High |
| CSV-R7 | `server.py` MC expected-move fallback | synthetic **`volatility`** = `20%`, fallback hours = `6.5` | `chains.*.volatility` for **`volatility`** input; time must be explicitly governed | `GATE_FAIL_CLOSED` / `REDESIGN` | Medium/High |
| CSV-R8 | `v2_decision/a2_lifecycle_health.py::resolve_a2_option_right()` | App-side right inference from side/proof | `chains.*.putCall` | `REPLACE_WITH_SCHWAB`: `winner.chain_row.putCall` is the Schwab-primary source; app-side aliases (`call_option_right`, `rec_side`, `winner.side`) are legacy fallbacks only when `chain_row.putCall` is absent. | Medium |
| CSV-R9 | Inline `chain_row.get("multiplier")` reads at consumer sites (formerly `chains.py::contract_fields()` — removed in the Schwab-direct redesign) | Missing multiplier became `100` in multiple paths | `chains.*.multiplier` | `REPLACE_WITH_SCHWAB`: Schwab `chains.*.multiplier` is the primary source; the literal `100` default is not a Schwab fallback — fail closed when the Schwab field is absent. | High |
| CSV-R10 | `realized_contract_eval.py` | `OPTION_MULTIPLIER = 100` for replay PnL | `chains.*.multiplier` | `REPLACE_WITH_SCHWAB`: Schwab `chains.*.multiplier` is the primary source for replay PnL; the literal `100` constant is not a Schwab fallback. | Critical |
| CSV-R11 | Inline equity-quote reads in `server.py` (formerly `chains.py::parse_quote_payload()` — removed in the Schwab-direct redesign) | Historically read only `quotes.quote.*` subtree | `quotes.regular.*`, `quotes.extended.*` where CSV provides session fields | `REDESIGN` quote merge policy: Schwab `quotes.quote.*` is the primary subtree; `quotes.regular.*` and `quotes.extended.*` are governed Schwab session fallbacks for fields the primary subtree omits. App-side aliases are legacy fallbacks only when no Schwab subtree carries the field. | High |
| CSV-R12 | `features/inference_snapshot.py` / `calibration/writer.py` time fallback | `time.time()` / wall clock fallback | `quotes.quote.quoteTime`, `quotes.quote.tradeTime`, streaming time fields | `REPLACE_WITH_SCHWAB` for data time: Schwab `quoteTime`/`tradeTime`/streaming time fields are the primary source; wall-clock `time.time()` is not a Schwab fallback. Label the decision clock separately from the data clock. | Medium |
| CSV-R13 | `order_flow_live_state.py` / utility change fields | Uses stream percent and sometimes non-CSV alias | `streaming.content.*.REGULAR_MARKET_CHANGE_PERCENT`, `quotes.quote.netChange`, `quotes.quote.netPercentChange` | `REPLACE_WITH_SCHWAB`: Schwab streaming `REGULAR_MARKET_CHANGE_PERCENT` and quote `netChange`/`netPercentChange` are the primary sources; non-CSV aliases are legacy fallbacks only when Schwab fields are absent. Reconcile field names against the CSV. | Medium |

---

## Gate / Fail-Closed Findings

These are not always direct replacements, but the current code can silently substitute a market-data primitive or market-data-derived feature.

| ID | Site | Current behavior | CSV relationship | Action | Severity |
|---|---|---|---|---|---|
| CSV-G1 | `server.py::_fetch_state()` | `spot = parsed.last or parsed.mark or 0.0` | `quotes.quote.lastPrice`, `quotes.quote.mark` | `GATE_FAIL_CLOSED` | High |
| CSV-G2 | `server.py::_fetch_state()` | cached spread carry-forward | `quotes.quote.bidPrice`, `quotes.quote.askPrice` | `GATE_FAIL_CLOSED` with age/source | High |
| CSV-G3 | `server.py::_tier_a_live_state_dict()` / overlays | `spread` key mixes dollars vs fraction across consumers | spread is derived from Schwab bid/ask; no native spread key | `REDESIGN` units: `spread_pts` vs `spread_frac` | High |
| CSV-G4 | `market_data_adapter.py` | OHLCV missing/unparseable -> `0.0` | `pricehistory.candles.*` | `GATE_FAIL_CLOSED` on Schwab path | High |
| CSV-G5 | `snapshot_normalizer.py::resample_to_1m()` | synthetic OHLCV from snapshots/spot | `pricehistory.candles.*` exists | `REDESIGN`; label synthetic vs Schwab bars | Medium/High |
| CSV-G6 | `liquidity_value_engine.py` | OHLCV defaults to `0` | `pricehistory.candles.*` | `GATE_FAIL_CLOSED` | High |
| CSV-G7 | `features/replay_signal_input_v1.py` | missing spot became `0.0` | spot sourced from Schwab quote/mark upstream | `GATE_FAIL_CLOSED`; fixed in current working tree | High |
| CSV-G8 | `features/fusion_model_input.py` | missing `vwap_side` -> `above`; zone -> `unknown` | no Schwab equivalent; synthetic category | `GATE_FAIL_CLOSED` or explicit NULL semantics | High |
| CSV-G9 | `lstm_data.py` / `features/lstm_sequence_input.py` | missing numerics -> `0.0`; zone/vwap-side defaults | mixed primitives and internal fields | `REDESIGN` missingness masks / fail closed | High |
| CSV-G10 | `ml_train.py` / `ml_predict.py` | median/zero imputation and `nan_to_num` hide upstream failures | mixed Schwab inputs | `REDESIGN` imputation provenance and hard caps | High |
| CSV-G11 | `signals.py::_spot_for_mc_fusion_adjustment()` | missing spot -> `0.0` | spot has Schwab upstream authority | `GATE_FAIL_CLOSED` | High |
| CSV-G12 | `signals.py::_run_model_stack()` | uniform priors / minimal overlays under failure | no Schwab equivalent; model degradation | `GATE_FAIL_CLOSED` / declared degraded mode | Critical |
| CSV-G13 | `mc_fusion_adjustment.py` | MC output zero-fill | no Schwab equivalent | `KEEP_DERIVED_WITH_PROVENANCE` or gate when trade-impacting | Medium |
| CSV-G14 | `order_flow_engine.py::_compute_rvol()` | returns `1.0` when baseline invalid | no Schwab RVOL primitive | `GATE_FAIL_CLOSED` / provenance | Medium |
| CSV-G15 | `static/index.html` | sticky bid/ask/VIX/PCR display | UI consumes Schwab-derived payload fields | `GATE_FAIL_CLOSED` display reset | High |

---

## True Analytics / No Schwab Equivalent

These should not be replaced by Schwab fields because the CSV has no equivalent analytic. They still require provenance/source labeling.

| Analytic family | Representative sites | Schwab CSV relationship | Required action |
|---|---|---|---|
| GEX / DEX / vanna / charm aggregates | `math_exposure_core.py`, `math_levels.py`, `math_volatility.py` | Schwab provides primitives (`delta`, `gamma`, `vega`, `volatility`, `openInterest`, `multiplier`), not aggregates | `KEEP_DERIVED_WITH_PROVENANCE` and input completeness |
| Gamma walls, delta walls, pin rails, void zones | `math_levels.py`, `market_state.py` | no Schwab equivalent | `KEEP_DERIVED_WITH_PROVENANCE` |
| Option expression score / liquidity gate / A2 policy | `math_probabilities.py`, `market_state.py`, `v2_decision/a2_option_expression.py` | Schwab provides inputs, not strategy policy result | `KEEP_DERIVED_WITH_PROVENANCE` |
| Breakeven | `market_state.py`, `v2_decision/a2_option_expression.py` | Schwab provides strike and price inputs, not app breakeven | `KEEP_DERIVED_WITH_PROVENANCE`; use `mark`/bid/ask precedence |
| VWAP, VWAP side, distance to VWAP | `market_context.py`, `planes/context_light.py`, `math_snapshot_derive.py`, `features/inference_snapshot.py` | CSV has no VWAP field | `KEEP_DERIVED_WITH_PROVENANCE`; define one VWAP authority |
| PCR / PCR arrows | `market_context.py`, `server.py`, UI | no single Schwab PCR scalar; derived from option OI | `KEEP_DERIVED_WITH_PROVENANCE` |
| VIX direction / VIX vs previous refresh | `server.py`, `static/index.html` | VIX level is Schwab quote; direction/change vs prior UI refresh is derived | `KEEP_DERIVED_WITH_PROVENANCE`; fix enum/payload contract |
| Streaming source badges / freshness / staleness | `order_flow_streaming.py`, `static/index.html`, `server.py` | no Schwab equivalent; transport health | `KEEP_DERIVED_WITH_PROVENANCE` |
| Replay PnL and realized labels | `realized_contract_eval.py`, `v2_decision/a2_replay_labels.py` | Schwab provides prices; app defines fill/exit policy | `KEEP_DERIVED_WITH_PROVENANCE`; use Schwab multiplier |
| ML predictions / calibration / fusion / MC | `ml_*`, `features/`, `signals.py`, `mc_fusion_adjustment.py` | no Schwab equivalent | `KEEP_DERIVED_WITH_PROVENANCE`; no silent degradation |

---

## New Findings Added By CSV Crosswalk

These were either missing from the prior register or need explicit register IDs.

| New ID | Site | Finding | Action | Severity |
|---|---|---|---|---|
| CSV-N1 | `math_exposure_core.py`, `backfill_flow_imbalance.py` and other inline `chain_row.get("multiplier")` consumers (formerly also `chains.py` — removed in the Schwab-direct redesign) | multiplier default/cross-consumer inconsistency | `REPLACE_WITH_SCHWAB` / fail closed | High |
| CSV-N2 | `realized_contract_eval.py` | hard-coded replay `OPTION_MULTIPLIER = 100` | `REPLACE_WITH_SCHWAB` | Critical |
| CSV-N3 | `debug_flow_snapshot.py` | multiplier extractor reads `ct.get("multiplier")` directly with no `100` coercion at the extractor; downstream `math_exposure_core.compute_exposures_by_strike` skips contracts with missing multiplier (does not coerce `100`). Disposition: NO_REMEDIATION_NEEDED at the extractor; retain row as historical reference until the row is formally retired. | None — current code is fail-closed per `math_exposure_core.compute_exposures_by_strike` | Resolved |
| CSV-N5 | `server.py::_tier_a_live_state_dict()` | `spread` unit mismatch with plane/Tier C | `REDESIGN` | High |
| CSV-N6 | `live_market_plane.merge_into_state()` / `apply_l1_live_quote_overlay()` | can overlay fraction `spread` onto dicts expecting dollar spread | `REDESIGN` / `GATE_FAIL_CLOSED` | High |
| CSV-N7 | `server.py` / `static/index.html` | VIX direction enum mismatch and payload omission | `REDESIGN` | High |
| CSV-N8 | `features/inference_snapshot.py` | VWAP distance sign can be double-applied | `REDESIGN` | Medium |
| CSV-N9 | `signals.py::_run_model_stack()` | uniform priors and minimal overlays can bypass real feature truth | `GATE_FAIL_CLOSED` | Critical |
| CSV-N10 | `calibration/writer.py` | default decision timestamp uses wall clock | `REPLACE_WITH_SCHWAB` data timestamp where appropriate | Medium |
| CSV-N11 | `math_exposure_core.py::compute_net_charm()` | **`volatility`** `20%` and multiplier `100` defaults | `GATE_FAIL_CLOSED` | High |
| CSV-N12 | `v2_decision/a2_option_expression.py::_dte_value()` | parses DTE from UI text | `REPLACE_WITH_SCHWAB` / `REDESIGN` | High |
| CSV-N13 | `market_state.py::_oe_chain_row_snapshot()` | Proof-row path: `daysToExpiration` is now preserved (`market_state._oe_chain_row_snapshot` includes the canonical `daysToExpiration` key per `governance/A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`). Disposition: RESOLVED for the proof-row path. Any non-proof-row consumers still parsing DTE from text fall under CSV-N12 above. | Resolved (proof-row); see CSV-N12 for any residual text-parse consumers | Resolved |
| CSV-N14 | `static/index.html` utility bar | point change derived from stream percent times merged spot | `KEEP_DERIVED_WITH_PROVENANCE` or align to `quotes.quote.netChange` | Medium |

---

## Working-Tree Remediation State

Already fixed or partially fixed in the current uncommitted working tree:

| Finding | Working tree status |
|---|---|
| DFR-002 / PQ-004 | live plane no longer carries prior spot/bid/ask or fabricates midpoint spot. |
| DFR-003 / PQ-001 / PQ-002 | REST fast quote no longer uses `spot=0.0`; emits quote source metadata and `spread_pts`. |
| DFR-004 / PQ-003 | cached spread is labeled `cached_last_valid_not_tradeable` and not used as current `MarketState.spread`. |
| DFR-010 / MT-001 | replay signal spot fails closed instead of missing -> `0.0`. |
| CSV-N1 / R9 | Inline `chain_row.get("multiplier")` consumers in `backfill_flow_imbalance.py` and `math_exposure_core.py` stop defaulting missing multiplier to `100` (the historical `chains.py` consumer site was removed in the Schwab-direct redesign). |

Not fixed by current working tree:

```text
realized_contract_eval.py OPTION_MULTIPLIER = 100
spread unit split across Tier A / plane / Tier C / UI
VIX direction payload and enum contract
A2 DTE text parsing (`v2_decision/a2_option_expression.py::_dte_value()`)
market_data_adapter OHLCV zero injection
snapshot_normalizer synthetic OHLCV provenance
ML/LSTM/XGB zero/imputation semantics
signals/model-stack degraded-mode behavior
```

Resolved (no longer in the not-fixed list):

```text
debug_flow_snapshot.py multiplier default — extractor reads `ct.get("multiplier")` directly with no `100` coercion; `math_exposure_core.compute_exposures_by_strike` skips contracts with missing multiplier (fail-closed)
parse_quote_payload regular/extended subtree policy — `chains.py::parse_quote_payload` removed in the Schwab-direct redesign; equity-quote reads in `server.py` are inline against Schwab `quotes.quote.*` / `quotes.regular.*` / `quotes.extended.*` per CSV-R11
daysToExpiration preservation — proof-row path preserves `daysToExpiration` per `governance/A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md` (CSV-N13 / CSV-R3)
```

---

## Next Remediation Order

1. **Split and govern spread units**: `spread_frac` vs `spread_pts`/`spread_dollars`; update plane, Tier A, Tier C, UI, A2 consumers.
2. **Complete multiplier remediation**: add `realized_contract_eval.py` to the N1/R9 slice before claiming closure (`debug_flow_snapshot.py` extractor is already fail-closed via `math_exposure_core.compute_exposures_by_strike`).
3. **A2 DTE authority**: replace remaining UI-text DTE parsing in `v2_decision/a2_option_expression.py::_dte_value()`; proof-row `daysToExpiration` preservation is already landed.
4. **Quote parsing authority**: keep equity-quote reads inline against Schwab `quotes.quote.*` / `quotes.regular.*` / `quotes.extended.*` per CSV-R11; do not reintroduce a `parse_quote_payload`-style helper.
5. **OHLCV zero injection**: reject or source-label incomplete Schwab bars and synthetic snapshot bars.
6. **VIX/UI source contract**: serialize VIX direction/change consistently and align enum names.
7. **Model/training missingness**: replace silent zero/median laundering with provenance, missing masks, or fail-closed rules.

---

## Non-Closure Statement

```text
csv_authority_crosswalk_status = SYNTHESIZED
mechanical_candidate_classification_status = FIRST_PASS_COMPLETE
full_disposition_register_status = GENERATED
manual_residual_rows_requiring_disposition = 50
runtime_remediation_status = OPEN
all_consumer_closure_status = OPEN
```

This document is the CSV-backed crosswalk baseline. It does not claim remediation closure.
