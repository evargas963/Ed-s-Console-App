> **Classification:** Policy Specification | **Scope:** Governance policy/contract `PILOT_1B_A2_0DTE_CONTRACT.md`.

# Pilot 1B A2 0DTE Contract

**Status:** DRAFT implementation contract  
**Date:** 2026-05-05  
**Module:** A - short-horizon event-driven trading  
**Expression profile:** A2 - options / 0DTE  
**Initial tickers:** SPY / QQQ unless amended  
**Runtime plane:** Tier C only  
**Depends on:** `governance/IMPLEMENTATION_BLUEPRINT_V2.md`, `governance/PILOT_1A_BUILD_PLAN.md`, `governance/FRAMEWORK_V2_TARGET_LOCK_RECORD.md`

Pilot 1B promotes 0DTE from downstream option-expression scoring into an explicit v2 expression profile. This document is a contract-first artifact: it defines the required A2 shape before adapting existing option code.

It is not production authority and does not change locked v1.1 behavior.

Pilot 1B operates outside v1.1 prereg authority; it is governed by the v2.0 target lock and this contract until a v2.0 prereg is approved and content-hash-bound. Adding QQQ does not require a v1.1 prereg amendment because Pilot 1B does not consume v1.1 authority.

---

## Objective

A2 answers:

> Given a Module A short-horizon directional signal, is there a valid options / 0DTE expression that should be shown as a draft v2 advisory decision?

A2 is not just "A1 plus a call option." It has separate requirements for:

- option-chain identity and as-of discipline;
- strike / expiry / right selection;
- bid / ask / mid and liquidity quality;
- chain **`volatility`** / Greeks and expiration risk;
- contract-level payoff labels;
- spread and fill realism;
- lifecycle actions and forced-exit rules;
- replay/live parity;
- source-indicated v2 output fields.

---

## Non-Goals

Pilot 1B does not:

- train an options-native model yet;
- claim a validated A2 edge;
- promote artifacts;
- alter Module A/A1 authority;
- put option-chain work on Tier A, Tier B, or L1;
- make option output trade-impacting;
- hide missing A2 requirements behind generic confidence fields.
- cover multi-leg structures. Pilot 1B is single-leg directional CALL/PUT only. Verticals, butterflies, calendars, condors, iron condors, and other multi-leg structures require separate expression-profile contracts.

Early A2 output is a deterministic baseline only until labels, replay, provenance, execution, and lifecycle validation exist.

---

## A2 Output Contract

The A2 object should attach under the existing Tier C `v2_decision` object, not as top-level `MarketState` fields.

### Schwab canonical binding (normative for market-data leaves)

Authoritative leaf list: `schwab_field_inventory/schwab_field_dictionary.csv` (column `canonical_field`). For option contracts, chain rows normalize to **`chains.callExpDateMap.*.<leaf>`** or **`chains.putExpDateMap.*.<leaf>`** (same leaf names on both maps). Pilot 1B MUST use these wire names in code, proof rows, and serialization; aliases used only in UI copy must still resolve to these keys in logs and tests.

| A2 / adapter name (this contract) | Schwab canonical leaf (chain row) | Classification |
|---|---|---|
| `strike` | `strikePrice` | Wire |
| `contract_symbol` | `symbol` | Wire |
| `selected_expiry` (as calendar identity) | `expirationDate` | Wire |
| `dte` (when taken from chain) | `daysToExpiration` | Wire |
| `bid` / `ask` | `bid` / `ask` | Wire |
| `mid` | *(none)* | **Derived:** `(bid + ask) / 2` when both present; source label MUST NOT claim Schwab-native `mid` |
| `spread` (width) | *(none)* | **Derived:** `ask - bid` when both present; not a Schwab dictionary leaf |
| `iv` | `volatility` | Wire (Schwab uses `volatility`; do not emit or persist `iv` as the wire key) |
| `delta` / `gamma` / `theta` / `vega` / `rho` | same names | Wire |
| Theoretical model (wire) | `theoreticalVolatility`, `theoreticalOptionValue` | Wire |
| Volume / OI (soft gates, scoring) | `totalVolume`, `openInterest` | Wire (do not use non-canonical `volume`) |
| Quote / trade clock inputs | `quoteTimeInLong`, `tradeTimeInLong` | Wire |
| Mark / last | `mark`, `last` | Wire |
| `delta_gamma_ratio`, `gamma_x_oi`, `vol_oi_ratio` (A2 schema) | *(none as single leaf)* | **Derived** in `score_option_expression` from wires such as `delta`, `gamma`, `openInterest`, `volatility`, `totalVolume` |

Underlying **spot** for Black-Scholes fallback (when used) is NOT on the option chain row; use an equity quote canonical such as **`quotes.quote.lastPrice`** → **`quotes.extended.lastPrice`** → **`quotes.regular.regularMarketLastPrice`** ladder (see `server.py::_extract_quote` and `market_context.py::_extract_quote`). The lifecycle sidecar `derivation_inputs.spot` therefore carries `source: v2_compliant` with `detail: "quotes.quote.lastPrice"` (the upstream primary leaf). Likewise, `derivation_inputs.vix_level` is Schwab-direct from the `$VIX` quote payload (`detail: "quotes.$VIX.quote.lastPrice"`) and labeled `v2_compliant`.

Rows in the tables below that name **`mid`**, **`spread`**, **`iv`**, or policy-only objects remain valid as **A2 schema** names, but implementations MUST map population to the Schwab/derived classification above and label source accordingly (`v2_compliant` only for true wire reads, not for derived mids/spreads).

Required identity fields:

| Field | Required source behavior |
|---|---|
| `module_id` | `value: "A"`, `source: "v1_approximation"` until Module A validation is v2-bound |
| `expression_profile_id` | `value: "A2"`, `source: "v2_compliant"` once this contract is implemented as a shape |
| `instrument_family` | `value: "options_0dte"`, `source: "v2_compliant"` once this contract is implemented as a shape |
| `underlying_ticker` | `v2_compliant`; literal Schwab request parameter / `chains.symbol` (no derivation). `detail: "chains.symbol"`. |
| `selected_expiry` | `v2_compliant`; the chain-row `expirationDate` of the chosen contract is the **Schwab-primary source** (`detail: "schwab_chain_expirationDate"`). `ms_dict["call_option_expiry"]` / `ms_dict["selected_exp"]` are legacy app-side fallbacks only when no `chain_row` is present. |
| `dte` | `v2_compliant`; Schwab `chains.*.daysToExpiration` is the **Schwab-primary source** (`detail: "schwab_chain_daysToExpiration"`). When the Schwab field is absent the leaf falls back to `not_implemented`, never to a synthetic date diff. |
| `decision_plane` | `value: "Tier C"`, `source: "v2_compliant"` |
| `authority_mode` | `value: "advisory_non_authoritative"`, `source: "v2_compliant"` |

Required option expression fields:

| Field | Required source behavior |
|---|---|
| `option_action` | `TRADE`, `WAIT`, or `AVOID`; deterministic baseline can be `v1_approximation` |
| `option_right` | `CALL`, `PUT`, or `NONE`. Schwab `chain_row.putCall` is the **Schwab-primary source** and yields `v2_compliant` with `detail: "chains.*.putCall"`. App-side aliases (`ms.call_option_right`, `ms.rec_side`, `winner.side`) are legacy fallbacks only when `chain_row.putCall` is absent and yield `v1_approximation`. |
| `strike` | Schwab `chain_row.strikePrice` is the **Schwab-primary source** and yields `v2_compliant` with `detail: "schwab_chain_strikePrice"`. `winner.strike` (sourced from the chain row by `recommend_option_expression`) is treated as Schwab-direct. `ms.rec_strike` is a legacy app-side fallback only when no chain row is present and yields `v1_approximation`. |
| `contract_symbol` | `v2_compliant` when the selected chain row exposes Schwab **`symbol`** (`detail: "schwab_chain_symbol"`), else `not_implemented`. |
| `bid` / `ask` / `mid` | `bid`/`ask` from chain row are Schwab wires (`v2_compliant`, `detail: "schwab_chain_bid"` / `"schwab_chain_ask"`); `mid` is **derived** from `mark` -> `last` -> `(bid+ask)/2` and is `v1_approximation` (no Schwab single-leaf mid). |
| `spread` | deterministic baseline from `score_option_expression` (**derived** from bid/ask; not a Schwab leaf — stays `v1_approximation`) |
| `max_loss` | `policy_object_pending` until sizing and debit policy are bound |
| `breakeven` | deterministic baseline when **derived** mid (from **`bid`**/**`ask`**) is available; `v1_approximation` (no Schwab leaf for breakeven) |
| `selected_contract_snapshot` | the literal selected Schwab chain row passthrough — every field on it is a Schwab wire leaf. `v2_compliant`, `detail: "schwab_chain_row_snapshot"`. |
| `selection_proof` | deterministic baseline from `recommend_option_expression` proof; app-side selection record (`v1_approximation`, no Schwab equivalent) |

Required probability and expected-value fields:

| Field | Required source behavior |
|---|---|
| `P_underlying_entry_success` | `v1_approximation` from Module A/A1 stack probability |
| `P_contract_profit` | `not_implemented` until contract-level labels exist |
| `P_lifecycle_adjusted_profit` | `not_implemented` until lifecycle policy is validated |
| `p_low` / `p_high` | `not_implemented` until calibrated/conformal A2 bounds exist |
| `EV_contract_mid` | `not_implemented` until contract payoff labels exist |
| `EV_lower` / `EV_upper` | `not_implemented` until calibrated bounds and execution costs exist |
| `execution_adjusted_EV` | `not_implemented` until spread/fill/slippage model exists |

Required execution fields:

| Field | Required source behavior |
|---|---|
| `liquidity_gate_pass` | deterministic baseline from `score_option_expression.liq_gate` |
| `spread_quality` | deterministic baseline from spread and configured threshold |
| `fill_probability` | `not_implemented` |
| `slippage_estimate` | `not_implemented` |
| `adverse_selection_risk` | `not_implemented` |
| `quote_staleness_ms` | `not_implemented` unless **`quoteTimeInLong`** (chain wire) or governed quote clock is available; compute as delta vs adapter clock, not a Schwab leaf |
| `capacity_size_cap` | `policy_object_pending` |

Required **`volatility`** / Greeks fields:

| Field | Required source behavior |
|---|---|
| `delta` | Schwab `chains.*.delta` is the **Schwab-primary source**: `v2_compliant`, `detail: "schwab_chain_delta"` when present and not the `-999.0` sentinel; `not_implemented` otherwise. |
| `gamma` | Schwab `chains.*.gamma` is the **Schwab-primary source**: `v2_compliant`, `detail: "schwab_chain_gamma"` when present and not the `-999.0` sentinel; `not_implemented` otherwise. |
| `vega` | Schwab `chains.*.vega` is the **Schwab-primary source**: `v2_compliant`, `detail: "schwab_chain_vega"` when present and not the `-999.0` sentinel; `not_implemented` otherwise. |
| `theta` | hard input. Schwab `chains.*.theta` is the **Schwab-primary source** (`v2_compliant`, `detail: "schwab_chain_theta"`). When the Schwab field is absent or carries the `-999.0` sentinel, the Black-Scholes theta computed from underlying spot, strike, IV, and expiry is a governed `v1_approximation` fallback. A2 must emit `WAIT` if theta is unavailable. |
| `iv` | Schwab `chains.*.volatility` is the **Schwab-primary source** (`v2_compliant`, `detail: "schwab_chain_volatility"`); `chains.*.theoreticalVolatility` is a Schwab fallback (`v2_compliant`, `detail: "schwab_chain_theoreticalVolatility"`) when the primary field is absent or sentinel. Do not treat `iv` as a persisted Schwab key. |
| `delta_gamma_ratio` | derived `|delta|/|gamma|` from `score_option_expression`; no Schwab single-leaf ratio — `v1_approximation`. |
| `gamma_x_oi` | derived `gamma * openInterest` from `score_option_expression` (`detail: "derived_schwab_gamma_x_openInterest"`); no Schwab single-leaf product — `v1_approximation`. |
| `vol_oi_ratio` | derived `volume / openInterest` from `score_option_expression`; no Schwab single-leaf ratio — `v1_approximation`. |

Required lifecycle fields:

| Field | Required source behavior |
|---|---|
| `entry_policy` | deterministic baseline from replay context or current call plan |
| `stop_policy` | `v1_approximation` from current rules stop geometry |
| `target_policy` | `v1_approximation` from current rules target geometry |
| `timeout_policy` | `policy_object_pending` until A2 lifecycle policy is bound |
| `forced_exit_time` | `policy_object_pending` |
| `allowed_actions` | `policy_object_pending`: hold, exit, tighten, scale_out, convert, force_exit |
| `lifecycle_policy_id` | `policy_object_pending` |

---

## Signal-To-Expression Handoff

The A2 deterministic baseline consumes Module A/A1 signal context but does not override Module A/A1 authority.

Pilot 1B handoff rules:

- A2 may emit non-`WAIT` only when Module A's signal is non-`WAIT`, the direction maps to a single-leg `CALL` for long or `PUT` for short, and the selected option expression passes every hard A2 gate.
- If Module A says `LONG` but no liquid or valid `CALL` is available, A2 emits `WAIT` and records the reason in `health` or `conformance_gaps`.
- If Module A says `SHORT` but no liquid or valid `PUT` is available, A2 emits `WAIT` and records the reason in `health` or `conformance_gaps`.
- If Module A says `TRADE` but A2 has **`volatility`**, theta, spread, quote, replay, or lifecycle concerns, A2 emits `WAIT` or advisory `AVOID` according to the gate and records the disagreement.
- A2 cannot veto A1 for trade-impacting purposes during Pilot 1B. A2 disagreement is advisory and must be recorded in `health` or `conformance_gaps`, not applied as an authority block.

---

## Readiness Gates

A2 must emit `WAIT` or `AVOID` rather than an option recommendation when any hard gate fails.

Hard gates:

- missing selected expiry;
- selected expiry is not same-day when the profile is in strict 0DTE mode;
- no option-chain archive / current chain rows for selected expiry;
- no side-compatible contracts;
- missing bid or ask for selected contract;
- missing theta from both chain row and Black-Scholes approximation inputs;
- invalid or stale **`quoteTimeInLong`** (chain wire) once quote staleness is implemented; compare against adapter clock per execution-field contract. Threshold policy object: `a2_quote_staleness_threshold_ms`, TBD pending operator decision; recommended starting value is `2000ms` based on Schwab L1 quote latency profile;
- spread exceeds governed hard threshold once threshold policy is bound. Threshold policy object: `a2_spread_hard_threshold`, TBD pending operator decision; recommended starting value is `$0.10` absolute or `10%` of mid, whichever is tighter, for SPY/QQQ 0DTE;
- missing selected strike or option right;
- Module A signal is `WAIT` or unavailable;
- replay/live parity is failing once validation status is available.

Soft gates:

- wide spread but still scoreable under current deterministic baseline;
- missing optional **`volatility`** / Greeks fields;
- low **`totalVolume`** / **`openInterest`**;
- wall contribution unavailable;
- no validated fill-probability model yet.
- pin risk near strike at expiry;
- late-day gamma acceleration in the final 30 minutes;
- early assignment risk for any future short-option structure.

Soft gates must appear in `conformance_gaps` or `health`, never disappear silently.

---

## Existing Module Audit

| Surface | Current capability | A2 role | Main gaps |
|---|---|---|---|
| `market_state.recommend_option_expression` | Maps `long` to CALL, `short` to PUT, `wait` to NO TRADE; evaluates ATM and one ITM candidate; returns expression, reasons, and proof. | Deterministic expression-selection baseline. | Not options-native edge; no strict 0DTE mode; fallback may choose wide-spread winner; no fill probability; no lifecycle policy ID. |
| `math_probabilities.score_option_expression` | Scores derived spread, gamma, distance from underlying price (**`quotes.regular.regularMarketLastPrice`** or governed spot proxy) to strike, **`totalVolume`** / **`openInterest`**, gamma × OI, max gamma strike, and wall contribution. | Deterministic liquidity/Greeks score baseline. | Score is heuristic, not calibrated EV; no slippage/fill model; no quote staleness; no capacity model; incomplete theta/expiration handling. |
| `realized_contract_eval.py` | Replays selected option contracts with archived chain; entry ask, exit bid; underlying stop/target path; skip reasons and trade logs. | Starting point for A2 label/replay contract. | Current labels are evaluator outputs, not v2 A2 label schema; skip-rate gates need A2 ownership; no conformal bounds; **`volatility`/Greeks** path attribution incomplete. |
| `live_vs_replay_validation.py` | Compares live option selection proof with replayed selection from archived chain and replay context. | A2 replay/live parity validation support. | Validation quality is a sidecar report, not attached to live `v2_decision`; not yet a readiness gate. |
| `call_engine.py` | Has time-aware, VIX-aware stop geometry described for 0DTE trading. | Lifecycle/risk-geometry baseline. | Underlying-level geometry is not contract-level lifecycle EV; dynamic actions need validation versus static baseline. |
| `server.py` / Tier C payload | Already serializes selected chain, replay context, option proof, and decision bundle. | Attachment point for A2 advisory object. | Must avoid Tier B/L1 option work; A2 construction must fail soft. |

---

## Deterministic Baseline Scope

The first A2 implementation may wrap:

- `market_state.recommend_option_expression`;
- `math_probabilities.score_option_expression`;
- selected contract row snapshot fields;
- replay context entry/exit policy text when available;
- Module A/A1 probability as `P_underlying_entry_success`.

It must label these outputs as `v1_approximation` or `policy_object_pending` unless the field is pure contract shape.

No field may be labeled `v2_compliant` merely because it is present.

---

## Required Gap List For First Adapter

The first A2 adapter must include these gaps at minimum:

- `a2_contract_profit_labels_not_implemented`;
- `a2_execution_model_not_implemented`;
- `a2_fill_probability_not_implemented`;
- `a2_lifecycle_policy_pending`;
- `a2_replay_live_parity_not_gating_runtime`;
- `a2_options_native_provenance_not_bound`;
- `a2_calibrated_probability_interval_not_implemented`;
- `a2_contract_ev_not_implemented`;
- `a2_pin_risk_handling_not_implemented`;
- `a2_late_day_gamma_policy_pending` — **resolved** by **O-34**
  (advisory-warning-only v1 policy bound). Late-day gamma exposure
  may raise lifecycle/sidecar warning state but does not independently
  tighten stops, resize, or force exit. EOD force-exit timing remains
  governed by O-33.
- `a2_early_assignment_risk_not_implemented`.

Lifecycle child gaps under `a2_lifecycle_policy_pending` are governed by `governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`. That contract extends the umbrella gap without renaming or superseding existing A2 lifecycle leaves (`P_lifecycle_adjusted_profit`, `timeout_policy`, `lifecycle_policy_id`).

---

## Tests Required Before Runtime Attachment

Add focused tests before attaching A2 to Tier C:

- valid A2 deterministic baseline object validates schema;
- `WAIT` signal emits no option contract and records source indicators;
- missing bid/ask blocks trade output;
- wide spread records a soft or hard gate according to policy;
- selected contract fields include source indicators;
- required A2 probability/EV placeholders are present;
- A2 output remains nested under `v2_decision`;
- `A2.option_action` is coherent with `A1.decision.action`; if A1 says `TRADE LONG` and A2 says `AVOID`, A2 must record the reason in `conformance_gaps` or `health`;
- A2 card/UI text is read-only and labeled advisory if UI is added in this phase.

---

## Binary Closure Criteria

Pilot 1B contract phase is complete when:

- A2 contract fields are enumerated in a durable governance artifact;
- current 0DTE surfaces are audited against the contract;
- deterministic baseline scope is explicitly separated from trained edge;
- required A2 gaps are named before adapter work begins;
- no runtime behavior changes are made by the contract artifact.

Pilot 1B implementation phase is complete when:

- A2 deterministic baseline output is attached to Tier C `v2_decision`;
- A2 output is visibly separate from A1;
- every A2 leaf field has an allowed source indicator;
- hard readiness gates can block unsafe option recommendations;
- replay labels exist before any trained A2 model claim;
- tests enforce advisory-only, Tier C-only behavior.

